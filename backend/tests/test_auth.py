from datetime import timedelta

from app.db import connect
from app.util import iso, utcnow

from .conftest import OWNER, login, setup_owner


def test_setup_runs_only_once(client):
    assert client.get("/api/setup/status").json() == {"needs_setup": True}
    setup_owner(client)
    assert client.get("/api/setup/status").json() == {"needs_setup": False}
    again = client.post("/api/setup", json={**OWNER, "username": "second"})
    assert again.status_code == 409


def test_setup_validation_messages_are_readable(client):
    r = client.post("/api/setup", json={**OWNER, "password": "short"})
    assert r.status_code == 422
    assert "at least 8" in r.json()["detail"]
    r = client.post("/api/setup", json={**OWNER, "username": "bad name!"})
    assert r.status_code == 422
    assert client.get("/api/setup/status").json()["needs_setup"] is True


def test_password_is_stored_as_hash(client):
    setup_owner(client)
    conn = connect()
    stored = conn.execute("SELECT password_hash FROM users WHERE username='owner'").fetchone()["password_hash"]
    conn.close()
    assert stored != OWNER["password"]
    assert OWNER["password"] not in stored
    assert stored.startswith("$2")  # bcrypt


def test_login_ok_and_me(client):
    setup_owner(client)
    r = client.post("/api/auth/login", json={"username": "owner", "password": OWNER["password"]})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "owner" and body["user"]["business"]["name"] == "Test Pharmacy"
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200 and me.json()["username"] == "owner"


def test_wrong_password_and_unknown_user_rejected(client):
    setup_owner(client)
    assert client.post("/api/auth/login", json={"username": "owner", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "ghost", "password": "nope"}).status_code == 401


def test_token_is_not_stored_in_plain_text(client):
    setup_owner(client)
    headers = login(client)
    token = headers["Authorization"].split()[1]
    conn = connect()
    hashes = [r["token_hash"] for r in conn.execute("SELECT token_hash FROM sessions")]
    conn.close()
    assert token not in hashes


def test_account_locks_after_5_wrong_passwords(client):
    setup_owner(client)
    for _ in range(4):
        assert client.post("/api/auth/login", json={"username": "owner", "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "owner", "password": "wrong"}).status_code == 423
    # even the correct password is refused while locked
    assert client.post("/api/auth/login", json={"username": "owner", "password": OWNER["password"]}).status_code == 423
    # after 5 minutes it works again
    conn = connect()
    conn.execute("UPDATE users SET locked_until = ? WHERE username = 'owner'", (iso(utcnow() - timedelta(seconds=1)),))
    conn.commit()
    conn.close()
    assert client.post("/api/auth/login", json={"username": "owner", "password": OWNER["password"]}).status_code == 200


def test_wrong_attempts_reset_after_good_login(client):
    setup_owner(client)
    for _ in range(3):
        client.post("/api/auth/login", json={"username": "owner", "password": "wrong"})
    login(client)
    for _ in range(4):
        assert client.post("/api/auth/login", json={"username": "owner", "password": "wrong"}).status_code == 401


def test_logout_ends_session(client):
    setup_owner(client)
    headers = login(client)
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_no_token_or_bad_token_is_401(client):
    setup_owner(client)
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer abc"}).status_code == 401
    assert client.get("/api/users").status_code == 401


def test_expired_session_is_rejected(client):
    setup_owner(client)
    headers = login(client)
    conn = connect()
    conn.execute("UPDATE sessions SET expires_at = ?", (iso(utcnow() - timedelta(minutes=1)),))
    conn.commit()
    conn.close()
    assert client.get("/api/auth/me", headers=headers).status_code == 401
