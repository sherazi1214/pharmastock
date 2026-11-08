import json
from fastapi import Header, HTTPException, Depends
from .db import get_db
def get_current_user(x_user: int = Header(...), c=Depends(get_db)):
    r = c.execute("SELECT * FROM users WHERE id=?", (x_user,)).fetchone()
    if not r: raise HTTPException(401, "Not logged in")
    d = dict(r); d["permissions"] = json.loads(d["permissions"]); return d
def require_permission(perm):
    def dep(user=Depends(get_current_user)):
        if user["role"] != "owner" and perm not in user["permissions"]:
            raise HTTPException(403, "No permission")
        return user
    return dep
def require_owner(user=Depends(get_current_user)):
    if user["role"] != "owner": raise HTTPException(403, "Owner only")
    return user
