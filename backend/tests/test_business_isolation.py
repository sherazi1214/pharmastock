from .conftest import add_user, login, make_second_business


def test_business_data_is_isolated(client, owner_headers):
    add_user(client, owner_headers, "sam", "salesperson")
    me1 = client.get("/api/auth/me", headers=owner_headers).json()
    bid2, ids = make_second_business()
    owner2 = login(client, "owner2", "OtherPass123")

    # Lists only show own business
    users2 = {u["username"] for u in client.get("/api/users", headers=owner2).json()}
    assert users2 == {"owner2", "sales2"}
    users1 = {u["username"] for u in client.get("/api/users", headers=owner_headers).json()}
    assert users1 == {"owner", "sam"}

    # Settings belong to the right business
    assert client.get("/api/settings", headers=owner2).json()["business_name"] == "Other Pharmacy"
    assert client.get("/api/settings", headers=owner_headers).json()["business_name"] == "Test Pharmacy"

    # Cannot touch the other business's users
    assert client.patch(f"/api/users/{me1['id']}", headers=owner2, json={"is_active": False}).status_code == 404
    assert client.post(f"/api/users/{me1['id']}/reset-password", headers=owner2,
                       json={"new_password": "Takeover1234"}).status_code == 404
    assert client.patch(f"/api/users/{ids['sales2']}", headers=owner_headers, json={"role": "owner"}).status_code == 404
    login(client, "owner")  # still works with the old password

    # Audit logs are separate
    logs2 = client.get("/api/audit-logs", headers=owner2).json()
    assert logs2 and all(row["username"] in ("owner2", "sales2") for row in logs2)
    logs1 = client.get("/api/audit-logs", headers=owner_headers).json()
    assert all(row["username"] in ("owner", "sam") for row in logs1)

    # Permission changes are separate
    client.put("/api/permissions/salesperson", headers=owner2, json={"permissions": []})
    sales1 = login(client, "sam", "UserPass123")
    assert "manage_sales" in client.get("/api/auth/me", headers=sales1).json()["permissions"]
    assert client.get("/api/auth/me", headers=login(client, "sales2", "OtherPass123")).json()["permissions"] == []

    # Usernames are unique across the whole system
    assert client.post("/api/users", headers=owner2, json={
        "username": "sam", "full_name": "Dup Sam", "password": "UserPass123", "role": "salesperson"}).status_code == 409
