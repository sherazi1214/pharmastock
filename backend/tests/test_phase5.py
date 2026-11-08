import base64, csv, io
from datetime import date
from conftest import H, new_id, seed, make_customer, sell


def pay(client, cust, amount, uid=None, user=1, method="Cash"):
    return client.post(f"/api/customers/{cust}/payments", json={"client_uuid": uid or new_id(), "amount": amount, "method": method}, headers=H(user))


def raw(db, sql, *a):
    c = db.connect(); r = c.execute(sql, a).fetchone(); c.close(); return r[0]


# ---------------------------------------------------------------- customer payments
def test_credit_sale_raises_balance_and_payment_pays_oldest_first(env):
    client, db = env
    pid, _ = seed(db)
    cu = make_customer(client)
    s1 = sell(client, pid, cu, 1)          # 400
    s2 = sell(client, pid, cu, 2)          # 800
    s3 = sell(client, pid, cu, 1, paid=100)  # 400, 100 paid -> 300 due
    acc = client.get(f"/api/customers/{cu}/account", headers=H(1)).json()
    assert acc["outstanding"] == 400 + 800 + 300
    r = pay(client, cu, 500)
    assert r.status_code == 201, r.text
    assert [a["invoice_number"] for a in r.json()["applied_to"]] == [s1["invoice_number"], s2["invoice_number"]]
    acc = client.get(f"/api/customers/{cu}/account", headers=H(1)).json()
    dues = {x["invoice_number"]: x["due_amount"] for x in acc["open_invoices"]}
    assert s1["invoice_number"] not in dues                     # fully paid
    assert dues[s2["invoice_number"]] == 700                    # 800 - 100
    assert dues[s3["invoice_number"]] == 300
    assert acc["outstanding"] == 1000
    # paid_amount + due_amount must still equal total on every invoice
    c = db.connect()
    for r_ in c.execute("SELECT total, paid_amount, due_amount FROM sales"):
        assert abs(r_["paid_amount"] + r_["due_amount"] - r_["total"]) < 0.005
    c.close()


def test_payment_more_than_owed_and_bad_method_refused(env):
    client, db = env
    pid, _ = seed(db)
    cu = make_customer(client)
    sell(client, pid, cu, 1)
    assert pay(client, cu, 400.01).status_code == 400
    assert pay(client, cu, 100, method="Bitcoin").status_code == 400
    assert raw(db, "SELECT COUNT(*) FROM customer_payments") == 0
    assert client.get(f"/api/customers/{cu}/account", headers=H(1)).json()["outstanding"] == 400


def test_same_payment_uuid_saved_once(env):
    client, db = env
    pid, _ = seed(db)
    cu = make_customer(client)
    sell(client, pid, cu, 2)
    u = new_id()
    codes = [pay(client, cu, 300, uid=u).status_code for _ in range(3)]
    assert codes == [201, 200, 200]
    assert raw(db, "SELECT COUNT(*) FROM customer_payments") == 1
    assert client.get(f"/api/customers/{cu}/account", headers=H(1)).json()["outstanding"] == 500


def test_payment_after_return_and_customer_isolation(env):
    client, db = env
    pid, _ = seed(db)
    cu = make_customer(client)
    s = sell(client, pid, cu, 2)  # 800 due
    item = client.get(f"/api/sales/{s['id']}", headers=H(1)).json()["items"][0]["id"]
    r = client.post(f"/api/sales/{s['id']}/returns", json={"client_uuid": new_id(), "action": "restock", "reason": "wrong item",
                    "lines": [{"sale_item_id": item, "unit_name": "Box", "quantity": 1}]}, headers=H(1))
    assert r.status_code == 201, r.text
    assert client.get(f"/api/customers/{cu}/account", headers=H(1)).json()["outstanding"] == 400
    # business 2 cannot see or pay business 1's customer
    assert client.get(f"/api/customers/{cu}/account", headers=H(4)).status_code == 404
    assert pay(client, cu, 100, user=4).status_code == 404
    assert raw(db, "SELECT COUNT(*) FROM customer_payments") == 0


def test_salesperson_without_customer_permission_refused(env):
    client, db = env
    pid, _ = seed(db); cu = make_customer(client)
    assert client.get(f"/api/customers/{cu}/account", headers=H(3)).status_code == 403
    assert pay(client, cu, 10, user=3).status_code == 403


# ---------------------------------------------------------------- dashboard
def test_dashboard_equals_raw_records(env):
    client, db = env
    pid, _ = seed(db, minimum=2000)                      # 1000 base on hand, minimum 2000 -> low stock
    pid2, _ = seed(db, name="Brufen DEMO", batch="B9", expiry_days=30, minimum=0)   # near expiry
    pid3, _ = seed(db, name="Old DEMO", batch="B7", expiry_days=1000)
    cu = make_customer(client)
    sell(client, pid, cu, 2, paid=100)                   # 800 total, 700 due
    sell(client, pid3, None, 3, kind="retail", paid=1500)
    d = client.get("/api/dashboard", headers=H(1)).json()
    assert d["today_sales"] == raw(db, "SELECT SUM(total) FROM sales") == 800 + 1500
    assert d["today_purchases"] == raw(db, "SELECT SUM(total) FROM purchases")
    assert d["customer_outstanding"] == raw(db, "SELECT SUM(due_amount) FROM sales WHERE customer_id IS NOT NULL") == 700
    expected_value = raw(db, "SELECT SUM(ba.quantity_base*pi.unit_cost/pi.unit_factor) FROM batches ba JOIN purchase_items pi ON pi.batch_id=ba.id")
    assert abs(d["stock_value"] - expected_value) < 0.01
    assert d["low_stock_count"] == 1
    assert d["near_expiry_count"] == 1
    # stock value equals the Stock page
    stock = client.get("/api/stock", headers=H(1)).json()
    assert abs(stock["stock_value"] - d["stock_value"]) < 0.01


def test_dashboard_hides_money_from_people_without_permission(env):
    client, db = env
    seed(db)
    d = client.get("/api/dashboard", headers=H(2)).json()      # salesperson
    assert d["stock_value"] is None and d["customer_outstanding"] is None and d["today_purchases"] is None
    assert d["today_sales"] == 0
    d = client.get("/api/dashboard", headers=H(3)).json()      # stock operator
    assert d["stock_value"] is None and d["customer_outstanding"] is None
    assert d["today_purchases"] is not None


def test_dashboard_isolated_between_businesses(env):
    client, db = env
    pid, _ = seed(db)
    sell(client, pid, make_customer(client), 1, paid=400)
    d2 = client.get("/api/dashboard", headers=H(4)).json()
    assert d2["today_sales"] == 0 and d2["stock_value"] == 0 and d2["customer_outstanding"] == 0


# ---------------------------------------------------------------- reports
def rep(client, name, user=1, **q):
    return client.get(f"/api/reports/{name}", params=q, headers=H(user))


def test_sales_reports_reconcile(env):
    client, db = env
    pid, _ = seed(db)
    cu = make_customer(client)
    s = sell(client, pid, cu, 3, paid=200)
    sell(client, pid, None, 5, unit="Strip", kind="retail", paid=250)
    item = client.get(f"/api/sales/{s['id']}", headers=H(1)).json()["items"][0]["id"]
    client.post(f"/api/sales/{s['id']}/returns", json={"client_uuid": new_id(), "action": "restock", "reason": "damaged box",
                "lines": [{"sale_item_id": item, "unit_name": "Box", "quantity": 1}]}, headers=H(1))
    daily = rep(client, "daily_sales").json()
    assert daily["totals"]["total"] == raw(db, "SELECT SUM(total) FROM sales")
    assert daily["totals"]["returns"] == raw(db, "SELECT SUM(total) FROM sale_returns") == 400
    assert daily["totals"]["net_sales"] == daily["totals"]["total"] - 400
    assert daily["totals"]["invoices"] == 2
    monthly = rep(client, "monthly_sales").json()
    assert monthly["totals"] == {k: daily["totals"][k] for k in monthly["totals"]}
    best = rep(client, "best_selling").json()
    assert best["rows"][0]["quantity_base"] == 300 - 100 + 50    # sold 3 boxes, returned 1, +5 strips
    assert abs(best["totals"]["revenue"] - daily["totals"]["net_sales"]) < 0.01
    # a range with no sales is empty
    assert rep(client, "daily_sales", **{"from": "2020-01-01", "to": "2020-01-31"}).json()["rows"] == []


def test_stock_reports_reconcile(env):
    client, db = env
    seed(db, name="A DEMO", qty_boxes=10, batch="A1", cost_box=300, minimum=5000)
    seed(db, name="B DEMO", qty_boxes=2, batch="B1", expiry_days=20, cost_box=500)
    seed(db, name="C DEMO", qty_boxes=1, batch="C1", expiry_days=-10, cost_box=100)
    cur = rep(client, "current_stock").json()
    assert cur["totals"]["value"] == client.get("/api/stock", headers=H(1)).json()["stock_value"] == 10 * 300 + 2 * 500 + 100
    assert sum(r["quantity_base"] for r in cur["rows"]) == raw(db, "SELECT SUM(quantity_base) FROM batches")
    assert [r["product"] for r in rep(client, "near_expiry").json()["rows"]] == ["B DEMO"]
    exp = rep(client, "expired_stock").json()
    assert [r["product"] for r in exp["rows"]] == ["C DEMO"] and exp["rows"][0]["status"] == "Expired"
    assert [r["product"] for r in rep(client, "low_stock").json()["rows"]] == ["A DEMO"]
    assert rep(client, "current_stock", user=3).json()["totals"] == {}      # no cost permission -> no value
    assert "value" not in rep(client, "current_stock", user=3).json()["rows"][0]


def test_balance_reports_reconcile(env):
    client, db = env
    pid, _ = seed(db)
    c1, c2 = make_customer(client, "A DEMO"), make_customer(client, "B DEMO")
    sell(client, pid, c1, 2); sell(client, pid, c2, 1, paid=150)
    pay(client, c1, 300)
    cb = rep(client, "customer_balances").json()
    assert cb["totals"]["outstanding"] == raw(db, "SELECT SUM(due_amount) FROM sales") == 500 + 250
    assert {r["name"]: r["outstanding"] for r in cb["rows"]} == {"A DEMO": 500, "B DEMO": 250}
    sb = rep(client, "supplier_balances").json()
    assert sb["totals"]["outstanding"] == raw(db, "SELECT SUM(due_amount) FROM purchases") == 1500
    ph = rep(client, "purchase_history").json()
    assert ph["totals"]["total"] == 3000 and ph["totals"]["due"] == 1500


def test_profit_estimate_uses_batch_cost_and_returns(env):
    client, db = env
    pid, _ = seed(db, cost_box=300)                 # cost 3.00 per tablet
    cu = make_customer(client)
    s = sell(client, pid, cu, 4)                    # revenue 1600, cost 1200
    item = client.get(f"/api/sales/{s['id']}", headers=H(1)).json()["items"][0]["id"]
    for action in ("restock", "write_off"):         # return 1 box each way
        r = client.post(f"/api/sales/{s['id']}/returns", json={"client_uuid": new_id(), "action": action, "reason": "test return",
                        "lines": [{"sale_item_id": item, "unit_name": "Box", "quantity": 1}]}, headers=H(1))
        assert r.status_code == 201, r.text
    p = rep(client, "profit").json()
    # revenue 1600 - returns 800 - cost 1200 + cost of the restocked box 300 = -100 (written-off box cost stays a loss)
    assert p["totals"] == {"revenue": 1600, "returns": 800, "cost_of_goods_sold": 900, "estimated_gross_profit": 1600 - 800 - 900}
    assert p["title"] == "Estimated gross profit"
    assert "expenses" in p["note"] and "not track" in p["note"]


def test_profit_cost_and_balance_reports_need_permission(env):
    client, db = env
    seed(db)
    for name in ("profit", "customer_balances", "supplier_balances", "purchase_history"):
        assert rep(client, name, user=2).status_code == 403, name   # salesperson
        assert rep(client, name, user=3).status_code == 403, name   # stock operator
        assert rep(client, name, user=1).status_code == 200, name
        assert client.get(f"/api/reports/{name}/download", headers=H(2)).status_code == 403
        assert client.get(f"/api/reports/{name}/export", headers=H(2)).status_code == 403
    names = [x["name"] for x in client.get("/api/reports", headers=H(2)).json()["items"]]
    assert "profit" not in names and "daily_sales" in names
    # no report permission at all
    c = db.connect(); c.execute("UPDATE users SET permissions='[]' WHERE id=2"); c.commit(); c.close()
    assert rep(client, "daily_sales", user=2).status_code == 403


def test_reports_isolated_between_businesses(env):
    client, db = env
    pid, _ = seed(db)
    sell(client, pid, make_customer(client), 1)
    for name in ("daily_sales", "current_stock", "customer_balances", "supplier_balances", "profit", "best_selling", "purchase_history"):
        r = rep(client, name, user=4).json()
        assert r["rows"] == [] or all(x.get("amount", 0) == 0 for x in r["rows"]), name


def test_bad_dates_rejected(env):
    client, db = env
    assert rep(client, "daily_sales", **{"from": "x"}).status_code == 400
    assert rep(client, "daily_sales", **{"from": "2026-05-02", "to": "2026-05-01"}).status_code == 400
    assert rep(client, "nope").status_code == 404


# ---------------------------------------------------------------- exports
def test_csv_and_excel_exports_open_and_match(env):
    client, db = env
    pid, _ = seed(db, name="=HYPERLINK DEMO")
    sell(client, pid, make_customer(client, "+Evil DEMO"), 1, paid=100)
    r = client.get("/api/reports/daily_sales/download", params={"format": "csv"}, headers=H(1))
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[0] == ["Daily sales"] and rows[3][0] == "Date"
    assert rows[4][4] == "400.0" and rows[-3][0] == "TOTAL"
    r = client.get("/api/reports/customer_balances/download", params={"format": "csv"}, headers=H(1))
    assert "'+Evil DEMO" in r.content.decode("utf-8-sig")      # formula-looking text is neutralised
    from openpyxl import load_workbook
    r = client.get("/api/reports/current_stock/download", params={"format": "xlsx"}, headers=H(1))
    ws = load_workbook(io.BytesIO(r.content)).active
    assert ws["A1"].value == "Current stock" and ws["A4"].value == "Medicine"
    assert str(ws["A5"].value).startswith("'=HYPERLINK")
    j = client.get("/api/reports/profit/export", params={"format": "xlsx"}, headers=H(1)).json()
    ws = load_workbook(io.BytesIO(base64.b64decode(j["data_base64"]))).active
    labels = [row[0].value for row in ws.iter_rows(min_row=5, max_row=9)]
    assert labels[-1] == "Estimated gross profit" and j["filename"].endswith(".xlsx")
    assert raw(db, "SELECT COUNT(*) FROM audit_logs WHERE action='report_exported'") >= 4
