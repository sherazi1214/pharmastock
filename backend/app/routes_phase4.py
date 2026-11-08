"""PharmaStock 2027 - Phase 4: retail/wholesale sales (POS), FEFO stock deduction,
customer prices, credit limit check, invoices and sale returns.

PRICE RULE (important): the prices saved on a product (retail, wholesale, MRP) and a
customer's special price are for the LARGEST unit of that product (the pack/box).
The price of a smaller unit is worked out as:  pack price x unit factor / largest factor.
Example: box = 100 tablets, retail price 500 per box -> 1 strip of 10 = 50.00.
"""
import json
import sqlite3
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from .audit import log as audit_log
from .db import get_db
from .deps import require_owner, require_permission
from .routes_phase3 import schema as ensure_stock_schema
from .routes_products import ensure_schema as ensure_product_schema, parse_gs1

router = APIRouter(prefix="/api", tags=["sales"])


# ---------------------------------------------------------------- helpers
def stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def money(x: float) -> float:
    return round(x + (1e-9 if x >= 0 else -1e-9), 2)


def can_see_cost(user: dict) -> bool:
    return user["role"] == "owner" or "view_purchase_price" in user.get("permissions", [])


def can_discount(user: dict) -> bool:
    return user["role"] == "owner" or "give_discount" in user.get("permissions", [])


def ensure_sales_schema(c) -> None:
    ensure_product_schema(c)
    ensure_stock_schema(c)
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS business_flags(
            business_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
            PRIMARY KEY(business_id, key));

        CREATE TABLE IF NOT EXISTS customers(
            id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER NOT NULL,
            name TEXT NOT NULL, customer_type TEXT NOT NULL DEFAULT 'retail',
            phone TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '',
            licence_number TEXT NOT NULL DEFAULT '',
            credit_allowed INTEGER NOT NULL DEFAULT 0, credit_limit REAL NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(business_id, name));

        CREATE TABLE IF NOT EXISTS customer_prices(
            id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER NOT NULL,
            customer_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
            price REAL NOT NULL,
            UNIQUE(business_id, customer_id, product_id));

        CREATE TABLE IF NOT EXISTS sales(
            id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER NOT NULL,
            client_uuid TEXT NOT NULL, invoice_seq INTEGER NOT NULL, invoice_number TEXT NOT NULL,
            sale_type TEXT NOT NULL, customer_id INTEGER,
            subtotal REAL NOT NULL, discount REAL NOT NULL, total REAL NOT NULL,
            paid_amount REAL NOT NULL, due_amount REAL NOT NULL,
            payment_method TEXT NOT NULL DEFAULT '',
            returned_total REAL NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            created_by INTEGER, created_at TEXT NOT NULL,
            UNIQUE(business_id, client_uuid),
            UNIQUE(business_id, invoice_seq));

        CREATE TABLE IF NOT EXISTS sale_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER NOT NULL, sale_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL, unit_name TEXT NOT NULL, quantity REAL NOT NULL,
            unit_factor INTEGER NOT NULL, base_quantity INTEGER NOT NULL,
            pack_price REAL NOT NULL, line_gross REAL NOT NULL, line_discount REAL NOT NULL,
            line_total REAL NOT NULL, net_total REAL NOT NULL,
            cost_total REAL NOT NULL DEFAULT 0, returned_base INTEGER NOT NULL DEFAULT 0);

        CREATE TABLE IF NOT EXISTS sale_item_batches(
            id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER NOT NULL,
            sale_item_id INTEGER NOT NULL, batch_id INTEGER NOT NULL,
            base_quantity INTEGER NOT NULL, cost_per_base REAL NOT NULL DEFAULT 0,
            returned_base INTEGER NOT NULL DEFAULT 0);

        CREATE TABLE IF NOT EXISTS sale_returns(
            id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER NOT NULL, sale_id INTEGER NOT NULL,
            client_uuid TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL,
            total REAL NOT NULL, due_reduced REAL NOT NULL, refund_amount REAL NOT NULL,
            created_by INTEGER, created_at TEXT NOT NULL,
            UNIQUE(business_id, client_uuid));

        CREATE TABLE IF NOT EXISTS sale_return_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER NOT NULL, return_id INTEGER NOT NULL,
            sale_item_id INTEGER NOT NULL, batch_id INTEGER NOT NULL,
            base_quantity INTEGER NOT NULL, amount REAL NOT NULL);

        CREATE INDEX IF NOT EXISTS idx_sales_business_date ON sales(business_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_sales_customer ON sales(business_id, customer_id);
        CREATE INDEX IF NOT EXISTS idx_sale_items_sale ON sale_items(business_id, sale_id);
        """
    )
    c.commit()


def get_flag(c, b: int, key: str, default: str = "0") -> str:
    row = c.execute("SELECT value FROM business_flags WHERE business_id=? AND key=?", (b, key)).fetchone()
    return row["value"] if row else default


def product_units(c, b: int, product_id: int) -> list[dict]:
    return [dict(u) for u in c.execute(
        "SELECT name, factor FROM product_units WHERE business_id=? AND product_id=? ORDER BY factor", (b, product_id))]


def show_quantity(base: int, units: list[dict]) -> str:
    """e.g. 253 tablets -> '2 Box 5 Strip 3 Tablet'."""
    if not units:
        return str(base)
    if base < 0:
        return "-" + show_quantity(-base, units)
    parts, left = [], base
    for u in sorted(units, key=lambda u: -u["factor"]):
        n, left = divmod(left, u["factor"])
        if n:
            parts.append(f"{n} {u['name']}")
    return " ".join(parts) if parts else f"0 {units[0]['name']}"


def cost_per_base(c, b: int, batch_id: int, cache: dict) -> float:
    """Purchase cost of ONE base unit of this batch (from its latest purchase line)."""
    if batch_id not in cache:
        row = c.execute(
            "SELECT unit_cost, unit_factor FROM purchase_items WHERE business_id=? AND batch_id=? ORDER BY id DESC LIMIT 1",
            (b, batch_id)).fetchone()
        cache[batch_id] = (row["unit_cost"] / row["unit_factor"]) if row and row["unit_factor"] else 0.0
    return cache[batch_id]


def customer_outstanding(c, b: int, customer_id: int) -> float:
    row = c.execute("SELECT COALESCE(SUM(due_amount),0) v FROM sales WHERE business_id=? AND customer_id=?",
                    (b, customer_id)).fetchone()
    return money(row["v"])


def sellable_batches(c, b: int, product_id: int, today: str):
    return c.execute(
        """SELECT id, batch_number, expiry_date, quantity_base FROM batches
           WHERE business_id=? AND product_id=? AND status='active' AND expiry_date>=? AND quantity_base>0
           ORDER BY expiry_date, id""", (b, product_id, today)).fetchall()


def pos_product(c, b: int, p, today: str) -> dict:
    units = product_units(c, b, p["id"])
    sellable = sellable_batches(c, b, p["id"], today)
    qty = sum(r["quantity_base"] for r in sellable)
    return {
        "id": p["id"], "name": p["name"], "generic_name": p["generic_name"], "strength": p["strength"],
        "dosage_form": p["dosage_form"], "barcode": p["barcode"],
        "retail_price": p["retail_price"], "wholesale_price": p["wholesale_price"], "mrp": p["mrp"],
        "prescription_required": bool(p["prescription_required"]),
        "units": units, "pack_factor": units[-1]["factor"] if units else 1,
        "available_base": qty, "available_text": show_quantity(qty, units),
        "next_expiry": sellable[0]["expiry_date"] if sellable else None,
    }


# ---------------------------------------------------------------- models
class SaleLineIn(BaseModel):
    product_id: int
    unit_name: str = Field(min_length=1)
    quantity: float = Field(gt=0)
    discount: float = Field(default=0, ge=0)


class SaleIn(BaseModel):
    client_uuid: str = Field(min_length=8, max_length=64)
    sale_type: Literal["retail", "wholesale"]
    customer_id: int | None = None
    lines: list[SaleLineIn] = Field(min_length=1)
    discount: float = Field(default=0, ge=0)
    payment_method: str = ""
    paid_amount: float | None = Field(default=None, ge=0)
    notes: str = Field(default="", max_length=300)


class ReturnLineIn(BaseModel):
    sale_item_id: int
    unit_name: str = Field(min_length=1)
    quantity: float = Field(gt=0)


class ReturnIn(BaseModel):
    client_uuid: str = Field(min_length=8, max_length=64)
    action: Literal["restock", "write_off"]
    reason: str = Field(min_length=3, max_length=300)
    lines: list[ReturnLineIn] = Field(min_length=1)


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    customer_type: Literal["retail", "wholesale"] = "retail"
    phone: str = ""
    address: str = ""
    licence_number: str = ""
    credit_allowed: bool = False
    credit_limit: float = Field(default=0, ge=0)


class CustomerPriceIn(BaseModel):
    product_id: int
    price: float = Field(gt=0)


class SalesSettingsIn(BaseModel):
    allow_negative_stock: bool


# ---------------------------------------------------------------- settings
@router.get("/sales/settings")
def sales_settings(user=Depends(require_permission("manage_sales")), c=Depends(get_db)):
    ensure_sales_schema(c)
    b = user["business_id"]
    biz = c.execute("SELECT payment_methods FROM businesses WHERE id=?", (b,)).fetchone()
    try:
        methods = json.loads(biz["payment_methods"]) if biz else ["Cash"]
    except ValueError:
        methods = ["Cash"]
    return {"allow_negative_stock": get_flag(c, b, "allow_negative_stock") == "1", "payment_methods": methods}


@router.put("/sales/settings")
def save_sales_settings(x: SalesSettingsIn, user=Depends(require_owner), c=Depends(get_db)):
    ensure_sales_schema(c)
    b = user["business_id"]
    c.execute("INSERT INTO business_flags(business_id,key,value) VALUES(?,?,?) "
              "ON CONFLICT(business_id,key) DO UPDATE SET value=excluded.value",
              (b, "allow_negative_stock", "1" if x.allow_negative_stock else "0"))
    audit_log(c, b, user["id"], user["username"], "sales_settings_changed",
              f"allow_negative_stock={'on' if x.allow_negative_stock else 'off'}")
    return {"ok": True, "allow_negative_stock": x.allow_negative_stock}


# ---------------------------------------------------------------- POS lookups
@router.get("/sales/products")
def pos_products(search: str = "", user=Depends(require_permission("manage_sales")), c=Depends(get_db)):
    ensure_sales_schema(c)
    b, today = user["business_id"], date.today().isoformat()
    q = f"%{search.strip()}%"
    rows = c.execute(
        """SELECT * FROM products WHERE business_id=? AND status='active'
           AND (name LIKE ? OR generic_name LIKE ? OR barcode LIKE ?
                OR id IN (SELECT product_id FROM product_barcodes WHERE business_id=? AND barcode LIKE ?))
           ORDER BY name LIMIT 30""", (b, q, q, q, b, q)).fetchall()
    return {"items": [pos_product(c, b, p, today) for p in rows]}


@router.get("/sales/scan/{code:path}")
def pos_scan(code: str, user=Depends(require_permission("manage_sales")), c=Depends(get_db)):
    """Scanner types the code and presses Enter. Plain barcodes and GS1 DataMatrix both work."""
    ensure_sales_schema(c)
    b, today = user["business_id"], date.today().isoformat()
    raw = code.strip()
    gs1 = parse_gs1(raw)
    candidates = [raw]
    if gs1["is_gs1"]:
        g = gs1["gtin"]
        candidates = [g, g.lstrip("0"), g[1:] if g.startswith("0") else g, raw]
    product = None
    for cand in dict.fromkeys(x for x in candidates if x):
        product = c.execute(
            """SELECT p.* FROM products p
               LEFT JOIN product_barcodes pb ON pb.product_id=p.id AND pb.business_id=p.business_id
               WHERE p.business_id=? AND p.status='active' AND (p.barcode=? OR pb.barcode=?) LIMIT 1""",
            (b, cand, cand)).fetchone()
        if product:
            break
    if not product:
        return {"found": False, "message": "No product matches this barcode. Nothing was sold or saved."}
    return {"found": True, "product": pos_product(c, b, product, today),
            "gs1": {"batch": gs1["batch"], "expiry": gs1["expiry"]} if gs1["is_gs1"] else None}


@router.get("/sales/customers")
def pos_customers(user=Depends(require_permission("manage_sales")), c=Depends(get_db)):
    ensure_sales_schema(c)
    b = user["business_id"]
    rows = c.execute("SELECT id,name,customer_type,credit_allowed,credit_limit FROM customers "
                     "WHERE business_id=? AND is_active=1 ORDER BY name", (b,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["credit_allowed"] = bool(d["credit_allowed"])
        d["outstanding"] = customer_outstanding(c, b, r["id"])
        out.append(d)
    return {"items": out}


@router.get("/sales/customer-prices/{customer_id}")
def pos_customer_prices(customer_id: int, user=Depends(require_permission("manage_sales")), c=Depends(get_db)):
    ensure_sales_schema(c)
    b = user["business_id"]
    if not c.execute("SELECT id FROM customers WHERE id=? AND business_id=?", (customer_id, b)).fetchone():
        raise HTTPException(404, "Customer not found.")
    rows = c.execute("SELECT product_id, price FROM customer_prices WHERE business_id=? AND customer_id=?",
                     (b, customer_id)).fetchall()
    return {"prices": {str(r["product_id"]): r["price"] for r in rows}}


# ---------------------------------------------------------------- FEFO
def allocate_fefo(c, b: int, product, base_needed: int, today: str, allow_negative: bool, units: list[dict]):
    """Takes stock from the earliest-expiry sellable batch first. Returns [(batch_id, base_taken)]."""
    rows = sellable_batches(c, b, product["id"], today)
    available = sum(r["quantity_base"] for r in rows)
    taken, remaining = [], base_needed
    for r in rows:
        take = min(r["quantity_base"], remaining)
        taken.append([r["id"], take])
        remaining -= take
        if remaining <= 0:
            break
    if remaining > 0:
        if not allow_negative or not taken:
            blocked = c.execute(
                """SELECT COALESCE(SUM(quantity_base),0) v FROM batches WHERE business_id=? AND product_id=?
                   AND quantity_base>0 AND (status!='active' OR expiry_date<?)""", (b, product["id"], today)).fetchone()["v"]
            msg = (f"Not enough stock for {product['name']}. Available to sell: {show_quantity(available, units)}; "
                   f"you asked for {show_quantity(base_needed, units)}.")
            if blocked:
                msg += (f" {show_quantity(blocked, units)} more is expired, recalled, blocked or in quarantine "
                        f"and cannot be sold.")
            raise HTTPException(400, msg)
        taken[-1][1] += remaining  # owner allowed negative stock: shortfall goes on the last batch used
    return [(bid, qty) for bid, qty in taken]


# ---------------------------------------------------------------- create sale
def sale_summary(c, b: int, sale_id: int) -> dict:
    s = c.execute("SELECT id, invoice_number, total, paid_amount, due_amount FROM sales WHERE id=? AND business_id=?",
                  (sale_id, b)).fetchone()
    return dict(s)


@router.post("/sales", status_code=201)
def create_sale(x: SaleIn, response: Response, user=Depends(require_permission("manage_sales")), c=Depends(get_db)):
    ensure_sales_schema(c)
    b, today = user["business_id"], date.today().isoformat()
    uuid = x.client_uuid.strip()
    c.execute("BEGIN IMMEDIATE")
    try:
        # Same sale sent twice (double click, retry, offline queue replay) -> only one sale is ever saved.
        dup = c.execute("SELECT id FROM sales WHERE business_id=? AND client_uuid=?", (b, uuid)).fetchone()
        if dup:
            c.rollback()
            response.status_code = 200
            return {**sale_summary(c, b, dup["id"]), "duplicate": True,
                    "message": "This sale was already saved. No second sale was created."}

        customer = None
        if x.customer_id is not None:
            customer = c.execute("SELECT * FROM customers WHERE id=? AND business_id=? AND is_active=1",
                                 (x.customer_id, b)).fetchone()
            if not customer:
                raise HTTPException(404, "Customer not found.")
        if x.sale_type == "wholesale" and not customer:
            raise HTTPException(400, "Choose a customer for a wholesale sale.")

        allow_negative = get_flag(c, b, "allow_negative_stock") == "1"
        cost_cache: dict = {}
        prepared = []
        for ln in x.lines:
            p = c.execute("SELECT * FROM products WHERE id=? AND business_id=? AND status='active'",
                          (ln.product_id, b)).fetchone()
            if not p:
                raise HTTPException(404, "A selected product was not found or is inactive.")
            units = product_units(c, b, p["id"])
            unit = next((u for u in units if u["name"] == ln.unit_name), None)
            if not unit:
                raise HTTPException(400, f"{p['name']}: this unit does not exist for the product.")
            raw = ln.quantity * unit["factor"]
            base = round(raw)
            if base <= 0 or abs(base - raw) > 1e-7:
                raise HTTPException(400, f"{p['name']}: quantity must be a whole number of {units[0]['name']}.")

            if x.sale_type == "wholesale":
                special = c.execute("SELECT price FROM customer_prices WHERE business_id=? AND customer_id=? AND product_id=?",
                                    (b, customer["id"], p["id"])).fetchone()
                pack_price = special["price"] if special else p["wholesale_price"]
            else:
                pack_price = p["retail_price"]
            if pack_price <= 0:
                raise HTTPException(400, f"{p['name']}: no {x.sale_type} price is set. Set it on the Products page.")
            if p["mrp"] > 0 and pack_price > p["mrp"] + 1e-9:
                raise HTTPException(400, f"{p['name']}: price {pack_price:.2f} is above MRP {p['mrp']:.2f}. A sale above MRP is not allowed.")

            pack_factor = units[-1]["factor"]
            gross = money(pack_price * base / pack_factor)
            disc = money(ln.discount)
            if disc > 0 and not can_discount(user):
                raise HTTPException(403, "You do not have permission to give a discount.")
            if disc > gross + 1e-9:
                raise HTTPException(400, f"{p['name']}: discount is more than the line amount.")

            allocation = allocate_fefo(c, b, p, base, today, allow_negative, units)
            for batch_id, take in allocation:  # deduct now so a second line of the same medicine sees the reduced stock
                c.execute("UPDATE batches SET quantity_base=quantity_base-?, updated_at=? WHERE id=? AND business_id=?",
                          (take, stamp(), batch_id, b))
            cost = sum(take * cost_per_base(c, b, batch_id, cost_cache) for batch_id, take in allocation)
            prepared.append({"p": p, "unit": unit, "qty": ln.quantity, "base": base, "pack_price": pack_price,
                             "gross": gross, "disc": disc, "line": money(gross - disc),
                             "alloc": allocation, "cost": money(cost)})

        subtotal = money(sum(r["line"] for r in prepared))
        inv_disc = money(x.discount)
        if inv_disc > 0 and not can_discount(user):
            raise HTTPException(403, "You do not have permission to give a discount.")
        if inv_disc > subtotal + 1e-9:
            raise HTTPException(400, "Discount is more than the sale total.")
        total = money(subtotal - inv_disc)

        # spread invoice discount over lines (needed so returns refund the right amount)
        left = inv_disc
        for i, r in enumerate(prepared):
            share = left if i == len(prepared) - 1 else money(inv_disc * r["line"] / subtotal) if subtotal else 0
            r["net"] = money(r["line"] - share)
            left = money(left - share)

        methods = []
        biz = c.execute("SELECT payment_methods FROM businesses WHERE id=?", (b,)).fetchone()
        try:
            methods = json.loads(biz["payment_methods"])
        except (TypeError, ValueError):
            methods = ["Cash"]
        paid = money(total if x.paid_amount is None else x.paid_amount)
        if paid > total + 0.005:
            raise HTTPException(400, "Paid amount cannot be more than the sale total.")
        due = money(total - paid)
        method = x.payment_method.strip()
        if paid > 0:
            match = next((m for m in methods if m.lower() == method.lower()), None)
            if not match:
                raise HTTPException(400, "Choose one of the payment methods set in Settings.")
            method = match
        if due > 0.005:
            if not customer:
                raise HTTPException(400, "Choose a customer to sell on credit.")
            if not customer["credit_allowed"]:
                raise HTTPException(400, f"{customer['name']} is not allowed to buy on credit.")
            owing = customer_outstanding(c, b, customer["id"])
            if owing + due > customer["credit_limit"] + 0.005:
                raise HTTPException(400, f"Credit limit exceeded. {customer['name']} owes {owing:.2f}, limit is "
                                         f"{customer['credit_limit']:.2f}, this sale adds {due:.2f}.")

        seq = c.execute("SELECT COALESCE(MAX(invoice_seq),0)+1 n FROM sales WHERE business_id=?", (b,)).fetchone()["n"]
        now = stamp()
        sale_id = c.execute(
            """INSERT INTO sales(business_id,client_uuid,invoice_seq,invoice_number,sale_type,customer_id,subtotal,discount,
               total,paid_amount,due_amount,payment_method,notes,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (b, uuid, seq, f"INV-{seq:06d}", x.sale_type, customer["id"] if customer else None, subtotal, inv_disc, total,
             paid, due, method, x.notes.strip(), user["id"], now)).lastrowid
        for r in prepared:
            item_id = c.execute(
                """INSERT INTO sale_items(business_id,sale_id,product_id,unit_name,quantity,unit_factor,base_quantity,pack_price,
                   line_gross,line_discount,line_total,net_total,cost_total) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (b, sale_id, r["p"]["id"], r["unit"]["name"], r["qty"], r["unit"]["factor"], r["base"], r["pack_price"],
                 r["gross"], r["disc"], r["line"], r["net"], r["cost"])).lastrowid
            for batch_id, take in r["alloc"]:
                c.execute("INSERT INTO sale_item_batches(business_id,sale_item_id,batch_id,base_quantity,cost_per_base) VALUES(?,?,?,?,?)",
                          (b, item_id, batch_id, take, cost_per_base(c, b, batch_id, cost_cache)))
                c.execute(
                    """INSERT INTO stock_movements(business_id,product_id,batch_id,kind,quantity_base,reason,reference_type,
                       reference_id,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (b, r["p"]["id"], batch_id, "sale", -take, f"Sale {x.sale_type} INV-{seq:06d}", "sale", sale_id, user["id"], now))
        audit_log(c, b, user["id"], user["username"], "sale_created", f"INV-{seq:06d} total {total:.2f} due {due:.2f}")
        c.commit()
        return {"id": sale_id, "invoice_number": f"INV-{seq:06d}", "total": total, "paid_amount": paid,
                "due_amount": due, "duplicate": False, "message": "Sale saved and stock updated."}
    except sqlite3.IntegrityError:
        c.rollback()
        # lost a race with the identical sale: treat as duplicate
        dup = c.execute("SELECT id FROM sales WHERE business_id=? AND client_uuid=?", (b, uuid)).fetchone()
        if dup:
            response.status_code = 200
            return {**sale_summary(c, b, dup["id"]), "duplicate": True,
                    "message": "This sale was already saved. No second sale was created."}
        raise HTTPException(409, "The sale could not be saved. Please try again.")
    except Exception:
        c.rollback()
        raise


# ---------------------------------------------------------------- history / print
@router.get("/sales")
def sales_history(search: str = "", limit: int = Query(100, ge=1, le=500),
                  user=Depends(require_permission("manage_sales")), c=Depends(get_db)):
    ensure_sales_schema(c)
    b = user["business_id"]
    q = f"%{search.strip()}%"
    rows = c.execute(
        """SELECT s.id, s.invoice_number, s.sale_type, s.total, s.paid_amount, s.due_amount, s.returned_total,
                  s.payment_method, s.created_at, cu.name customer_name, u.full_name sold_by
           FROM sales s LEFT JOIN customers cu ON cu.id=s.customer_id AND cu.business_id=s.business_id
           LEFT JOIN users u ON u.id=s.created_by AND u.business_id=s.business_id
           WHERE s.business_id=? AND (s.invoice_number LIKE ? OR COALESCE(cu.name,'') LIKE ?)
           ORDER BY s.id DESC LIMIT ?""", (b, q, q, limit)).fetchall()
    return {"items": [dict(r) for r in rows]}


def load_sale(c, b: int, sale_id: int, user: dict) -> dict:
    s = c.execute(
        """SELECT s.*, cu.name customer_name, cu.phone customer_phone, cu.address customer_address
           FROM sales s LEFT JOIN customers cu ON cu.id=s.customer_id AND cu.business_id=s.business_id
           WHERE s.id=? AND s.business_id=?""", (sale_id, b)).fetchone()
    if not s:
        raise HTTPException(404, "Sale not found.")
    items = []
    for it in c.execute(
            """SELECT i.*, p.name product_name, p.strength FROM sale_items i
               JOIN products p ON p.id=i.product_id AND p.business_id=i.business_id
               WHERE i.sale_id=? AND i.business_id=? ORDER BY i.id""", (sale_id, b)):
        d = dict(it)
        d["batches"] = [dict(x) for x in c.execute(
            """SELECT sb.base_quantity, sb.returned_base, ba.batch_number, ba.expiry_date FROM sale_item_batches sb
               JOIN batches ba ON ba.id=sb.batch_id AND ba.business_id=sb.business_id
               WHERE sb.sale_item_id=? AND sb.business_id=? ORDER BY sb.id""", (it["id"], b))]
        if not can_see_cost(user):
            d.pop("cost_total", None)
        items.append(d)
    returns = [dict(r) for r in c.execute(
        "SELECT id, action, reason, total, due_reduced, refund_amount, created_at FROM sale_returns "
        "WHERE sale_id=? AND business_id=? ORDER BY id", (sale_id, b))]
    sale = dict(s)
    sale.pop("client_uuid", None)
    return {"sale": sale, "items": items, "returns": returns}


@router.get("/sales/{sale_id}")
def sale_detail(sale_id: int, user=Depends(require_permission("manage_sales")), c=Depends(get_db)):
    ensure_sales_schema(c)
    return load_sale(c, user["business_id"], sale_id, user)


@router.get("/sales/{sale_id}/print")
def sale_print(sale_id: int, user=Depends(require_permission("manage_sales")), c=Depends(get_db)):
    ensure_sales_schema(c)
    b = user["business_id"]
    data = load_sale(c, b, sale_id, user)
    biz = c.execute("SELECT name, address, phone, licence_number FROM businesses WHERE id=?", (b,)).fetchone()
    data["business"] = dict(biz)
    return data


# ---------------------------------------------------------------- returns
@router.post("/sales/{sale_id}/returns", status_code=201)
def create_return(sale_id: int, x: ReturnIn, response: Response,
                  user=Depends(require_permission("manage_sales")), c=Depends(get_db)):
    ensure_sales_schema(c)
    b, today = user["business_id"], date.today().isoformat()
    uuid = x.client_uuid.strip()
    c.execute("BEGIN IMMEDIATE")
    try:
        dup = c.execute("SELECT id, total FROM sale_returns WHERE business_id=? AND client_uuid=?", (b, uuid)).fetchone()
        if dup:
            c.rollback()
            response.status_code = 200
            return {"id": dup["id"], "total": dup["total"], "duplicate": True, "message": "This return was already saved."}
        sale = c.execute("SELECT * FROM sales WHERE id=? AND business_id=?", (sale_id, b)).fetchone()
        if not sale:
            raise HTTPException(404, "Sale not found.")

        now, total_amount = stamp(), 0.0
        moves, return_rows = [], []
        for ln in x.lines:
            item = c.execute("SELECT * FROM sale_items WHERE id=? AND sale_id=? AND business_id=?",
                             (ln.sale_item_id, sale_id, b)).fetchone()
            if not item:
                raise HTTPException(404, "A returned item does not belong to this sale.")
            units = product_units(c, b, item["product_id"])
            unit = next((u for u in units if u["name"] == ln.unit_name), None)
            if not unit:
                raise HTTPException(400, "This unit does not exist for the product.")
            raw = ln.quantity * unit["factor"]
            base = round(raw)
            if base <= 0 or abs(base - raw) > 1e-7:
                raise HTTPException(400, "Return quantity must be a whole number of the smallest unit.")
            returnable = item["base_quantity"] - item["returned_base"]
            if base > returnable:
                raise HTTPException(400, f"Only {show_quantity(returnable, units)} of this item can still be returned.")

            before = money(item["net_total"] * item["returned_base"] / item["base_quantity"])
            after = money(item["net_total"] * (item["returned_base"] + base) / item["base_quantity"])
            amount = money(after - before)
            total_amount += amount

            left = base
            item_rows = []
            for sb in c.execute("SELECT * FROM sale_item_batches WHERE sale_item_id=? AND business_id=? ORDER BY id",
                                (item["id"], b)).fetchall():
                if left <= 0:
                    break
                room = sb["base_quantity"] - sb["returned_base"]
                if room <= 0:
                    continue
                give = min(room, left)
                left -= give
                batch = c.execute("SELECT * FROM batches WHERE id=? AND business_id=?", (sb["batch_id"], b)).fetchone()
                if x.action == "restock" and (batch["status"] != "active" or batch["expiry_date"] < today):
                    raise HTTPException(400, f"Batch {batch['batch_number']} is expired, recalled, blocked or in quarantine. "
                                             f"Choose 'Write off' for this return.")
                c.execute("UPDATE sale_item_batches SET returned_base=returned_base+? WHERE id=? AND business_id=?",
                          (give, sb["id"], b))
                if x.action == "restock":
                    c.execute("UPDATE batches SET quantity_base=quantity_base+?, updated_at=? WHERE id=? AND business_id=?",
                              (give, now, batch["id"], b))
                moves.append((item["product_id"], batch["id"], give))
                item_rows.append([item["id"], batch["id"], give, 0.0])
            if left > 0:
                raise HTTPException(400, "This item cannot be returned: its batch records do not match the quantity sold.")
            item_rows[0][3] = amount  # the money of this line is recorded on its first batch row
            return_rows.extend(item_rows)
            c.execute("UPDATE sale_items SET returned_base=returned_base+? WHERE id=? AND business_id=?", (base, item["id"], b))

        total_amount = money(total_amount)
        due_cut = money(min(sale["due_amount"], total_amount))
        refund = money(total_amount - due_cut)
        return_id = c.execute(
            """INSERT INTO sale_returns(business_id,sale_id,client_uuid,action,reason,total,due_reduced,refund_amount,created_by,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (b, sale_id, uuid, x.action, x.reason.strip(), total_amount, due_cut, refund, user["id"], now)).lastrowid
        for item_id, batch_id, give, amount in return_rows:
            c.execute("INSERT INTO sale_return_items(business_id,return_id,sale_item_id,batch_id,base_quantity,amount) VALUES(?,?,?,?,?,?)",
                      (b, return_id, item_id, batch_id, give, amount))
        kind = "sale_return" if x.action == "restock" else "return_write_off"
        for product_id, batch_id, give in moves:
            qty = give if x.action == "restock" else 0
            reason = f"Return on {sale['invoice_number']}: {x.reason.strip()}" + ("" if x.action == "restock" else f" (written off {give} base units)")
            c.execute(
                """INSERT INTO stock_movements(business_id,product_id,batch_id,kind,quantity_base,reason,reference_type,
                   reference_id,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (b, product_id, batch_id, kind, qty, reason, "sale_return", return_id, user["id"], now))
        c.execute("UPDATE sales SET returned_total=returned_total+?, due_amount=due_amount-? WHERE id=? AND business_id=?",
                  (total_amount, due_cut, sale_id, b))
        audit_log(c, b, user["id"], user["username"], "sale_return", f"{sale['invoice_number']} {x.action} {total_amount:.2f}")
        c.commit()
        return {"id": return_id, "total": total_amount, "due_reduced": due_cut, "refund_amount": refund,
                "duplicate": False, "message": "Return saved."}
    except sqlite3.IntegrityError:
        c.rollback()
        raise HTTPException(409, "This return could not be saved. It may already exist.")
    except Exception:
        c.rollback()
        raise


# ---------------------------------------------------------------- customers (basic)
def customer_row(c, b: int, r) -> dict:
    d = dict(r)
    d["credit_allowed"] = bool(d["credit_allowed"])
    d["outstanding"] = customer_outstanding(c, b, r["id"])
    return d


@router.get("/customers")
def customers(user=Depends(require_permission("manage_customers")), c=Depends(get_db)):
    ensure_sales_schema(c)
    b = user["business_id"]
    rows = c.execute("SELECT * FROM customers WHERE business_id=? ORDER BY name", (b,)).fetchall()
    return {"items": [customer_row(c, b, r) for r in rows]}


@router.post("/customers", status_code=201)
def add_customer(x: CustomerIn, user=Depends(require_permission("manage_customers")), c=Depends(get_db)):
    ensure_sales_schema(c)
    b = user["business_id"]
    if user["role"] != "owner" and (x.credit_allowed or x.credit_limit > 0):
        raise HTTPException(403, "Only the owner can allow credit for a customer.")
    now = stamp()
    try:
        cur = c.execute(
            """INSERT INTO customers(business_id,name,customer_type,phone,address,licence_number,credit_allowed,credit_limit,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (b, x.name.strip(), x.customer_type, x.phone, x.address, x.licence_number, int(x.credit_allowed), x.credit_limit, now, now))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "A customer with this name already exists.")
    audit_log(c, b, user["id"], user["username"], "customer_added", x.name.strip())
    return {"id": cur.lastrowid, "ok": True}


@router.put("/customers/{customer_id}")
def edit_customer(customer_id: int, x: CustomerIn, user=Depends(require_permission("manage_customers")), c=Depends(get_db)):
    ensure_sales_schema(c)
    b = user["business_id"]
    cur_row = c.execute("SELECT * FROM customers WHERE id=? AND business_id=?", (customer_id, b)).fetchone()
    if not cur_row:
        raise HTTPException(404, "Customer not found.")
    if user["role"] != "owner" and (bool(cur_row["credit_allowed"]) != x.credit_allowed or abs(cur_row["credit_limit"] - x.credit_limit) > 1e-9):
        raise HTTPException(403, "Only the owner can change credit settings.")
    try:
        c.execute(
            """UPDATE customers SET name=?,customer_type=?,phone=?,address=?,licence_number=?,credit_allowed=?,credit_limit=?,updated_at=?
               WHERE id=? AND business_id=?""",
            (x.name.strip(), x.customer_type, x.phone, x.address, x.licence_number, int(x.credit_allowed), x.credit_limit,
             stamp(), customer_id, b))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "A customer with this name already exists.")
    audit_log(c, b, user["id"], user["username"], "customer_changed", x.name.strip())
    return {"ok": True}


@router.get("/customers/{customer_id}/prices")
def list_customer_prices(customer_id: int, user=Depends(require_permission("manage_customers")), c=Depends(get_db)):
    ensure_sales_schema(c)
    b = user["business_id"]
    if not c.execute("SELECT id FROM customers WHERE id=? AND business_id=?", (customer_id, b)).fetchone():
        raise HTTPException(404, "Customer not found.")
    rows = c.execute(
        """SELECT cp.product_id, cp.price, p.name product_name, p.wholesale_price, p.mrp FROM customer_prices cp
           JOIN products p ON p.id=cp.product_id AND p.business_id=cp.business_id
           WHERE cp.business_id=? AND cp.customer_id=? ORDER BY p.name""", (b, customer_id)).fetchall()
    return {"items": [dict(r) for r in rows]}


@router.put("/customers/{customer_id}/prices")
def set_customer_price(customer_id: int, x: CustomerPriceIn, user=Depends(require_permission("manage_customers")), c=Depends(get_db)):
    ensure_sales_schema(c)
    b = user["business_id"]
    if not c.execute("SELECT id FROM customers WHERE id=? AND business_id=?", (customer_id, b)).fetchone():
        raise HTTPException(404, "Customer not found.")
    p = c.execute("SELECT id, name, mrp FROM products WHERE id=? AND business_id=?", (x.product_id, b)).fetchone()
    if not p:
        raise HTTPException(404, "Product not found.")
    if p["mrp"] > 0 and x.price > p["mrp"] + 1e-9:
        raise HTTPException(400, f"Special price cannot be above MRP ({p['mrp']:.2f}).")
    c.execute("INSERT INTO customer_prices(business_id,customer_id,product_id,price) VALUES(?,?,?,?) "
              "ON CONFLICT(business_id,customer_id,product_id) DO UPDATE SET price=excluded.price",
              (b, customer_id, x.product_id, x.price))
    audit_log(c, b, user["id"], user["username"], "customer_price_set", f"customer {customer_id} product {p['name']} {x.price:.2f}")
    return {"ok": True}


@router.delete("/customers/{customer_id}/prices/{product_id}")
def delete_customer_price(customer_id: int, product_id: int, user=Depends(require_permission("manage_customers")), c=Depends(get_db)):
    ensure_sales_schema(c)
    b = user["business_id"]
    c.execute("DELETE FROM customer_prices WHERE business_id=? AND customer_id=? AND product_id=?", (b, customer_id, product_id))
    return {"ok": True}
