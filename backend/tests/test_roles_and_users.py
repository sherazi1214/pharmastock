from app.db import connect

from .conftest import add_user, login


def test_salesperson_is_refused_by_the_server(client, owner_headers):
    add_user(client, owner_headers, "sam", "salesperson")
    sales = login(client, "sam", "UserPass123")
    assert client.get("/api/settings", headers=sales).status_code == 403
    assert client.put("/api/settings", headers=sales, json={
        "business_name": "Hacked", "owner_name": "X Y", "payment_methods": ["Cash"], "near_expiry_days": 90}).status_code == 403
    assert client.get("/api/users", headers=sales).status_code == 403
    assert client.post("/api/users", headers=sales, json={
        "username": "evil", "full_name": "Evil One", "password": "EvilPass123", "role": "owner"}).status_code == 403
    assert client.patch("/api/users/1", headers=sales, json={"is_active": False}).status_code == 403
    assert client.post("/api/users/1/reset-password", headers=sales, json={"new_password": "EvilPass123"}).status_code == 403
    assert client.get("/api/permissions", headers=sales).status_code == 403
    assert client.put("/api/permissions/salesperson", headers=sales, json={"permissions": []}).status_code == 403
    assert client.get("/api/audit-logs", headers=sales).status_code == 403


def test_stock_operator_is_also_refused(client, owner_headers):
    add_user(client, owner_headers, "stan", "stock_operator")
    h = login(client, "stan", "UserPass123")
    assert client.get("/api/settings", headers=h).status_code == 403
    assert client.get("/api/users", headers=h).status_code == 403


def test_default_permissions_per_role(client, owner_headers):
    add_user(client, owner_headers, "sam", "salesperson")
    add_user(client, owner_headers, "stan", "stock_operator")
    sales = client.get("/api/auth/me", headers=login(client, "sam", "UserPass123")).json()["permissions"]
    stock = client.get("/api/auth/me", headers=login(client, "stan", "UserPass123")).json()["permissions"]
    owner = client.get("/api/auth/me", headers=owner_headers).json()["permissions"]
    assert "manage_sales" in sales and "view_profit" not in sales and "view_purchase_price" not in sales
    assert "manage_purchases" in stock and "view_profit" not in stock and "manage_sales" not in stock
    assert "view_profit" in owner


def test_owner_can_change_role_permissions(client, owner_headers):
    add_user(client, owner_headers, "sam", "salesperson")
    r = client.put("/api/permissions/salesperson", headers=owner_headers,
                   json={"permissions": ["view_dashboard", "manage_sales", "give_discount"]})
    assert r.status_code == 200
    perms = client.get("/api/auth/me", headers=login(client, "sam", "UserPass123")).json()["permissions"]
    assert perms == ["view_dashboard", "manage_sales", "give_discount"]
    assert client.put("/api/permissions/owner", headers=owner_headers, json={"permissions": []}).status_code == 400
    assert client.put("/api/permissions/salesperson", headers=owner_headers, json={"permissions": ["fly"]}).status_code == 400


def test_owner_manages_users(client, owner_headers):
    u = add_user(client, owner_headers, "sam", "salesperson")
    assert client.post("/api/users", headers=owner_headers, json={
        "username": "SAM", "full_name": "Other Sam", "password": "UserPass123", "role": "salesperson"}).status_code == 409
    assert len(client.get("/api/users", headers=owner_headers).json()) == 2
    r = client.patch(f"/api/users/{u['id']}", headers=owner_headers, json={"role": "stock_operator", "full_name": "Sam Khan"})
    assert r.json()["role"] == "stock_operator" and r.json()["full_name"] == "Sam Khan"


def test_disabling_user_blocks_login_and_kills_session(client, owner_headers):
    u = add_user(client, owner_headers, "sam", "salesperson")
    sales = login(client, "sam", "UserPass123")
    assert client.patch(f"/api/users/{u['id']}", headers=owner_headers, json={"is_active": False}).status_code == 200
    assert client.get("/api/auth/me", headers=sales).status_code == 401
    assert client.post("/api/auth/login", json={"username": "sam", "password": "UserPass123"}).status_code == 403
    client.patch(f"/api/users/{u['id']}", headers=owner_headers, json={"is_active": True})
    login(client, "sam", "UserPass123")


def test_owner_cannot_disable_or_demote_self(client, owner_headers):
    me = client.get("/api/auth/me", headers=owner_headers).json()
    assert client.patch(f"/api/users/{me['id']}", headers=owner_headers, json={"is_active": False}).status_code == 400
    assert client.patch(f"/api/users/{me['id']}", headers=owner_headers, json={"role": "salesperson"}).status_code == 400


def test_reset_password_unlocks_and_replaces_old_password(client, owner_headers):
    u = add_user(client, owner_headers, "sam", "salesperson")
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "sam", "password": "wrong"})
    assert client.post("/api/auth/login", json={"username": "sam", "password": "UserPass123"}).status_code == 423
    assert client.post(f"/api/users/{u['id']}/reset-password", headers=owner_headers,
                       json={"new_password": "BrandNew1234"}).status_code == 200
    assert client.post("/api/auth/login", json={"username": "sam", "password": "UserPass123"}).status_code == 401
    login(client, "sam", "BrandNew1234")


def test_settings_update_and_validation(client, owner_headers):
    body = {"business_name": "Shifa Medical Store", "owner_name": "Ali Owner", "address": "Main Bazar",
            "phone": "0300-0000000", "licence_number": "LIC-123",
            "payment_methods": ["Cash", "Bank Transfer", "cash", "JazzCash"], "near_expiry_days": 60}
    r = client.put("/api/settings", headers=owner_headers, json=body)
    assert r.status_code == 200
    got = client.get("/api/settings", headers=owner_headers).json()
    assert got["payment_methods"] == ["Cash", "Bank Transfer", "JazzCash"]  # duplicate removed
    assert got["near_expiry_days"] == 60 and got["business_name"] == "Shifa Medical Store"
    assert client.get("/api/auth/me", headers=owner_headers).json()["business"]["name"] == "Shifa Medical Store"
    assert client.put("/api/settings", headers=owner_headers, json={**body, "near_expiry_days": 0}).status_code == 422
    assert client.put("/api/settings", headers=owner_headers, json={**body, "payment_methods": []}).status_code == 422


def test_default_near_expiry_is_90(client, owner_headers):
    assert client.get("/api/settings", headers=owner_headers).json()["near_expiry_days"] == 90


def test_audit_log_records_important_actions(client, owner_headers):
    u = add_user(client, owner_headers, "sam", "salesperson")
    client.patch(f"/api/users/{u['id']}", headers=owner_headers, json={"is_active": False})
    client.post(f"/api/users/{u['id']}/reset-password", headers=owner_headers, json={"new_password": "BrandNew1234"})
    client.put("/api/settings", headers=owner_headers, json={
        "business_name": "New Name", "owner_name": "Ali Owner", "payment_methods": ["Cash"], "near_expiry_days": 45})
    client.put("/api/permissions/salesperson", headers=owner_headers, json={"permissions": ["view_dashboard"]})
    client.post("/api/auth/logout", headers=owner_headers)
    owner2 = login(client)
    actions = {row["action"] for row in client.get("/api/audit-logs", headers=owner2).json()}
    for expected in ("setup_completed", "login", "logout", "user_created", "user_disabled",
                     "password_reset", "settings_changed", "permissions_changed"):
        assert expected in actions, expected


def test_failed_login_and_lock_are_audited(client, owner_headers):
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "owner", "password": "wrong"})
    conn = connect()
    actions = [r["action"] for r in conn.execute("SELECT action FROM audit_logs")]
    conn.close()
    assert actions.count("login_failed") == 4 and "account_locked" in actions
