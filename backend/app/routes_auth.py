import math
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request

from . import audit
from .config import LOCK_MINUTES, MAX_FAILED_ATTEMPTS, SESSION_HOURS
from .db import get_db
from .deps import get_current_user
from .permissions import permissions_for, seed_role_permissions
from .schemas import LoginIn, SetupIn
from .security import dummy_hash, hash_password, hash_token, new_token, verify_password
from .util import iso, now_iso, parse, utcnow

router = APIRouter(prefix="/api")


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def me_payload(conn, user: dict) -> dict:
    biz = conn.execute("SELECT id, name FROM businesses WHERE id = ?", (user["business_id"],)).fetchone()
    return {
        "id": user["id"],
        "username": user["username"],
        "full_name": user["full_name"],
        "role": user["role"],
        "permissions": user["permissions"],
        "business": {"id": biz["id"], "name": biz["name"]},
    }


@router.get("/setup/status")
def setup_status(conn=Depends(get_db)):
    count = conn.execute("SELECT COUNT(*) AS c FROM businesses").fetchone()["c"]
    return {"needs_setup": count == 0}


@router.post("/setup", status_code=201)
def setup(body: SetupIn, request: Request, conn=Depends(get_db)):
    conn.execute("BEGIN IMMEDIATE")  # two people cannot run setup at the same moment
    if conn.execute("SELECT COUNT(*) AS c FROM businesses").fetchone()["c"] > 0:
        raise HTTPException(status_code=409, detail="This business is already set up. Please log in.")
    now = now_iso()
    business_id = conn.execute(
        "INSERT INTO businesses (name, owner_name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (body.business_name, body.owner_name, now, now),
    ).lastrowid
    user_id = conn.execute(
        "INSERT INTO users (business_id, username, full_name, password_hash, role, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'owner', ?, ?)",
        (business_id, body.username, body.owner_name, hash_password(body.password), now, now),
    ).lastrowid
    seed_role_permissions(conn, business_id)
    audit.log(conn, business_id, user_id, body.username, "setup_completed",
              f"Business '{body.business_name}' created", client_ip(request))
    return {"ok": True}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, conn=Depends(get_db)):
    ip = client_ip(request)
    now = utcnow()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (body.username,)).fetchone()
    if row is None:
        verify_password(body.password, dummy_hash())
        raise HTTPException(status_code=401, detail="Wrong username or password.")

    user_id, business_id = row["id"], row["business_id"]

    if row["locked_until"] and parse(row["locked_until"]) > now:
        minutes = max(1, math.ceil((parse(row["locked_until"]) - now).total_seconds() / 60))
        raise HTTPException(
            status_code=423,
            detail=f"Too many wrong passwords. This account is locked. Try again in {minutes} minute(s).",
        )

    if not verify_password(body.password, row["password_hash"]):
        attempts = row["failed_attempts"] + 1
        if attempts >= MAX_FAILED_ATTEMPTS:
            conn.execute(
                "UPDATE users SET failed_attempts = 0, locked_until = ? WHERE id = ? AND business_id = ?",
                (iso(now + timedelta(minutes=LOCK_MINUTES)), user_id, business_id),
            )
            audit.log(conn, business_id, user_id, row["username"], "account_locked",
                      f"Locked for {LOCK_MINUTES} minutes after {MAX_FAILED_ATTEMPTS} wrong passwords", ip)
            conn.commit()  # keep the lock even though we return an error
            raise HTTPException(
                status_code=423,
                detail=f"Too many wrong passwords. This account is locked for {LOCK_MINUTES} minutes.",
            )
        conn.execute(
            "UPDATE users SET failed_attempts = ? WHERE id = ? AND business_id = ?",
            (attempts, user_id, business_id),
        )
        audit.log(conn, business_id, user_id, row["username"], "login_failed", "Wrong password", ip)
        conn.commit()
        left = MAX_FAILED_ATTEMPTS - attempts
        raise HTTPException(
            status_code=401,
            detail=f"Wrong username or password. {left} attempt(s) left before the account is locked.",
        )

    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="This account is disabled. Please contact the owner.")

    token = new_token()
    conn.execute("DELETE FROM sessions WHERE business_id = ? AND expires_at < ?", (business_id, iso(now)))
    conn.execute(
        "INSERT INTO sessions (business_id, user_id, token_hash, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (business_id, user_id, hash_token(token), iso(now), iso(now + timedelta(hours=SESSION_HOURS))),
    )
    conn.execute(
        "UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login_at = ? WHERE id = ? AND business_id = ?",
        (iso(now), user_id, business_id),
    )
    audit.log(conn, business_id, user_id, row["username"], "login", None, ip)

    user = {k: row[k] for k in ("id", "business_id", "username", "full_name", "role")}
    user["permissions"] = permissions_for(conn, business_id, row["role"])
    return {"token": token, "user": me_payload(conn, user)}


@router.post("/auth/logout")
def logout(request: Request, user=Depends(get_current_user), conn=Depends(get_db)):
    conn.execute("DELETE FROM sessions WHERE id = ? AND business_id = ?", (user["session_id"], user["business_id"]))
    audit.log(conn, user["business_id"], user["id"], user["username"], "logout", None, client_ip(request))
    return {"ok": True}


@router.get("/auth/me")
def me(user=Depends(get_current_user), conn=Depends(get_db)):
    return me_payload(conn, user)
