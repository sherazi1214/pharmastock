"""PharmaStock 2027 - Phase 5: customer accounts + payments, real dashboard, reports (print / Excel / CSV).

All numbers come from the database. Nothing is estimated except profit, which is labelled
"Estimated gross profit" (sales - batch cost of goods sold - returns). Expenses are not tracked.
"""
import base64
import csv
import io
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from .audit import log as audit_log
from .db import get_db
from .deps import require_permission
from .routes_phase4 import (ensure_sales_schema, money, product_units, show_quantity, stamp, customer_outstanding,
                            can_see_cost)

try:  # any logged-in user (used by the dashboard)
    from .deps import get_current_user as current_user
except ImportError:  # pragma: no cover
    from .deps import current_user  # type: ignore

router = APIRouter(prefix="/api", tags=["customers-dashboard-reports"])

PROFIT_NOTE = ("Estimated gross profit = sales - batch cost of goods sold - returns. "
               "Net profit needs expenses (rent, salaries, bills), which this software does not track.")


# ------------------------------------------------------------ permissions
def has_perm(user: dict, perm: str) -> bool:
    return user["role"] == "owner" or perm in user.get("permissions", [])


def can_see_profit(user: dict) -> bool:
    return has_perm(user, "view_profit")


def can_see_balances(user: dict) -> bool:
    return has_perm(user, "view_balances")


def ensure_p5_schema(c) -> None:
    ensure_sales_schema(c)
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS customer_payments(
            id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER NOT NULL, customer_id INTEGER NOT NULL,
            client_uuid TEXT NOT NULL, amount REAL NOT NULL, method TEXT NOT NULL DEFAULT '',
            reference TEXT NOT NULL DEFAULT '', created_by INTEGER, created_at TEXT NOT NULL,
            UNIQUE(business_id, client_uuid));
        CREATE TABLE IF NOT EXISTS customer_payment_allocations(
            id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER NOT NULL, payment_id INTEGER NOT NULL,
            sale_id INTEGER NOT NULL, amount REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_custpay_customer ON customer_payments(business_id, customer_id);
        CREATE INDEX IF NOT EXISTS idx_custalloc_payment ON customer_payment_allocations(business_id, payment_id);
        """)
    c.commit()


def payment_methods(c, b: int) -> list[str]:
    import json
    row = c.execute("SELECT payment_methods FROM businesses WHERE id=?", (b,)).fetchone()
    try:
        m = json.loads(row["payment_methods"]) if row else None
    except (TypeError, ValueError):
        m = None
    return m or ["Cash"]


# ------------------------------------------------------------ dates
def local_day_bounds(d1: date, d2: date) -> tuple[str, str]:
    """[start, end) in UTC text for the local days d1..d2 (inclusive). created_at is stored in UTC."""
    def utc(d: date) -> str:
        return datetime(d.year, d.month, d.day).astimezone().astimezone(timezone.utc).isoformat(timespec="seconds")
    return utc(d1), utc(d2 + timedelta(days=1))


def local_date_of(text: str) -> date:
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().date()


def parse_range(from_date: str | None, to_date: str | None) -> tuple[date, date]:
    today = date.today()
    try:
        d2 = date.fromisoformat(to_date) if to_date else today
        d1 = date.fromisoformat(from_date) if from_date else d2.replace(day=1)
    except ValueError:
        raise HTTPException(400, "Enter valid dates (YYYY-MM-DD).")
    if d1 > d2:
        raise HTTPException(400, "The 'from' date cannot be after the 'to' date.")
    if (d2 - d1).days > 3660:
        raise HTTPException(400, "Please choose a date range of 10 years or less.")
    return d1, d2


def near_days(c, b: int) -> int:
    r = c.execute("SELECT near_expiry_days FROM businesses WHERE id=?", (b,)).fetchone()
    try:
        return int(r["near_expiry_days"]) if r else 90
    except (TypeError, ValueError):
        return 90


COST_BASE_SQL = ("(SELECT pi.unit_cost*1.0/pi.unit_factor FROM purchase_items pi "
                 "WHERE pi.batch_id=ba.id AND pi.business_id=ba.business_id ORDER BY pi.id DESC LIMIT 1)")


def stock_value(c, b: int) -> float:
    """Same rule as the Stock page: batch quantity x cost of ONE base unit."""
    r = c.execute(f"SELECT COALESCE(SUM(ROUND(ba.quantity_base*COALESCE({COST_BASE_SQL},0),2)),0) v "
                  f"FROM batches ba WHERE ba.business_id=?", (b,)).fetchone()
    return money(r["v"])


def low_stock_rows(c, b: int, today: str) -> list:
    return c.execute(
        """SELECT p.id, p.name, p.strength, p.minimum_stock,
                  COALESCE((SELECT SUM(ba.quantity_base) FROM batches ba WHERE ba.business_id=p.business_id
                            AND ba.product_id=p.id AND ba.status='active' AND ba.expiry_date>=?),0) available
           FROM products p WHERE p.business_id=? AND p.status='active' AND p.minimum_stock>0
           ORDER BY p.name""", (today, b)).fetchall()


def near_expiry_where(days: int, today: date) -> tuple[str, tuple]:
    return ("ba.quantity_base>0 AND ba.status='active' AND ba.expiry_date>=? AND ba.expiry_date<=?",
            (today.isoformat(), (today + timedelta(days=days)).isoformat()))


# ============================================================ CUSTOMER ACCOUNTS
class CustomerPaymentIn(BaseModel):
    client_uuid: str = Field(min_length=8, max_length=64)
    amount: float = Field(gt=0)
    method: str = Field(min_length=1, max_length=50)
    reference: str = Field(default="", max_length=200)


def _customer_or_404(c, b: int, customer_id: int):
    cu = c.execute("SELECT * FROM customers WHERE id=? AND business_id=?", (customer_id, b)).fetchone()
    if not cu:
        raise HTTPException(404, "Customer not found.")
    return cu


@router.get("/customers/{customer_id}/account")
def customer_account(customer_id: int, user=Depends(require_permission("manage_customers")), c=Depends(get_db)):
    ensure_p5_schema(c)
    b = user["business_id"]
    cu = _customer_or_404(c, b, customer_id)
    outstanding = customer_outstanding(c, b, customer_id)
    open_invoices = [dict(r) for r in c.execute(
        "SELECT id, invoice_number, created_at, total, paid_amount, due_amount FROM sales "
        "WHERE business_id=? AND customer_id=? AND due_amount>0.004 ORDER BY created_at, id", (b, customer_id))]
    sales = [dict(r) for r in c.execute(
        "SELECT id, invoice_number, sale_type, created_at, total, paid_amount, due_amount, returned_total FROM sales "
        "WHERE business_id=? AND customer_id=? ORDER BY id DESC LIMIT 200", (b, customer_id))]
    pays = []
    for p in c.execute(
            "SELECT p.id, p.amount, p.method, p.reference, p.created_at, u.full_name received_by FROM customer_payments p "
            "LEFT JOIN users u ON u.id=p.created_by AND u.business_id=p.business_id "
            "WHERE p.business_id=? AND p.customer_id=? ORDER BY p.id DESC LIMIT 200", (b, customer_id)):
        d = dict(p)
        d["applied_to"] = [dict(a) for a in c.execute(
            "SELECT s.invoice_number, a.amount FROM customer_payment_allocations a JOIN sales s "
            "ON s.id=a.sale_id AND s.business_id=a.business_id WHERE a.payment_id=? AND a.business_id=? ORDER BY a.id",
            (p["id"], b))]
        pays.append(d)
    return {
        "customer": {"id": cu["id"], "name": cu["name"], "customer_type": cu["customer_type"], "phone": cu["phone"],
                     "address": cu["address"], "licence_number": cu["licence_number"],
                     "credit_allowed": bool(cu["credit_allowed"]), "credit_limit": cu["credit_limit"]},
        "outstanding": outstanding,
        "credit_left": money(max(0.0, cu["credit_limit"] - outstanding)) if cu["credit_allowed"] else 0.0,
        "open_invoices": open_invoices, "sales": sales, "payments": pays,
        "payment_methods": payment_methods(c, b),
    }


@router.post("/customers/{customer_id}/payments", status_code=201)
def receive_customer_payment(customer_id: int, x: CustomerPaymentIn, response: Response,
                             user=Depends(require_permission("manage_customers")), c=Depends(get_db)):
    """Money received from a customer. Applied to the OLDEST unpaid invoices first. Same client_uuid = saved once."""
    ensure_p5_schema(c)
    b = user["business_id"]
    uuid = x.client_uuid.strip()
    amount = money(x.amount)
    if amount <= 0:
        raise HTTPException(400, "Enter an amount greater than zero.")
    c.execute("BEGIN IMMEDIATE")
    try:
        dup = c.execute("SELECT id, amount FROM customer_payments WHERE business_id=? AND client_uuid=?", (b, uuid)).fetchone()
        if dup:
            c.rollback()
            response.status_code = 200
            return {"id": dup["id"], "amount": dup["amount"], "duplicate": True,
                    "message": "This payment was already saved. It was not added twice."}
        _customer_or_404(c, b, customer_id)
        method = next((m for m in payment_methods(c, b) if m.lower() == x.method.strip().lower()), None)
        if not method:
            raise HTTPException(400, "Choose one of the payment methods set in Settings.")
        owing = customer_outstanding(c, b, customer_id)
        if owing <= 0.004:
            raise HTTPException(400, "This customer has nothing to pay.")
        if amount > owing + 0.005:
            raise HTTPException(400, f"The customer owes only {owing:.2f}. You entered {amount:.2f}.")
        now = stamp()
        pid = c.execute(
            "INSERT INTO customer_payments(business_id,customer_id,client_uuid,amount,method,reference,created_by,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)", (b, customer_id, uuid, amount, method, x.reference.strip(), user["id"], now)).lastrowid
        left, applied_to = amount, []
        for inv in c.execute("SELECT id, invoice_number, due_amount FROM sales WHERE business_id=? AND customer_id=? "
                             "AND due_amount>0.004 ORDER BY created_at, id", (b, customer_id)).fetchall():
            if left <= 0.004:
                break
            take = money(min(left, inv["due_amount"]))
            new_due = money(inv["due_amount"] - take)
            c.execute("UPDATE sales SET paid_amount=paid_amount+?, due_amount=? WHERE id=? AND business_id=?",
                      (take, 0.0 if new_due < 0.005 else new_due, inv["id"], b))
            c.execute("INSERT INTO customer_payment_allocations(business_id,payment_id,sale_id,amount) VALUES(?,?,?,?)",
                      (b, pid, inv["id"], take))
            applied_to.append({"invoice_number": inv["invoice_number"], "amount": take})
            left = money(left - take)
        audit_log(c, b, user["id"], user["username"], "customer_payment", f"customer {customer_id} {amount:.2f} {method}")
        c.commit()
        return {"id": pid, "amount": amount, "applied_to": applied_to,
                "outstanding": customer_outstanding(c, b, customer_id), "duplicate": False,
                "message": "Payment saved. Oldest invoices were paid first."}
    except sqlite3.IntegrityError:
        c.rollback()
        dup = c.execute("SELECT id, amount FROM customer_payments WHERE business_id=? AND client_uuid=?", (b, uuid)).fetchone()
        if dup:
            response.status_code = 200
            return {"id": dup["id"], "amount": dup["amount"], "duplicate": True,
                    "message": "This payment was already saved. It was not added twice."}
        raise HTTPException(409, "The payment could not be saved. Please try again.")
    except Exception:
        c.rollback()
        raise


# ============================================================ DASHBOARD
@router.get("/dashboard")
def dashboard(user=Depends(current_user), c=Depends(get_db)):
    ensure_p5_schema(c)
    b, today = user["business_id"], date.today()
    start, end = local_day_bounds(today, today)
    out: dict = {"date": today.isoformat(), "today_sales": None, "today_returns": None, "today_purchases": None,
                 "stock_value": None, "low_stock_count": None, "near_expiry_count": None, "customer_outstanding": None}
    if has_perm(user, "manage_sales") or has_perm(user, "view_reports"):
        r = c.execute("SELECT COALESCE(SUM(total),0) t, COUNT(*) n FROM sales WHERE business_id=? AND created_at>=? AND created_at<?",
                      (b, start, end)).fetchone()
        rr = c.execute("SELECT COALESCE(SUM(total),0) t FROM sale_returns WHERE business_id=? AND created_at>=? AND created_at<?",
                       (b, start, end)).fetchone()
        out.update(today_sales=money(r["t"]), today_invoices=r["n"], today_returns=money(rr["t"]))
    if has_perm(user, "manage_purchases") or can_see_cost(user):
        r = c.execute("SELECT COALESCE(SUM(total),0) t FROM purchases WHERE business_id=? AND purchase_date=?",
                      (b, today.isoformat())).fetchone()
        out["today_purchases"] = money(r["t"])
    if can_see_cost(user):
        out["stock_value"] = stock_value(c, b)
    if has_perm(user, "view_stock") or has_perm(user, "view_reports"):
        out["low_stock_count"] = sum(1 for r in low_stock_rows(c, b, today.isoformat()) if r["available"] <= r["minimum_stock"])
        w, args = near_expiry_where(near_days(c, b), today)
        out["near_expiry_count"] = c.execute(f"SELECT COUNT(*) n FROM batches ba WHERE ba.business_id=? AND {w}", (b, *args)).fetchone()["n"]
    if can_see_balances(user):
        r = c.execute("SELECT COALESCE(SUM(due_amount),0) v FROM sales WHERE business_id=? AND customer_id IS NOT NULL", (b,)).fetchone()
        out["customer_outstanding"] = money(r["v"])
    shortcuts = []
    if has_perm(user, "manage_sales"):
        shortcuts += [{"label": "New Sale", "href": "/sales"}, {"label": "Scan Medicine", "href": "/products"}]
    elif has_perm(user, "manage_products") or has_perm(user, "view_stock"):
        shortcuts.append({"label": "Scan Medicine", "href": "/products"})
    if has_perm(user, "manage_purchases"):
        shortcuts.append({"label": "New Purchase", "href": "/purchase"})
    if has_perm(user, "manage_products"):
        shortcuts.append({"label": "Add Product", "href": "/products"})
    out["shortcuts"] = shortcuts
    return out


# ============================================================ REPORTS
def col(key: str, label: str, typ: str = "text") -> dict:
    return {"key": key, "label": label, "type": typ}


def units_by_product(c, b: int) -> dict[int, list[dict]]:
    m: dict[int, list[dict]] = {}
    for u in c.execute("SELECT product_id, name, factor FROM product_units WHERE business_id=? ORDER BY factor", (b,)):
        m.setdefault(u["product_id"], []).append({"name": u["name"], "factor": u["factor"]})
    return m


def r_daily_sales(c, b, user, d1, d2):
    s, e = local_day_bounds(d1, d2)
    days: dict[str, dict] = {}
    def day(k):
        return days.setdefault(k, {"date": k, "invoices": 0, "subtotal": 0.0, "discount": 0.0, "total": 0.0, "returns": 0.0})
    for r in c.execute("SELECT created_at, subtotal, discount, total FROM sales WHERE business_id=? AND created_at>=? AND created_at<?", (b, s, e)):
        d = day(local_date_of(r["created_at"]).isoformat())
        d["invoices"] += 1; d["subtotal"] += r["subtotal"]; d["discount"] += r["discount"]; d["total"] += r["total"]
    for r in c.execute("SELECT created_at, total FROM sale_returns WHERE business_id=? AND created_at>=? AND created_at<?", (b, s, e)):
        day(local_date_of(r["created_at"]).isoformat())["returns"] += r["total"]
    rows = []
    for k in sorted(days):
        d = days[k]
        rows.append({**d, **{f: money(d[f]) for f in ("subtotal", "discount", "total", "returns")}, "net_sales": money(d["total"] - d["returns"])})
    tot = {"invoices": sum(r["invoices"] for r in rows)}
    for f in ("subtotal", "discount", "total", "returns", "net_sales"):
        tot[f] = money(sum(r[f] for r in rows))
    return {"title": "Daily sales", "columns": [col("date", "Date", "date"), col("invoices", "Invoices", "int"), col("subtotal", "Before discount", "money"),
            col("discount", "Discount", "money"), col("total", "Sales total", "money"), col("returns", "Returns", "money"), col("net_sales", "Net sales", "money")],
            "rows": rows, "totals": tot, "note": "Returns are counted on the day the return was made."}


def r_monthly_sales(c, b, user, d1, d2):
    base = r_daily_sales(c, b, user, d1, d2)
    months: dict[str, dict] = {}
    for r in base["rows"]:
        m = months.setdefault(r["date"][:7], {"month": r["date"][:7], "invoices": 0, "total": 0.0, "discount": 0.0, "returns": 0.0})
        m["invoices"] += r["invoices"]; m["total"] += r["total"]; m["discount"] += r["discount"]; m["returns"] += r["returns"]
    rows = [{**m, "total": money(m["total"]), "discount": money(m["discount"]), "returns": money(m["returns"]),
             "net_sales": money(m["total"] - m["returns"])} for _, m in sorted(months.items())]
    tot = {"invoices": sum(r["invoices"] for r in rows)}
    for f in ("total", "discount", "returns", "net_sales"):
        tot[f] = money(sum(r[f] for r in rows))
    return {"title": "Monthly sales", "columns": [col("month", "Month"), col("invoices", "Invoices", "int"), col("discount", "Discount", "money"),
            col("total", "Sales total", "money"), col("returns", "Returns", "money"), col("net_sales", "Net sales", "money")],
            "rows": rows, "totals": tot, "note": ""}


def r_purchase_history(c, b, user, d1, d2):
    rows = [dict(r) for r in c.execute(
        "SELECT p.purchase_date, p.invoice_number, s.name supplier, p.total, p.paid_amount paid, p.due_amount due FROM purchases p "
        "JOIN suppliers s ON s.id=p.supplier_id AND s.business_id=p.business_id WHERE p.business_id=? AND p.purchase_date>=? AND p.purchase_date<=? "
        "ORDER BY p.purchase_date, p.id", (b, d1.isoformat(), d2.isoformat()))]
    for r in rows:
        for f in ("total", "paid", "due"):
            r[f] = money(r[f])
    return {"title": "Purchase history", "columns": [col("purchase_date", "Date", "date"), col("invoice_number", "Invoice"), col("supplier", "Supplier"),
            col("total", "Total", "money"), col("paid", "Paid", "money"), col("due", "Unpaid", "money")], "rows": rows,
            "totals": {f: money(sum(r[f] for r in rows)) for f in ("total", "paid", "due")}, "note": ""}


def _batch_rows(c, b, where: str, args: tuple, order: str):
    return c.execute(
        f"SELECT ba.id, ba.product_id, ba.batch_number, ba.expiry_date, ba.quantity_base, ba.status, p.name product_name, p.strength, "
        f"ROUND(ba.quantity_base*COALESCE({COST_BASE_SQL},0),2) value FROM batches ba JOIN products p ON p.id=ba.product_id "
        f"AND p.business_id=ba.business_id WHERE ba.business_id=? AND {where} ORDER BY {order}", (b, *args)).fetchall()


def _batch_report(c, b, user, rows, title, note, with_days=False):
    um, today, cost = units_by_product(c, b), date.today(), can_see_cost(user)
    out = []
    for r in rows:
        exp = date.fromisoformat(r["expiry_date"])
        status = r["status"].capitalize() if r["status"] != "active" else ("Expired" if exp < today else "OK")
        d = {"product": f"{r['product_name']} {r['strength'] or ''}".strip(), "batch": r["batch_number"], "expiry": r["expiry_date"],
             "days_left": (exp - today).days, "quantity": show_quantity(r["quantity_base"], um.get(r["product_id"], [])),
             "quantity_base": r["quantity_base"], "status": status}
        if cost:
            d["value"] = money(r["value"])
        out.append(d)
    cols = [col("product", "Medicine"), col("batch", "Batch"), col("expiry", "Expiry", "date")]
    if with_days:
        cols.append(col("days_left", "Days left", "int"))
    cols += [col("quantity", "Quantity"), col("quantity_base", "Base units", "int"), col("status", "Status")]
    tot = {}
    if cost:
        cols.append(col("value", "Stock value", "money")); tot["value"] = money(sum(r["value"] for r in out))
    return {"title": title, "columns": cols, "rows": out, "totals": tot, "note": note}


def r_current_stock(c, b, user, d1, d2):
    rows = _batch_rows(c, b, "ba.quantity_base<>0", (), "p.name, ba.expiry_date")
    rep = _batch_report(c, b, user, rows, "Current stock", "Stock value = quantity x purchase cost of one base unit.")
    return rep


def r_low_stock(c, b, user, d1, d2):
    um, rows = units_by_product(c, b), []
    for r in low_stock_rows(c, b, date.today().isoformat()):
        if r["available"] <= r["minimum_stock"]:
            u = um.get(r["id"], [])
            rows.append({"product": f"{r['name']} {r['strength'] or ''}".strip(), "available": show_quantity(r["available"], u),
                         "minimum": show_quantity(r["minimum_stock"], u), "available_base": r["available"], "minimum_base": r["minimum_stock"]})
    return {"title": "Low stock", "columns": [col("product", "Medicine"), col("available", "Can sell now"), col("minimum", "Minimum stock"),
            col("available_base", "Base units", "int"), col("minimum_base", "Minimum (base)", "int")], "rows": rows, "totals": {},
            "note": "Only stock that is active and not expired is counted."}


def r_near_expiry(c, b, user, d1, d2):
    today = date.today(); w, a = near_expiry_where(near_days(c, b), today)
    return _batch_report(c, b, user, _batch_rows(c, b, w, a, "ba.expiry_date, p.name"), "Near expiry",
                         f"Active batches that expire within {near_days(c, b)} days (set in Settings).", True)


def r_expired(c, b, user, d1, d2):
    return _batch_report(c, b, user, _batch_rows(c, b, "ba.quantity_base>0 AND ba.expiry_date<?", (date.today().isoformat(),), "ba.expiry_date, p.name"),
                         "Expired stock", "Expired stock cannot be sold.", True)


def r_best_selling(c, b, user, d1, d2):
    s, e = local_day_bounds(d1, d2)
    um = units_by_product(c, b)
    rows = []
    for r in c.execute(
            """SELECT i.product_id, p.name, p.strength, SUM(i.base_quantity-i.returned_base) qty,
                      SUM(i.net_total - i.net_total*i.returned_base*1.0/i.base_quantity) revenue, COUNT(DISTINCT i.sale_id) invoices
               FROM sale_items i JOIN sales sa ON sa.id=i.sale_id AND sa.business_id=i.business_id
               JOIN products p ON p.id=i.product_id AND p.business_id=i.business_id
               WHERE i.business_id=? AND sa.created_at>=? AND sa.created_at<? GROUP BY i.product_id
               ORDER BY qty DESC, revenue DESC LIMIT 100""", (b, s, e)):
        rows.append({"rank": len(rows) + 1, "product": f"{r['name']} {r['strength'] or ''}".strip(), "quantity": show_quantity(r["qty"], um.get(r["product_id"], [])),
                     "quantity_base": r["qty"], "invoices": r["invoices"], "revenue": money(r["revenue"])})
    return {"title": "Best-selling products", "columns": [col("rank", "#", "int"), col("product", "Medicine"), col("quantity", "Sold (after returns)"),
            col("quantity_base", "Base units", "int"), col("invoices", "Invoices", "int"), col("revenue", "Sales amount", "money")],
            "rows": rows, "totals": {"revenue": money(sum(r["revenue"] for r in rows))}, "note": "Top 100 by quantity sold. Returned quantities are removed."}


def r_customer_balances(c, b, user, d1, d2):
    rows = [dict(r) for r in c.execute(
        """SELECT cu.name, cu.customer_type, cu.phone, cu.credit_limit, ROUND(SUM(s.due_amount),2) outstanding,
                  MIN(CASE WHEN s.due_amount>0.004 THEN substr(s.created_at,1,10) END) oldest_unpaid
           FROM customers cu JOIN sales s ON s.customer_id=cu.id AND s.business_id=cu.business_id
           WHERE cu.business_id=? GROUP BY cu.id HAVING ABS(SUM(s.due_amount))>0.004 ORDER BY outstanding DESC, cu.name""", (b,))]
    for r in rows:
        r["outstanding"] = money(r["outstanding"])
    return {"title": "Customer balances", "columns": [col("name", "Customer"), col("customer_type", "Type"), col("phone", "Phone"),
            col("credit_limit", "Credit limit", "money"), col("outstanding", "Owes", "money"), col("oldest_unpaid", "Oldest unpaid invoice", "date")],
            "rows": rows, "totals": {"outstanding": money(sum(r["outstanding"] for r in rows))}, "note": "Shows the balance today (not for the date range)."}


def r_supplier_balances(c, b, user, d1, d2):
    rows = [dict(r) for r in c.execute(
        """SELECT s.name, s.phone, ROUND(SUM(p.due_amount),2) outstanding FROM suppliers s JOIN purchases p
           ON p.supplier_id=s.id AND p.business_id=s.business_id WHERE s.business_id=? GROUP BY s.id
           HAVING ABS(SUM(p.due_amount))>0.004 ORDER BY outstanding DESC, s.name""", (b,))]
    for r in rows:
        r["outstanding"] = money(r["outstanding"])
    return {"title": "Supplier balances", "columns": [col("name", "Supplier"), col("phone", "Phone"), col("outstanding", "We owe", "money")],
            "rows": rows, "totals": {"outstanding": money(sum(r["outstanding"] for r in rows))}, "note": "Shows the balance today (not for the date range)."}


def r_profit(c, b, user, d1, d2):
    s, e = local_day_bounds(d1, d2)
    revenue = c.execute("SELECT COALESCE(SUM(total),0) v FROM sales WHERE business_id=? AND created_at>=? AND created_at<?", (b, s, e)).fetchone()["v"]
    cogs = c.execute(
        """SELECT COALESCE(SUM(sb.base_quantity*sb.cost_per_base),0) v FROM sale_item_batches sb JOIN sale_items i ON i.id=sb.sale_item_id
           AND i.business_id=sb.business_id JOIN sales sa ON sa.id=i.sale_id AND sa.business_id=i.business_id
           WHERE sb.business_id=? AND sa.created_at>=? AND sa.created_at<?""", (b, s, e)).fetchone()["v"]
    returns = c.execute("SELECT COALESCE(SUM(total),0) v FROM sale_returns WHERE business_id=? AND created_at>=? AND created_at<?", (b, s, e)).fetchone()["v"]
    back = c.execute(
        """SELECT COALESCE(SUM(ri.base_quantity*sb.cost_per_base),0) v FROM sale_return_items ri JOIN sale_returns r ON r.id=ri.return_id
           AND r.business_id=ri.business_id JOIN sale_item_batches sb ON sb.sale_item_id=ri.sale_item_id AND sb.batch_id=ri.batch_id
           AND sb.business_id=ri.business_id WHERE ri.business_id=? AND r.action='restock' AND r.created_at>=? AND r.created_at<?""", (b, s, e)).fetchone()["v"]
    revenue, cogs, returns, back = money(revenue), money(cogs), money(returns), money(back)
    net_cogs = money(cogs - back)
    profit = money(revenue - returns - net_cogs)
    lines = [("Sales revenue (after discounts)", revenue), ("Less: returns given back to customers", -returns),
             ("Cost of medicines sold (batch cost)", -cogs), ("Add back: cost of returned medicines put back in stock", back),
             ("Estimated gross profit", profit)]
    return {"title": "Estimated gross profit", "columns": [col("item", "Item"), col("amount", "Amount", "money")],
            "rows": [{"item": k, "amount": v} for k, v in lines],
            "totals": {"revenue": revenue, "returns": returns, "cost_of_goods_sold": net_cogs, "estimated_gross_profit": profit},
            "note": PROFIT_NOTE}


# name -> (function, extra permission check or None, title)
REPORTS: dict[str, tuple[Callable, Callable | None, str]] = {
    "daily_sales": (r_daily_sales, None, "Daily sales"),
    "monthly_sales": (r_monthly_sales, None, "Monthly sales"),
    "purchase_history": (r_purchase_history, can_see_cost, "Purchase history"),
    "current_stock": (r_current_stock, None, "Current stock"),
    "low_stock": (r_low_stock, None, "Low stock"),
    "near_expiry": (r_near_expiry, None, "Near expiry"),
    "expired_stock": (r_expired, None, "Expired stock"),
    "best_selling": (r_best_selling, None, "Best-selling products"),
    "customer_balances": (r_customer_balances, can_see_balances, "Customer balances"),
    "supplier_balances": (r_supplier_balances, can_see_balances, "Supplier balances"),
    "profit": (r_profit, can_see_profit, "Estimated gross profit"),
}


def run_report(name: str, user: dict, c, from_date, to_date) -> dict:
    if name not in REPORTS:
        raise HTTPException(404, "Report not found.")
    fn, check, _ = REPORTS[name]
    if check and not check(user):
        raise HTTPException(403, "You do not have permission to open this report.")
    ensure_p5_schema(c)
    d1, d2 = parse_range(from_date, to_date)
    rep = fn(c, user["business_id"], user, d1, d2)
    biz = c.execute("SELECT name FROM businesses WHERE id=?", (user["business_id"],)).fetchone()
    rep.update(name=name, from_date=d1.isoformat(), to_date=d2.isoformat(), business_name=biz["name"] if biz else "")
    return rep


@router.get("/reports")
def report_list(user=Depends(require_permission("view_reports"))):
    return {"items": [{"name": n, "title": t} for n, (_, chk, t) in REPORTS.items() if not chk or chk(user)]}


@router.get("/reports/{name}")
def report_view(name: str, from_date: str | None = Query(None, alias="from"), to_date: str | None = Query(None, alias="to"),
                user=Depends(require_permission("view_reports")), c=Depends(get_db)):
    return run_report(name, user, c, from_date, to_date)


# ------------------------------------------------------------ export
def _safe_cell(v):
    """Stops spreadsheet formula injection (a text cell starting with = + - @)."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@"):
        return "'" + v
    return v


def _table(rep: dict) -> tuple[list[str], list[list]]:
    cols = rep["columns"]
    head = [x["label"] for x in cols]
    body = [[r.get(x["key"], "") for x in cols] for r in rep["rows"]]
    t = rep.get("totals") or {}
    if t and rep["rows"]:
        body.append(["TOTAL" if i == 0 else t.get(x["key"], "") for i, x in enumerate(cols)])
    return head, body


def to_csv(rep: dict) -> bytes:
    head, body = _table(rep)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([rep["title"]]); w.writerow([f"From {rep['from_date']} to {rep['to_date']}"]); w.writerow([])
    w.writerow(head)
    for r in body:
        w.writerow([_safe_cell(v) for v in r])
    if rep.get("note"):
        w.writerow([]); w.writerow([rep["note"]])
    return buf.getvalue().encode("utf-8-sig")  # BOM so Excel shows letters correctly


def to_xlsx(rep: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    head, body = _table(rep)
    wb = Workbook(); ws = wb.active; ws.title = rep["title"][:31]
    ws.append([rep["title"]]); ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"From {rep['from_date']} to {rep['to_date']}"]); ws.append([])
    ws.append(head)
    for cell in ws[4]:
        cell.font = Font(bold=True)
    types = [x["type"] for x in rep["columns"]]
    for r in body:
        ws.append([_safe_cell(v) for v in r])
        for i, cell in enumerate(ws[ws.max_row]):
            if types[i] == "money" and isinstance(cell.value, (int, float)):
                cell.number_format = "#,##0.00"
    if rep["rows"] and rep.get("totals"):
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)
    if rep.get("note"):
        ws.append([]); ws.append([rep["note"]])
    for i, h in enumerate(head, start=1):
        width = max([len(str(h))] + [len(str(r[i - 1])) for r in body if i - 1 < len(r)]) + 2
        ws.column_dimensions[ws.cell(row=4, column=i).column_letter].width = min(width, 45)
    out = io.BytesIO(); wb.save(out)
    return out.getvalue()


MIME = {"csv": "text/csv; charset=utf-8", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


def _export(name, fmt, from_date, to_date, user, c):
    rep = run_report(name, user, c, from_date, to_date)
    data = to_csv(rep) if fmt == "csv" else to_xlsx(rep)
    audit_log(c, user["business_id"], user["id"], user["username"], "report_exported", f"{name} {fmt}")
    c.commit()
    return data, f"{name}_{rep['from_date']}_{rep['to_date']}.{fmt}"


@router.get("/reports/{name}/download")
def report_download(name: str, format: Literal["csv", "xlsx"] = "xlsx", from_date: str | None = Query(None, alias="from"),
                    to_date: str | None = Query(None, alias="to"), user=Depends(require_permission("view_reports")), c=Depends(get_db)):
    data, fname = _export(name, format, from_date, to_date, user, c)
    return Response(data, media_type=MIME[format], headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/reports/{name}/export")
def report_export(name: str, format: Literal["csv", "xlsx"] = "xlsx", from_date: str | None = Query(None, alias="from"),
                  to_date: str | None = Query(None, alias="to"), user=Depends(require_permission("view_reports")), c=Depends(get_db)):
    """Same file as /download but inside JSON, so the web page can save it using its normal login."""
    data, fname = _export(name, format, from_date, to_date, user, c)
    return {"filename": fname, "mime": MIME[format].split(";")[0], "data_base64": base64.b64encode(data).decode()}
