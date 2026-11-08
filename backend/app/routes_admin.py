import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from . import audit
from .db import get_db
from .deps import require_owner
from .permissions import EDITABLE_ROLES, PERMISSION_KEYS, PERMISSIONS, permissions_for
from .routes_auth import client_ip
from .schemas import PermissionsIn, ResetPasswordIn, SettingsIn, UserCreateIn, UserUpdateIn
from .security import hash_password
from .util import now_iso, parse, utcnow

router = APIRouter(prefix="/api")


# ---------- Settings ----------

def _business_dict(row) -> dict:
    return {
        "business_name": row["name"],
        "owner_name": row["owner_name"],
        "address": row["address"],
        "phone": row["phone"],
        "licence_number": row["licence_number"],
        "payment_methods": json.loads(row["payment_methods"]),
        "near_expiry_days": row["near_expiry_days"],
    }


@router.get("/settings")
def get_settings(owner=Depends(require_owner), conn=Depends(get_db)):
    row = conn.execute("SELECT * FROM businesses WHERE id = ?", (owner["business_id"],)).fetchone()
    return _business_dict(row)


@router.put("/settings")
def update_settings(body: SettingsIn, request: Request, owner=Depends(require_owner), conn=Depends(get_db)):
    bid = owner["business_id"]
    old = _business_dict(conn.execute("SELECT * FROM businesses WHERE id = ?", (bid,)).fetchone())
    new = body.model_dump()
    conn.execute(
        "UPDATE businesses SET name = ?, owner_name = ?, address = ?, phone = ?, licence_number = ?, "
        "payment_methods = ?, near_expiry_days = ?, updated_at = ? WHERE id = ?",
        (new["business_name"], new["owner_name"], new["address"], new["phone"], new["licence_number"],
         json.dumps(new["payment_methods"]), new["near_expiry_days"], now_iso(), bid),
    )
    changes = [f"{k}: {old[k]!r} -> {new[k]!r}" for k in new if old[k] != new[k]]
    if changes:
        audit.log(conn, bid, owner["id"], owner["username"], "settings_changed",
                  "; ".join(changes)[:500], client_ip(request))
    return new


# ---------- Users ----------

def _user_dict(row) -> dict:
    locked = bool(row["locked_until"] and parse(row["locked_until"]) > utcnow())
    return {
        "id": row["id"],
        "username": row["username"],
        "full_name": row["full_name"],
        "role": row["role"],
        "is_active": bool(row["is_active"]),
        "locked": locked,
        "last_login_at": row["last_login_at"],
        "created_at": row["created_at"],
    }


def _get_user_or_404(conn, business_id: int, user_id: int):
    row = conn.execute("SELECT * FROM users WHERE id = ? AND business_id = ?", (user_id, business_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return row


@router.get("/users")
def list_users(owner=Depends(require_owner), conn=Depends(get_db)):
    rows = conn.execute("SELECT * FROM users WHERE business_id = ? ORDER BY id", (owner["business_id"],)).fetchall()
    return [_user_dict(r) for r in rows]


@router.post("/users", status_code=201)
def create_user(body: UserCreateIn, request: Request, owner=Depends(require_owner), conn=Depends(get_db)):
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (body.username,)).fetchone():
        raise HTTPException(status_code=409, detail="This username is already taken. Please choose another.")
    now = now_iso()
    new_id = conn.execute(
        "INSERT INTO users (business_id, username, full_name, password_hash, role, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (owner["business_id"], body.username, body.full_name, hash_password(body.password), body.role, now, now),
    ).lastrowid
    audit.log(conn, owner["business_id"], owner["id"], owner["username"], "user_created",
              f"Created user '{body.username}' with role {body.role}", client_ip(request))
    return _user_dict(_get_user_or_404(conn, owner["business_id"], new_id))


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdateIn, request: Request, owner=Depends(require_owner), conn=Depends(get_db)):
    bid = owner["business_id"]
    target = _get_user_or_404(conn, bid, user_id)
    ip = client_ip(request)

    if target["id"] == owner["id"]:
        if body.is_active is False:
            raise HTTPException(status_code=400, detail="You cannot disable your own account.")
        if body.role is not None and body.role != "owner":
            raise HTTPException(status_code=400, detail="You cannot remove your own owner role.")

    if body.full_name is not None and body.full_name != target["full_name"]:
        conn.execute("UPDATE users SET full_name = ?, updated_at = ? WHERE id = ? AND business_id = ?",
                     (body.full_name, now_iso(), user_id, bid))
        audit.log(conn, bid, owner["id"], owner["username"], "user_changed",
                  f"Renamed '{target['username']}' to '{body.full_name}'", ip)
    if body.role is not None and body.role != target["role"]:
        conn.execute("UPDATE users SET role = ?, updated_at = ? WHERE id = ? AND business_id = ?",
                     (body.role, now_iso(), user_id, bid))
        audit.log(conn, bid, owner["id"], owner["username"], "user_changed",
                  f"Role of '{target['username']}' changed from {target['role']} to {body.role}", ip)
    if body.is_active is not None and bool(target["is_active"]) != body.is_active:
        conn.execute("UPDATE users SET is_active = ?, updated_at = ? WHERE id = ? AND business_id = ?",
                     (1 if body.is_active else 0, now_iso(), user_id, bid))
        if not body.is_active:
            conn.execute("DELETE FROM sessions WHERE user_id = ? AND business_id = ?", (user_id, bid))
        audit.log(conn, bid, owner["id"], owner["username"],
                  "user_enabled" if body.is_active else "user_disabled", f"User '{target['username']}'", ip)
    return _user_dict(_get_user_or_404(conn, bid, user_id))


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, body: ResetPasswordIn, request: Request,
                   owner=Depends(require_owner), conn=Depends(get_db)):
    bid = owner["business_id"]
    target = _get_user_or_404(conn, bid, user_id)
    conn.execute(
        "UPDATE users SET password_hash = ?, failed_attempts = 0, locked_until = NULL, updated_at = ? "
        "WHERE id = ? AND business_id = ?",
        (hash_password(body.new_password), now_iso(), user_id, bid),
    )
    conn.execute("DELETE FROM sessions WHERE user_id = ? AND business_id = ?", (user_id, bid))
    audit.log(conn, bid, owner["id"], owner["username"], "password_reset",
              f"Password reset for '{target['username']}'", client_ip(request))
    return {"ok": True}


# ---------- Permissions ----------

@router.get("/permissions")
def get_permissions(owner=Depends(require_owner), conn=Depends(get_db)):
    return {
        "permissions": [{"key": k, "label": label} for k, label in PERMISSIONS],
        "roles": {role: permissions_for(conn, owner["business_id"], role) for role in EDITABLE_ROLES},
    }


@router.put("/permissions/{role}")
def set_permissions(role: str, body: PermissionsIn, request: Request,
                    owner=Depends(require_owner), conn=Depends(get_db)):
    if role not in EDITABLE_ROLES:
        raise HTTPException(status_code=400, detail="Owner permissions cannot be changed. Choose another role.")
    unknown = [p for p in body.permissions if p not in PERMISSION_KEYS]
    if unknown:
        raise HTTPException(status_code=400, detail="Unknown permission in the list.")
    bid = owner["business_id"]
    keys = sorted(set(body.permissions), key=PERMISSION_KEYS.index)
    conn.execute("DELETE FROM role_permissions WHERE business_id = ? AND role = ?", (bid, role))
    for key in keys:
        conn.execute("INSERT INTO role_permissions (business_id, role, permission) VALUES (?, ?, ?)", (bid, role, key))
    audit.log(conn, bid, owner["id"], owner["username"], "permissions_changed",
              f"Permissions for {role}: {', '.join(keys) or 'none'}", client_ip(request))
    return {"role": role, "permissions": keys}


# ---------- Audit log ----------

@router.get("/audit-logs")
def audit_logs(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
               owner=Depends(require_owner), conn=Depends(get_db)):
    rows = conn.execute(
        "SELECT id, username, action, details, ip_address, created_at FROM audit_logs "
        "WHERE business_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
        (owner["business_id"], limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]
