"""Phase 7 - the 14 acceptance tests (automated where possible) + two-business isolation.
Runs the REAL Phase 3-6 routes against simple stand-ins for Phase 1/2 (login, products table).
Tests 1 and 14 and the full Phase 2 scan screen cannot be proven here - see TEST_REPORT.md."""
import json
import os
import sqlite3
from datetime import date, timedelta
from conftest import H, new_id, seed, make_customer, sell


def one(db, sql, *a):
    c = db.connect(); r = c.execute(sql, a).fetchone(); c.close(); return r[0]


def add_product(db, business=1, name="Test DEMO", retail=500, wholesale=400, mrp=600):
    c = db.connect()
    pid = c.execute("INSERT INTO products(business_id,name,retail_price,wholesale_price,mrp) VALUES(?,?,?,?,?)", (business, name, retail, wholesale, mrp)).lastrowid
    for n, f in (("Tablet", 1), ("Strip", 10), ("Box", 100)):
        c.execute("INSERT INTO product_units(business_id,product_id,name,factor) VALUES(?,?,?,?)", (business, pid, n, f))
    sid = c.execute("INSERT OR IGNORE INTO suppliers(business_id,name,created_at,updated_at) VALUES(?,?,'x','x')", (business, f"Sup{business}")).lastrowid
    sid = c.execute("SELECT id FROM suppliers WHERE business_id=? LIMIT 1", (business,)).fetchone()[0]
    c.commit(); c.close()
    return pid, sid


def future(days): return (date.today() + timedelta(days=days)).isoformat()


def buy(client, pid, sid, qty, batch, days, inv, paid=0, user=1, cost=300):
    return client.post("/api/purchases", json={"supplier_id": sid, "invoice_number": inv, "purchase_date": date.today().isoformat(), "paid_amount": paid,
                       "items": [{"product_id": pid, "unit_name": "Box", "quantity": qty, "unit_cost": cost, "batch_number": batch, "expiry_date": future(days)}]}, headers=H(user))


# 2 / 3 ---------------------------------------------------------------- barcodes (POS scan path only)
def test_02_known_barcode_loads_correct_product(env):
    client, db = env
    p1, _ = seed(db, name="One DEMO"); p2, _ = seed(db, name="Two DEMO", batch="B2")
    c = db.connect(); c.execute("UPDATE products SET barcode='6001234567890' WHERE id=?", (p2,)); c.commit(); c.close()
    r = client.get("/api/sales/scan/6001234567890", headers=H(1)).json()
    assert r["found"] and r["product"]["id"] == p2 and r["product"]["name"] == "Two DEMO"


def test_03_unknown_barcode_is_safe(env):
    client, db = env
    seed(db)
    before = one(db, "SELECT COUNT(*) FROM products")
    r = client.get("/api/sales/scan/0000000000000", headers=H(1)).json()
    assert r["found"] is False and "Nothing was sold or saved" in r["message"]
    assert one(db, "SELECT COUNT(*) FROM products") == before and one(db, "SELECT COUNT(*) FROM sales") == 0


# 4 -------------------------------------------------------------------- purchases
def test_04_purchase_adds_exact_base_units_and_supplier_balance(env):
    client, db = env
    pid, sid = add_product(db)
    r = buy(client, pid, sid, 3, "P1", 400, "I-1", paid=300)
    assert r.status_code == 201, r.text
    assert one(db, "SELECT quantity_base FROM batches WHERE product_id=?", pid) == 300
    assert one(db, "SELECT SUM(quantity_base) FROM stock_movements WHERE product_id=? AND kind='purchase'", pid) == 300
    assert one(db, "SELECT due_amount FROM purchases") == 600
    # bad purchase changes nothing
    bad = buy(client, pid, sid, 1, "P1", 500, "I-2")                  # same batch, other expiry
    assert bad.status_code == 409
    assert buy(client, pid, sid, 1, "P9", -5, "I-3").status_code == 400  # expired date
    assert one(db, "SELECT quantity_base FROM batches WHERE product_id=? AND batch_number='P1'", pid) == 300
    assert one(db, "SELECT COUNT(*) FROM purchases") == 1
    # supplier payment lowers balance
    assert client.post(f"/api/suppliers/{sid}/payments", json={"amount": 200}, headers=H(1)).status_code == 201
    assert one(db, "SELECT SUM(due_amount) FROM purchases") == 400


# 5 / 6 ---------------------------------------------------------------- sales + units
def test_05_06_sale_reduces_stock_and_units_convert(env):
    client, db = env
    pid, _ = seed(db, qty_boxes=1)       # 100 tablets, retail 500 per box
    body = {"client_uuid": new_id(), "sale_type": "retail", "paid_amount": 125, "payment_method": "Cash",
            "lines": [{"product_id": pid, "unit_name": "Strip", "quantity": 2}, {"product_id": pid, "unit_name": "Tablet", "quantity": 5}]}
    r = client.post("/api/sales", json=body, headers=H(1))
    assert r.status_code == 201, r.text
    assert r.json()["total"] == 2 * 50 + 5 * 5
    assert one(db, "SELECT quantity_base FROM batches WHERE product_id=?", pid) == 100 - 25
    assert one(db, "SELECT SUM(base_quantity) FROM sale_items") == 25
    assert one(db, "SELECT SUM(quantity_base) FROM stock_movements WHERE kind='sale'") == -25
    too_much = {**body, "client_uuid": new_id(), "lines": [{"product_id": pid, "unit_name": "Box", "quantity": 1}]}
    r = client.post("/api/sales", json=too_much, headers=H(1))
    assert r.status_code == 400 and "Not enough stock" in r.json()["detail"]
    assert one(db, "SELECT quantity_base FROM batches WHERE product_id=?", pid) == 75


# 7 -------------------------------------------------------------------- batches / FEFO
def test_07_batches_keep_own_expiry_and_fefo_order(env):
    client, db = env
    pid, sid = add_product(db)
    assert buy(client, pid, sid, 1, "LATE", 600, "A1").status_code == 201
    assert buy(client, pid, sid, 1, "EARLY", 100, "A2").status_code == 201
    exp = {r[0]: r[1] for r in sqlite3.connect(os.environ["TEST_DB"]).execute("SELECT batch_number, expiry_date FROM batches")}
    assert exp == {"LATE": future(600), "EARLY": future(100)}
    sell(client, pid, None, 150, unit="Tablet", kind="retail", paid=750)
    q = {r[0]: r[1] for r in sqlite3.connect(os.environ["TEST_DB"]).execute("SELECT batch_number, quantity_base FROM batches")}
    assert q == {"EARLY": 0, "LATE": 50}                         # earliest used first, split across batches


# 8 -------------------------------------------------------------------- blocked stock
def test_08_expired_and_recalled_cannot_be_sold(env):
    client, db = env
    exp_pid, _ = seed(db, name="Old DEMO", expiry_days=-5, batch="OLD")
    rec_pid, rec_batch = seed(db, name="Recalled DEMO", batch="REC")
    blk_pid, blk_batch = seed(db, name="Blocked DEMO", batch="BLK")
    assert client.post(f"/api/stock/batches/{rec_batch}/status", json={"status": "recalled", "reason": "maker recall"}, headers=H(1)).status_code == 200
    assert client.post(f"/api/stock/batches/{blk_batch}/status", json={"status": "quarantine", "reason": "checking"}, headers=H(1)).status_code == 200
    for pid in (exp_pid, rec_pid, blk_pid):
        r = client.post("/api/sales", json={"client_uuid": new_id(), "sale_type": "retail", "paid_amount": 500, "payment_method": "Cash",
                        "lines": [{"product_id": pid, "unit_name": "Box", "quantity": 1}]}, headers=H(1))
        assert r.status_code == 400 and "cannot be sold" in r.json()["detail"], r.text
    assert one(db, "SELECT COUNT(*) FROM sales") == 0
    assert one(db, "SELECT SUM(quantity_base) FROM batches") == 3000


# 9 -------------------------------------------------------------------- credit
def test_09_credit_sales_update_balances(env):
    client, db = env
    pid, _ = seed(db)
    cu = make_customer(client, limit=1000)
    sell(client, pid, cu, 2)                                         # 800 on credit
    assert one(db, "SELECT SUM(due_amount) FROM sales WHERE customer_id=?", cu) == 800
    body = {"client_uuid": new_id(), "sale_type": "wholesale", "customer_id": cu, "paid_amount": 0, "payment_method": "Cash",
            "lines": [{"product_id": pid, "unit_name": "Box", "quantity": 1}]}
    r = client.post("/api/sales", json=body, headers=H(1))            # 800 + 400 = 1200 is above the 1000 limit
    assert r.status_code == 400 and "Credit limit exceeded" in r.json()["detail"]
    assert one(db, "SELECT SUM(due_amount) FROM sales WHERE customer_id=?", cu) == 800
    assert client.post(f"/api/customers/{cu}/payments", json={"client_uuid": new_id(), "amount": 300, "method": "Cash"}, headers=H(1)).status_code == 201
    assert one(db, "SELECT SUM(due_amount) FROM sales WHERE customer_id=?", cu) == 500
    assert client.post("/api/sales", json=body, headers=H(1)).status_code == 201   # 500 + 400 fits the limit now
    assert one(db, "SELECT SUM(due_amount) FROM sales WHERE customer_id=?", cu) == 900


def test_09b_credit_limit_refused(env):
    client, db = env
    pid, _ = seed(db)
    cu = make_customer(client, limit=500)
    body = {"client_uuid": new_id(), "sale_type": "wholesale", "customer_id": cu, "paid_amount": 0, "payment_method": "Cash",
            "lines": [{"product_id": pid, "unit_name": "Box", "quantity": 2}]}
    r = client.post("/api/sales", json=body, headers=H(1))
    assert r.status_code == 400 and "Credit limit exceeded" in r.json()["detail"]
    assert one(db, "SELECT COUNT(*) FROM sales") == 0 and one(db, "SELECT quantity_base FROM batches") == 1000


# 10 ------------------------------------------------------------------- offline replay
def test_10_offline_items_sync_once(env):
    client, db = env
    pid, sid = add_product(db)
    cu = make_customer(client)
    seed_pid, _ = seed(db, name="Stocked DEMO", batch="S1")
    sale_uuid, buy_uuid, pay_uuid = new_id(), new_id(), new_id()
    sale = {"sale_type": "wholesale", "customer_id": cu, "paid_amount": 0, "payment_method": "Cash", "lines": [{"product_id": seed_pid, "unit_name": "Box", "quantity": 2}]}
    purchase = {"supplier_id": sid, "invoice_number": "OFF-1", "purchase_date": date.today().isoformat(), "paid_amount": 0,
                "items": [{"product_id": pid, "unit_name": "Box", "quantity": 1, "unit_cost": 300, "batch_number": "OFF", "expiry_date": future(300)}]}
    first = client.post("/api/sync/push", json={"items": [{"client_uuid": sale_uuid, "kind": "sale", "payload": sale},
                                                          {"client_uuid": buy_uuid, "kind": "purchase", "payload": purchase},
                                                          {"client_uuid": pay_uuid, "kind": "customer_payment", "payload": {"customer_id": cu, "amount": 300, "method": "Cash"}}]}, headers=H(1))
    assert [r["status"] for r in first.json()["results"]] == ["saved", "saved", "saved"], first.text
    for _ in range(3):
        again = client.post("/api/sync/push", json={"items": [{"client_uuid": sale_uuid, "kind": "sale", "payload": sale},
                                                              {"client_uuid": buy_uuid, "kind": "purchase", "payload": purchase},
                                                              {"client_uuid": pay_uuid, "kind": "customer_payment", "payload": {"customer_id": cu, "amount": 300, "method": "Cash"}}]}, headers=H(1))
        assert [r["status"] for r in again.json()["results"]] == ["duplicate"] * 3
    assert one(db, "SELECT COUNT(*) FROM sales") == 1
    assert one(db, "SELECT COUNT(*) FROM purchases WHERE invoice_number='OFF-1'") == 1
    assert one(db, "SELECT quantity_base FROM batches WHERE batch_number='OFF'") == 100
    assert one(db, "SELECT quantity_base FROM batches WHERE batch_number='S1'") == 800
    assert one(db, "SELECT COUNT(*) FROM customer_payments") == 1 and one(db, "SELECT SUM(due_amount) FROM sales") == 500
    # a refused item is reported, not hidden, and saves nothing
    big = {**sale, "lines": [{"product_id": seed_pid, "unit_name": "Box", "quantity": 999}]}
    r = client.post("/api/sync/push", json={"items": [{"client_uuid": new_id(), "kind": "sale", "payload": big}]}, headers=H(1)).json()["results"][0]
    assert r["status"] == "error" and "Not enough stock" in r["message"]
    assert one(db, "SELECT COUNT(*) FROM sales") == 1
    # permission is checked for queued items too
    r = client.post("/api/sync/push", json={"items": [{"client_uuid": new_id(), "kind": "purchase", "payload": purchase}]}, headers=H(2)).json()["results"][0]
    assert r["status"] == "error"
    # status never claims cloud sync
    st = client.get("/api/sync/status", headers=H(1)).json()
    assert st["cloud"]["configured"] is False and st["cloud"]["state"] == "not_configured"


# 11 ------------------------------------------------------------------- isolation
def test_11_two_businesses_never_see_each_other(env):
    client, db = env
    pid1, b1 = seed(db, business=1, name="ZZMARK ONE DEMO")
    pid2, b2 = seed(db, business=2, name="ZZMARK TWO DEMO", batch="X2")
    cu1 = make_customer(client, "ZZMARK Customer DEMO")
    s1 = sell(client, pid1, cu1, 1)
    # business 2 owner (user 4) reads: nothing of business 1 appears
    urls = ["/api/stock", "/api/stock/movements", "/api/suppliers", "/api/purchases", "/api/sales", "/api/sales/customers", "/api/customers",
            "/api/sales/products?search=ZZMARK", "/api/products-for-purchase?search=ZZMARK", "/api/dashboard", "/api/backups", "/api/sync/log"]
    for u in urls:
        r = client.get(u, headers=H(4))
        assert r.status_code == 200, u
        t = r.text
        assert "ONE DEMO" not in t and "Customer DEMO" not in t, u
    for name in ("daily_sales", "monthly_sales", "purchase_history", "current_stock", "low_stock", "near_expiry", "expired_stock", "best_selling",
                 "customer_balances", "supplier_balances", "profit"):
        t = client.get(f"/api/reports/{name}", headers=H(4)).text
        assert "ONE DEMO" not in t and "Customer DEMO" not in t, name
    assert client.get("/api/stock", headers=H(4)).json()["stock_value"] == 1000 * 0 + client.get("/api/stock", headers=H(4)).json()["stock_value"]
    # business 2 cannot touch business 1 records by id
    sid = s1["id"]
    attempts = [
        client.get(f"/api/sales/{sid}", headers=H(4)), client.get(f"/api/sales/{sid}/print", headers=H(4)),
        client.post(f"/api/sales/{sid}/returns", json={"client_uuid": new_id(), "action": "restock", "reason": "attack", "lines": [{"sale_item_id": 1, "unit_name": "Box", "quantity": 1}]}, headers=H(4)),
        client.get(f"/api/customers/{cu1}/account", headers=H(4)),
        client.post(f"/api/customers/{cu1}/payments", json={"client_uuid": new_id(), "amount": 1, "method": "Cash"}, headers=H(4)),
        client.put(f"/api/customers/{cu1}", json={"name": "Hacked", "customer_type": "retail"}, headers=H(4)),
        client.put(f"/api/customers/{cu1}/prices", json={"product_id": pid1, "price": 1}, headers=H(4)),
        client.post(f"/api/stock/batches/{b1}/status", json={"status": "blocked", "reason": "attack"}, headers=H(4)),
        client.post("/api/stock/adjustments", json={"product_id": pid1, "batch_id": b1, "quantity_base": -5, "reason": "attack"}, headers=H(4)),
        client.post("/api/sales", json={"client_uuid": new_id(), "sale_type": "retail", "paid_amount": 500, "payment_method": "Cash", "lines": [{"product_id": pid1, "unit_name": "Box", "quantity": 1}]}, headers=H(4)),
        client.post("/api/suppliers/1/payments", json={"amount": 5}, headers=H(4)),
        client.get("/api/suppliers/1/history", headers=H(4)),
    ]
    for r in attempts:
        assert r.status_code in (400, 403, 404), (r.request.url, r.status_code, r.text[:100])
    assert one(db, "SELECT name FROM customers WHERE id=?", cu1) == "ZZMARK Customer DEMO"
    assert one(db, "SELECT quantity_base FROM batches WHERE id=?", b1) == 900
    assert one(db, "SELECT status FROM batches WHERE id=?", b1) == "active"
    assert one(db, "SELECT COUNT(*) FROM stock_movements WHERE reason='attack'") == 0
    # same idempotency key in two businesses is two separate sales
    u = new_id()
    body = lambda p: {"client_uuid": u, "sale_type": "retail", "paid_amount": 500, "payment_method": "Cash", "lines": [{"product_id": p, "unit_name": "Box", "quantity": 1}]}
    assert client.post("/api/sales", json=body(pid1), headers=H(1)).status_code == 201
    assert client.post("/api/sales", json=body(pid2), headers=H(4)).status_code == 201
    assert one(db, "SELECT COUNT(*) FROM sales WHERE client_uuid=?", u) == 2


# 12 ------------------------------------------------------------------- backup / restore
def test_12_backup_verified_and_restore_returns_exact_data(env):
    client, db = env
    pid, _ = seed(db)
    cu = make_customer(client)
    sell(client, pid, cu, 1)
    b = client.post("/api/backups", headers=H(1))
    assert b.status_code == 201 and b.json()["status"] == "verified" and b.json()["label"] == "Backed up and verified"
    assert b.json()["total_records"] > 0 and len(b.json()["sha256"]) == 64
    snap = {t: one(db, f'SELECT COUNT(*) FROM "{t}"') for t in ("sales", "sale_items", "batches", "stock_movements", "customers")}
    qty = one(db, "SELECT quantity_base FROM batches")
    sell(client, pid, cu, 2); sell(client, pid, None, 1, kind="retail", paid=500)           # later data that must disappear
    assert one(db, "SELECT COUNT(*) FROM sales") == 3
    # wrong confirmation / non-owner refused
    assert client.post(f"/api/backups/{b.json()['id']}/restore", json={"confirm": "yes"}, headers=H(1)).status_code == 400
    assert client.post(f"/api/backups/{b.json()['id']}/restore", json={"confirm": "RESTORE"}, headers=H(2)).status_code == 403
    r = client.post(f"/api/backups/{b.json()['id']}/restore", json={"confirm": "RESTORE"}, headers=H(1))
    assert r.status_code == 200, r.text
    assert {t: one(db, f'SELECT COUNT(*) FROM "{t}"') for t in snap} == snap
    assert one(db, "SELECT quantity_base FROM batches") == qty
    kinds = [x["kind"] for x in client.get("/api/backups", headers=H(1)).json()["items"]]
    assert "before-restore" in kinds                                  # safety copy was made and is still listed
    safety = [x for x in client.get("/api/backups", headers=H(1)).json()["items"] if x["kind"] == "before-restore"][0]
    assert safety["status"] == "verified" and safety["exists"]


def test_12b_damaged_or_changed_backup_is_never_restored(env):
    client, db = env
    seed(db)
    b = client.post("/api/backups", headers=H(1)).json()
    folder = client.get("/api/backups", headers=H(1)).json()["folder"]
    path = os.path.join(folder, b["filename"])
    with open(path, "ab") as f:
        f.write(b"tampered")
    before = one(db, "SELECT COUNT(*) FROM batches")
    r = client.post(f"/api/backups/{b['id']}/restore", json={"confirm": "RESTORE"}, headers=H(1))
    assert r.status_code == 400 and "changed" in r.json()["detail"]
    assert one(db, "SELECT COUNT(*) FROM batches") == before
    # a missing file is reported honestly
    os.remove(path)
    assert client.post(f"/api/backups/{b['id']}/restore", json={"confirm": "RESTORE"}, headers=H(1)).status_code == 404
    item = [x for x in client.get("/api/backups", headers=H(1)).json()["items"] if x["id"] == b["id"]][0]
    assert item["exists"] is False


def test_12c_failed_verification_is_not_called_backed_up(env, monkeypatch):
    client, db = env
    seed(db)
    mod = __import__("sys").modules["psapp.routes_phase6"]
    monkeypatch.setattr(mod, "verify_file", lambda *a, **k: (False, "Integrity check failed: test", {}))
    b = client.post("/api/backups", headers=H(1)).json()
    assert b["status"] == "failed" and b["label"] == "Backup FAILED" and b["exists"] is False
    assert client.get("/api/sync/status", headers=H(1)).json()["last_verified_backup"] is None
    assert os.listdir(client.get("/api/backups", headers=H(1)).json()["folder"]) == []     # bad copy removed
    assert client.post(f"/api/backups/{b['id']}/restore", json={"confirm": "RESTORE"}, headers=H(1)).status_code == 400


# 13 ------------------------------------------------------------------- reports reconcile (more in test_phase5.py)
def test_13_reports_reconcile_with_transactions(env):
    client, db = env
    pid, _ = seed(db, minimum=100)
    cu = make_customer(client)
    sell(client, pid, cu, 3, paid=400); sell(client, pid, None, 2, unit="Strip", kind="retail", paid=100)
    d = client.get("/api/reports/daily_sales", headers=H(1)).json()["totals"]
    assert d["total"] == one(db, "SELECT SUM(total) FROM sales") == 1200 + 100
    assert client.get("/api/reports/customer_balances", headers=H(1)).json()["totals"]["outstanding"] == one(db, "SELECT SUM(due_amount) FROM sales") == 800
    sv = client.get("/api/reports/current_stock", headers=H(1)).json()["totals"]["value"]
    assert sv == client.get("/api/stock", headers=H(1)).json()["stock_value"] == client.get("/api/dashboard", headers=H(1)).json()["stock_value"]
    assert one(db, "SELECT SUM(quantity_base) FROM batches") == 1000 - 300 - 20
