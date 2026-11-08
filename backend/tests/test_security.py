"""Phase 7 - security checks."""
import asyncio
import importlib
import json
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
from conftest import H, new_id, seed, make_customer, sell


def test_every_api_endpoint_requires_login(env):
    client, db = env
    sec = importlib.import_module("psapp.security")
    assert sec.endpoints_without_login(client.app) == []


def test_no_login_header_is_refused_everywhere(env):
    client, db = env
    for r in client.app.routes:
        if not getattr(r, "path", "").startswith("/api"):
            continue
        for m in (r.methods or []):
            path = r.path.replace("{", "").replace("}", "")
            for ch in ("sale_id", "customer_id", "backup_id", "name", "code:path"):
                pass
            url = r.path
            import re
            url = re.sub(r"\{[^}]+\}", "1", url)
            res = client.request(m, url, json={} if m in ("POST", "PUT", "PATCH") else None)
            assert res.status_code in (401, 403, 422), f"{m} {r.path} answered {res.status_code} without a login"


def test_salesperson_cannot_use_owner_only_endpoints(env):
    client, db = env
    pid, bid = seed(db)
    cu = make_customer(client)
    checks = [
        ("GET", "/api/backups", None), ("POST", "/api/backups", None),
        ("POST", "/api/backups/1/restore", {"confirm": "RESTORE"}),
        ("GET", "/api/sync/log", None), ("DELETE", "/api/sync/cloud-settings", None),
        ("PUT", "/api/sync/cloud-settings", {"host": "h", "dbname": "d", "username": "u", "password": "p"}),
        ("PUT", "/api/sales/settings", {"allow_negative_stock": True}),
        ("POST", f"/api/stock/batches/{bid}/status", {"status": "blocked", "reason": "test reason"}),
    ]
    for m, url, body in checks:
        r = client.request(m, url, json=body, headers=H(2))
        assert r.status_code == 403, f"{m} {url} -> {r.status_code}"
    # credit settings are owner-only too
    r = client.put(f"/api/customers/{cu}", json={"name": "Ali DEMO", "credit_allowed": True, "credit_limit": 5}, headers=H(2))
    assert r.status_code == 403
    # stock operator cannot adjust stock or sell
    assert client.post("/api/stock/adjustments", json={"product_id": pid, "batch_id": bid, "quantity_base": -1, "reason": "test"}, headers=H(3)).status_code == 403
    assert client.post("/api/sales", json={}, headers=H(3)).status_code == 403


def test_input_validation_refuses_bad_values(env):
    client, db = env
    pid, _ = seed(db)
    cu = make_customer(client)
    base = {"client_uuid": new_id(), "sale_type": "retail", "lines": [{"product_id": pid, "unit_name": "Box", "quantity": 1}], "paid_amount": 500, "payment_method": "Cash"}
    bad = [
        {**base, "lines": [{"product_id": pid, "unit_name": "Box", "quantity": -1}]},
        {**base, "lines": [{"product_id": pid, "unit_name": "Box", "quantity": 0}]},
        {**base, "lines": [{"product_id": pid, "unit_name": "Box", "quantity": 0.5}]},
        {**base, "lines": [{"product_id": pid, "unit_name": "Box", "quantity": 1, "discount": -5}]},
        {**base, "sale_type": "free"},
        {**base, "client_uuid": "x"},
        {**base, "lines": []},
        {**base, "notes": "n" * 5000},
        {**base, "paid_amount": -1},
    ]
    for b in bad:
        assert client.post("/api/sales", json=b, headers=H(1)).status_code in (400, 422), b
    assert client.post(f"/api/customers/{cu}/payments", json={"client_uuid": new_id(), "amount": -5, "method": "Cash"}, headers=H(1)).status_code == 422
    c = db.connect()
    assert c.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0
    c.close()


def test_search_text_cannot_inject_sql(env):
    client, db = env
    seed(db)
    for evil in ["' OR 1=1 --", "'; DROP TABLE products; --", "%", "\" OR \"\"=\""]:
        assert client.get("/api/sales/products", params={"search": evil}, headers=H(1)).status_code == 200
        assert client.get("/api/sales", params={"search": evil}, headers=H(1)).status_code == 200
        assert client.get(f"/api/sales/scan/{evil}", headers=H(1)).status_code == 200
    c = db.connect()
    assert c.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1
    c.close()


def test_report_name_and_dates_cannot_escape(env):
    client, db = env
    assert client.get("/api/reports/..%2F..%2Fetc", headers=H(1)).status_code in (404, 400)
    assert client.get("/api/reports/daily_sales", params={"from": "2026-01-01; DROP TABLE sales"}, headers=H(1)).status_code == 400


# ---------------------------------------------------------------- middleware (own small app)
def small_app():
    sec = importlib.import_module("psapp.security")
    app = FastAPI()

    @app.post("/api/auth/login")
    def login():
        return {"ok": True}

    @app.post("/api/products/import")
    async def imp(request_body: dict):
        return {"ok": True}

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    app.add_middleware(sec.BodyLimitMiddleware, json_bytes=1000, upload_bytes=5000)
    app.add_middleware(sec.LoginRateLimitMiddleware, max_tries=3, window=60)
    app.add_middleware(sec.SecurityHeadersMiddleware)
    return app


def test_login_rate_limit(env):
    c = TestClient(small_app())
    codes = [c.post("/api/auth/login").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    r = c.post("/api/auth/login")
    assert "Retry-After" in r.headers and "Too many" in r.json()["detail"]
    assert c.get("/api/ping").status_code == 200       # other pages are not limited


def test_big_requests_refused(env):
    c = TestClient(small_app())
    assert c.post("/api/products/import", json={"x": "a" * 2000}).status_code == 200   # import limit is bigger
    assert c.post("/api/products/import", json={"x": "a" * 6000}).status_code == 413
    assert c.post("/api/auth/login", content=b"a" * 2000, headers={"content-type": "application/json"}).status_code == 413
    assert c.post("/api/auth/login", content=b"a" * 200).status_code == 200


def test_safe_headers(env):
    r = TestClient(small_app()).get("/api/ping")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"


def test_frontend_served_by_backend(env, tmp_path):
    sec = importlib.import_module("psapp.security")
    out = tmp_path / "out"; (out / "sales").mkdir(parents=True)
    (out / "index.html").write_text("<h1>HOME</h1>"); (out / "sales" / "index.html").write_text("<h1>SALES</h1>"); (out / "reports.html").write_text("<h1>REPORTS</h1>")
    app = FastAPI()

    @app.get("/api/health")
    def h():
        return {"status": "ok"}
    assert sec.mount_frontend(app, out) is True
    c = TestClient(app)
    assert c.get("/").text == "<h1>HOME</h1>" and "SALES" in c.get("/sales").text and "REPORTS" in c.get("/reports").text
    assert c.get("/api/health").json() == {"status": "ok"}
    assert sec.mount_frontend(FastAPI(), tmp_path / "nothing") is False
