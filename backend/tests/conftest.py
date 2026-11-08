"""Builds a throw-away copy of the app: simple stand-ins for Phase 1/2 (login, products table) + the REAL Phase 3, 4 and 5 routes."""
import importlib, json, os, shutil, sys, tempfile, uuid as uuidlib
from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient

HERE = os.path.dirname(__file__)
APP = os.path.join(HERE, "..", "app")


@pytest.fixture()
def env(tmp_path):
    pkg = tmp_path / "pkgroot" / "psapp"
    pkg.mkdir(parents=True)
    for f in os.listdir(os.path.join(HERE, "stubs")):
        if f.endswith(".py"):
            shutil.copy(os.path.join(HERE, "stubs", f), pkg / f)
    for f in ("routes_phase3.py", "routes_phase4.py", "routes_phase5.py", "routes_phase6.py", "security.py"):
        shutil.copy(os.path.join(APP, f), pkg / f)
    (pkg / "__init__.py").write_text("")
    os.environ["TEST_DB"] = str(tmp_path / "t.db")
    sys.path.insert(0, str(tmp_path / "pkgroot"))
    for m in [m for m in sys.modules if m == "psapp" or m.startswith("psapp.")]:
        del sys.modules[m]
    from fastapi import FastAPI
    db = importlib.import_module("psapp.db")
    app = FastAPI()
    for name in ("routes_phase3", "routes_phase4", "routes_phase5", "routes_phase6"):
        app.include_router(importlib.import_module(f"psapp.{name}").router)
    db.init_db()
    c = db.connect()
    c.execute("INSERT INTO businesses(id,name) VALUES(1,'Shop One'),(2,'Shop Two')")
    users = [
        (1, 1, "owner", "Owner", "owner", []),
        (2, 1, "sales", "Sales Person", "salesperson", ["manage_sales", "manage_customers", "view_reports"]),
        (3, 1, "stockop", "Stock Op", "operator", ["manage_purchases", "view_stock", "view_reports"]),
        (4, 2, "owner2", "Owner Two", "owner", []),
    ]
    for u in users:
        c.execute("INSERT INTO users(id,business_id,username,full_name,role,permissions) VALUES(?,?,?,?,?,?)", (*u[:5], json.dumps(u[5])))
    c.commit()
    from psapp.routes_phase4 import ensure_sales_schema
    ensure_sales_schema(c)
    c.close()
    yield TestClient(app), db
    sys.path.remove(str(tmp_path / "pkgroot"))


def H(uid):
    return {"X-User": str(uid)}


def new_id():
    return uuidlib.uuid4().hex


def seed(db, business=1, name="Panadol DEMO", qty_boxes=10, expiry_days=400, batch="B1", retail=500, wholesale=400, mrp=600, cost_box=300, minimum=0):
    """One product (Box=100, Strip=10, Tablet=1) with one batch. Returns (product_id, batch_id)."""
    c = db.connect()
    pid = c.execute("INSERT INTO products(business_id,name,retail_price,wholesale_price,mrp,purchase_price,minimum_stock) VALUES(?,?,?,?,?,?,?)",
                    (business, name, retail, wholesale, mrp, cost_box, minimum)).lastrowid
    for n, f in (("Tablet", 1), ("Strip", 10), ("Box", 100)):
        c.execute("INSERT INTO product_units(business_id,product_id,name,factor) VALUES(?,?,?,?)", (business, pid, n, f))
    sup = c.execute("SELECT id FROM suppliers WHERE business_id=? LIMIT 1", (business,)).fetchone()
    sid = sup["id"] if sup else c.execute("INSERT INTO suppliers(business_id,name,created_at,updated_at) VALUES(?,?,'x','x')", (business, f"Supplier {business} DEMO")).lastrowid
    exp = (date.today() + timedelta(days=expiry_days)).isoformat()
    bid = c.execute("INSERT INTO batches(business_id,product_id,batch_number,expiry_date,quantity_base,unit_cost,created_at,updated_at) VALUES(?,?,?,?,?,?,'x','x')",
                    (business, pid, batch, exp, qty_boxes * 100, cost_box)).lastrowid
    total = qty_boxes * cost_box
    puid = c.execute("INSERT INTO purchases(business_id,supplier_id,invoice_number,purchase_date,subtotal,discount,tax,total,paid_amount,due_amount,created_at) "
                     "VALUES(?,?,?,?,?,0,0,?,?,?,'x')", (business, sid, f"PI-{pid}", date.today().isoformat(), total, total, total // 2, total - total // 2)).lastrowid
    c.execute("INSERT INTO purchase_items(business_id,purchase_id,product_id,batch_id,unit_name,quantity,unit_factor,base_quantity,unit_cost,discount,tax,line_total) "
              "VALUES(?,?,?,?,'Box',?,100,?,?,0,0,?)", (business, puid, pid, bid, qty_boxes, qty_boxes * 100, cost_box, total))
    c.commit(); c.close()
    return pid, bid


def make_customer(client, name="Ali DEMO", limit=100000, credit=True):
    r = client.post("/api/customers", json={"name": name, "customer_type": "wholesale", "credit_allowed": credit, "credit_limit": limit}, headers=H(1))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def sell(client, pid, cust, qty, unit="Box", paid=0, kind="wholesale", user=1, method="Cash"):
    body = {"client_uuid": new_id(), "sale_type": kind, "customer_id": cust, "lines": [{"product_id": pid, "unit_name": unit, "quantity": qty}],
            "paid_amount": paid, "payment_method": method}
    r = client.post("/api/sales", json=body, headers=H(user))
    assert r.status_code == 201, r.text
    return r.json()
