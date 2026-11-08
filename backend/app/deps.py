from fastapi import Depends, Header, HTTPException

from .db import get_db
from .permissions import permissions_for
from .security import hash_token
from .util import parse, utcnow


def get_current_user(authorization: str | None = Header(default=None), conn=Depends(get_db)) -> dict:
    """Finds the logged-in user from the token. Every later query must use user['business_id']."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Please log in.")
    token = authorization[7:].strip()
    row = conn.execute(
        """
        SELECT s.id AS session_id, s.expires_at,
               u.id, u.business_id, u.username, u.full_name, u.role, u.is_active
        FROM sessions s
        JOIN users u ON u.id = s.user_id AND u.business_id = s.business_id
        WHERE s.token_hash = ?
        """,
        (hash_token(token),),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Your session has ended. Please log in again.")
    if parse(row["expires_at"]) <= utcnow():
        conn.execute("DELETE FROM sessions WHERE id = ? AND business_id = ?", (row["session_id"], row["business_id"]))
        conn.commit()
        raise HTTPException(status_code=401, detail="Your session has expired. Please log in again.")
    if not row["is_active"]:
        raise HTTPException(status_code=401, detail="This account is disabled.")
    user = dict(row)
    user["permissions"] = permissions_for(conn, user["business_id"], user["role"])
    return user


def require_permission(key: str):
    def dependency(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] != "owner" and key not in user["permissions"]:
            raise HTTPException(status_code=403, detail="You do not have permission to do this.")
        return user

    return dependency


def require_owner(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Only the owner can do this.")
    return user
