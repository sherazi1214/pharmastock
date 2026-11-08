"""PharmaStock 2027 - Phase 6: offline queue receiver (duplicate-safe), sync status, verified backup, safe restore,
local side of cloud sync (outbox + encrypted cloud settings). The cloud server itself is NOT built: status says so.
"""
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from .audit import log as audit_log
from .db import get_db
from .deps import require_owner, require_permission
from .routes_phase3 import PaymentIn, PurchaseIn, create_purchase, supplier_payment
from .routes_phase4 import SaleIn, create_sale, ensure_sales_schema
from .routes_phase5 import CustomerPaymentIn, ensure_p5_schema, has_perm, receive_customer_payment

router = APIRouter(prefix="/api", tags=["sync-backup"])

try:  # any logged-in user
    from .deps import get_current_user as current_user
except ImportError:  # pragma: no cover
    from .deps import current_user  # type: ignore


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ schema
def ensure_p6_schema(c) -> None:
    ensure_p5_schema(c)
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS client_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER NOT NULL, kind TEXT NOT NULL,
            client_uuid TEXT NOT NULL, ref_id INTEGER, created_at TEXT NOT NULL,
            UNIQUE(business_id, kind, client_uuid));
        CREATE TABLE IF NOT EXISTS sync_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER NOT NULL, kind TEXT NOT NULL,
            client_uuid TEXT NOT NULL, result TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
            created_by INTEGER, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sync_outbox(
            id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER NOT NULL, entity TEXT NOT NULL,
            record_id INTEGER NOT NULL, sync_uuid TEXT NOT NULL, action TEXT NOT NULL DEFAULT 'create',
            status TEXT NOT NULL DEFAULT 'pending_cloud', created_at TEXT NOT NULL, sent_at TEXT,
            UNIQUE(business_id, entity, record_id, action));
        CREATE TABLE IF NOT EXISTS cloud_settings(
            business_id INTEGER PRIMARY KEY, host TEXT NOT NULL, port INTEGER NOT NULL, dbname TEXT NOT NULL,
            username TEXT NOT NULL, password_enc TEXT NOT NULL, sslmode TEXT NOT NULL DEFAULT 'require', updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS backups(
            id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER NOT NULL, filename TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'manual', status TEXT NOT NULL, size_bytes INTEGER NOT NULL DEFAULT 0,
            sha256 TEXT NOT NULL DEFAULT '', integrity TEXT NOT NULL DEFAULT '', counts_json TEXT NOT NULL DEFAULT '{}',
            message TEXT NOT NULL DEFAULT '', created_by INTEGER, created_at TEXT NOT NULL, verified_at TEXT);
        CREATE INDEX IF NOT EXISTS idx_backups_business ON backups(business_id, id);
        CREATE INDEX IF NOT EXISTS idx_sync_log_business ON sync_log(business_id, id);
        """)
    c.commit()


# ------------------------------------------------------------------ duplicate-safe wrapper
def run_once(c, b: int, kind: str, uuid: str, fn) -> dict:
    """Runs fn() at most once per (business, kind, client_uuid). Used for purchases and supplier payments."""
    for _ in range(2):
        try:
            c.execute("INSERT INTO client_requests(business_id,kind,client_uuid,created_at) VALUES(?,?,?,?)", (b, kind, uuid, stamp()))
            c.commit()
            break
        except sqlite3.IntegrityError:
            c.rollback()
            row = c.execute("SELECT ref_id, created_at FROM client_requests WHERE business_id=? AND kind=? AND client_uuid=?", (b, kind, uuid)).fetchone()
            if row and row["ref_id"] is not None:
                return {"id": row["ref_id"], "duplicate": True, "message": "Already saved. No second record was created."}
            old = row and datetime.fromisoformat(row["created_at"]) < datetime.now(timezone.utc) - timedelta(minutes=2)
            if not old:
                raise HTTPException(409, "This item is being saved right now. Please wait a moment.")
            c.execute("DELETE FROM client_requests WHERE business_id=? AND kind=? AND client_uuid=? AND ref_id IS NULL", (b, kind, uuid))
            c.commit()  # stale reservation from a crashed try: take it over
    else:
        raise HTTPException(409, "Could not reserve this item. Please try again.")
    try:
        result = fn()
    except Exception:
        c.rollback()
        c.execute("DELETE FROM client_requests WHERE business_id=? AND kind=? AND client_uuid=? AND ref_id IS NULL", (b, kind, uuid))
        c.commit()
        raise
    c.execute("UPDATE client_requests SET ref_id=? WHERE business_id=? AND kind=? AND client_uuid=?", (result.get("id"), b, kind, uuid))
    c.commit()
    return {**result, "duplicate": False}


# ------------------------------------------------------------------ queue receiver
class PushItem(BaseModel):
    client_uuid: str = Field(min_length=8, max_length=64)
    kind: Literal["sale", "purchase", "customer_payment", "supplier_payment"]
    payload: dict[str, Any]


class PushIn(BaseModel):
    items: list[PushItem] = Field(min_length=1, max_length=50)


NEEDS = {"sale": "manage_sales", "purchase": "manage_purchases", "customer_payment": "manage_customers", "supplier_payment": "manage_suppliers"}
ENTITY = {"sale": "sales", "purchase": "purchases", "customer_payment": "customer_payments", "supplier_payment": "supplier_payments"}


def _process(item: PushItem, user: dict, c) -> dict:
    b = user["business_id"]
    if not has_perm(user, NEEDS[item.kind]):
        raise HTTPException(403, "You do not have permission to save this kind of record.")
    body = {**item.payload, "client_uuid": item.client_uuid} if item.kind != "supplier_payment" and item.kind != "purchase" else item.payload
    resp = Response()
    try:
        if item.kind == "sale":
            res = create_sale(SaleIn(**body), resp, user, c)
        elif item.kind == "customer_payment":
            cid = int(item.payload["customer_id"])
            res = receive_customer_payment(cid, CustomerPaymentIn(**{k: v for k, v in body.items() if k != "customer_id"}), resp, user, c)
        elif item.kind == "purchase":
            data = PurchaseIn(**{k: v for k, v in body.items() if k != "client_uuid"})
            res = run_once(c, b, "purchase", item.client_uuid, lambda: create_purchase(data, user, c))
        else:
            sid = int(item.payload["supplier_id"])
            data = PaymentIn(**{k: v for k, v in body.items() if k not in ("supplier_id", "client_uuid")})
            res = run_once(c, b, "supplier_payment", item.client_uuid, lambda: supplier_payment(sid, data, user, c))
    except ValueError as e:  # pydantic validation of the queued payload
        raise HTTPException(422, str(e))
    c.rollback()
    return res


@router.post("/sync/push")
def sync_push(x: PushIn, user=Depends(current_user), c=Depends(get_db)):
    """Receives items saved offline in the browser, IN ORDER. Each item is saved once; replays are reported as duplicate."""
    ensure_p6_schema(c)
    b = user["business_id"]
    out = []
    for it in x.items:
        try:
            res = _process(it, user, c)
            state = "duplicate" if res.get("duplicate") else "saved"
            rid = res.get("id")
            if rid is not None:
                c.execute("INSERT OR IGNORE INTO sync_outbox(business_id,entity,record_id,sync_uuid,action,created_at) VALUES(?,?,?,?,?,?)",
                          (b, ENTITY[it.kind], int(rid), it.client_uuid, "create", stamp()))
            out.append({"client_uuid": it.client_uuid, "status": state, "id": rid, "message": res.get("message", ""),
                        "invoice_number": res.get("invoice_number")})
            c.execute("INSERT INTO sync_log(business_id,kind,client_uuid,result,detail,created_by,created_at) VALUES(?,?,?,?,?,?,?)",
                      (b, it.kind, it.client_uuid, state, str(res.get("message", ""))[:300], user["id"], stamp()))
        except HTTPException as e:
            c.rollback()
            detail = e.detail if isinstance(e.detail, str) else json.dumps(e.detail)
            retry = e.status_code == 409 and "right now" in detail  # another try is still running: ask the browser to retry
            out.append({"client_uuid": it.client_uuid, "status": "retry" if retry else "error", "message": detail})
            c.execute("INSERT INTO sync_log(business_id,kind,client_uuid,result,detail,created_by,created_at) VALUES(?,?,?,?,?,?,?)",
                      (b, it.kind, it.client_uuid, "retry" if retry else "error", detail[:300], user["id"], stamp()))
        c.commit()
    return {"results": out}


# ------------------------------------------------------------------ paths and helpers for backup
def db_file(c) -> Path:
    row = c.execute("PRAGMA database_list").fetchone()
    path = row["file"] if row else ""
    if not path:
        raise HTTPException(500, "The database is not a file, so it cannot be backed up.")
    return Path(path)


def backup_dir(c) -> Path:
    d = Path(os.environ.get("PHARMASTOCK_BACKUP_DIR", "")) if os.environ.get("PHARMASTOCK_BACKUP_DIR") else db_file(c).parent / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def table_names(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def count_rows(conn, tables: list[str]) -> dict[str, int]:
    return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_file(path: Path, live_tables: list[str] | None = None, before: dict | None = None, after: dict | None = None) -> tuple[bool, str, dict]:
    """Integrity check + table list + record counts. Returns (ok, message, counts)."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as e:
        return False, f"Cannot open the backup file: {e}", {}
    try:
        res = conn.execute("PRAGMA integrity_check").fetchall()
        if [r[0] for r in res] != ["ok"]:
            return False, "Integrity check failed: " + "; ".join(str(r[0]) for r in res[:3]), {}
        tables = table_names(conn)
        for need in ("businesses", "users"):
            if need not in tables:
                return False, f"The file is not a PharmaStock database (table '{need}' is missing).", {}
        if live_tables is not None and set(live_tables) - set(tables):
            return False, "Backup is missing tables: " + ", ".join(sorted(set(live_tables) - set(tables))), {}
        counts = count_rows(conn, tables)
        if before is not None and after is not None:
            for t, n in counts.items():
                lo, hi = before.get(t), after.get(t)
                if lo is not None and hi is not None and not (min(lo, hi) <= n <= max(lo, hi)):
                    return False, f"Record count of '{t}' does not match the live database ({n} in backup, {lo}-{hi} live).", counts
        return True, "Integrity check passed and record counts match.", counts
    except sqlite3.Error as e:
        return False, f"Verification failed: {e}", {}
    finally:
        conn.close()


def make_backup(c, user: dict, kind: str) -> dict:
    """Copy -> verify -> only then mark 'verified'. Any problem marks it 'failed' (never shows as backed up)."""
    b = user["business_id"]
    src = db_file(c)
    c.commit()
    name = f"pharmastock-{kind}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.db"
    target = backup_dir(c) / name
    bid = c.execute("INSERT INTO backups(business_id,filename,kind,status,created_by,created_at) VALUES(?,?,?,?,?,?)",
                    (b, name, kind, "creating", user["id"], stamp())).lastrowid
    c.commit()
    ok, msg, counts, size, digest = False, "", {}, 0, ""
    try:
        live = table_names(c)
        before = count_rows(c, live)
        dest = sqlite3.connect(target)
        try:
            c.backup(dest)  # SQLite online backup: a consistent copy even while the app is running
        finally:
            dest.close()
        after = count_rows(c, live)
        ok, msg, counts = verify_file(target, live, before, after)
        size = target.stat().st_size if target.exists() else 0
        digest = sha256_of(target) if ok else ""
    except Exception as e:  # any failure = not backed up
        ok, msg = False, f"Backup failed: {e}"
    if not ok and target.exists():
        try:
            target.unlink()
        except OSError:
            pass
    c.execute("UPDATE backups SET status=?, size_bytes=?, sha256=?, integrity=?, counts_json=?, message=?, verified_at=? WHERE id=? AND business_id=?",
              ("verified" if ok else "failed", size, digest, "ok" if ok else "failed", json.dumps(counts), msg, stamp() if ok else None, bid, b))
    audit_log(c, b, user["id"], user["username"], "backup_" + ("verified" if ok else "failed"), f"{name} {msg}"[:300])
    c.commit()
    return backup_row(c, b, bid)


def backup_row(c, b: int, bid: int) -> dict:
    r = c.execute("SELECT * FROM backups WHERE id=? AND business_id=?", (bid, b)).fetchone()
    d = dict(r)
    d["counts"] = json.loads(d.pop("counts_json") or "{}")
    d["total_records"] = sum(d["counts"].values())
    d["exists"] = (backup_dir_for(c) / d["filename"]).exists() if d["status"] == "verified" else False
    d["label"] = {"verified": "Backed up and verified", "failed": "Backup FAILED", "creating": "Backup not finished"}.get(d["status"], d["status"])
    return d


def backup_dir_for(c) -> Path:
    return backup_dir(c)


# ------------------------------------------------------------------ backup routes
@router.get("/backups")
def list_backups(user=Depends(require_owner), c=Depends(get_db)):
    ensure_p6_schema(c)
    b = user["business_id"]
    ids = [r["id"] for r in c.execute("SELECT id FROM backups WHERE business_id=? ORDER BY id DESC LIMIT 100", (b,))]
    return {"items": [backup_row(c, b, i) for i in ids], "folder": str(backup_dir(c))}


@router.post("/backups", status_code=201)
def create_backup(user=Depends(require_owner), c=Depends(get_db)):
    ensure_p6_schema(c)
    return make_backup(c, user, "manual")


class RestoreIn(BaseModel):
    confirm: str = Field(min_length=1, max_length=20)


@router.post("/backups/{backup_id}/restore")
def restore_backup(backup_id: int, x: RestoreIn, user=Depends(require_owner), c=Depends(get_db)):
    """Owner only. 1) check the file again  2) take a verified safety backup of today's data  3) copy the backup over the live data."""
    ensure_p6_schema(c)
    b = user["business_id"]
    if x.confirm.strip().upper() != "RESTORE":
        raise HTTPException(400, "Type RESTORE to confirm.")
    row = c.execute("SELECT * FROM backups WHERE id=? AND business_id=?", (backup_id, b)).fetchone()
    if not row:
        raise HTTPException(404, "Backup not found.")
    if row["status"] != "verified":
        raise HTTPException(400, "Only a verified backup can be restored.")
    path = backup_dir(c) / row["filename"]
    if not path.exists():
        raise HTTPException(404, "The backup file is missing from the backup folder.")
    if sha256_of(path) != row["sha256"]:
        raise HTTPException(400, "The backup file was changed after it was made. It will not be restored.")
    ok, msg, _ = verify_file(path)
    if not ok:
        raise HTTPException(400, msg)

    safety = make_backup(c, user, "before-restore")
    if safety["status"] != "verified":
        raise HTTPException(500, "Restore stopped: the safety backup of your current data failed. Nothing was changed. " + safety["message"])

    kept = [dict(r) for r in c.execute("SELECT * FROM backups ORDER BY id")]  # the restored file knows nothing about newer backups
    c.commit()
    try:
        src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            src.backup(c)
        finally:
            src.close()
    except sqlite3.Error as e:
        raise HTTPException(500, f"Restore failed ({e}). Your safety backup '{safety['filename']}' is in the backup folder.")
    ensure_p6_schema(c)
    have = {r["filename"] for r in c.execute("SELECT filename FROM backups")}
    cols = [r[1] for r in c.execute("PRAGMA table_info(backups)") if r[1] != "id"]
    for k in kept:
        if k["filename"] not in have:
            c.execute(f"INSERT INTO backups({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [k.get(col) for col in cols])
    audit_log(c, b, user["id"], user["username"], "backup_restored", f"restored {row['filename']}; safety copy {safety['filename']}")
    c.commit()
    return {"ok": True, "message": "Data restored. Please sign in again if asked.", "safety_backup": safety["filename"]}


# ------------------------------------------------------------------ cloud settings (local side only)
def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise HTTPException(400, "Cloud settings cannot be saved: the 'cryptography' package is not installed (pip install cryptography).")
    return Fernet


def _key(c) -> bytes:
    Fernet = _fernet()
    p = db_file(c).parent / "cloud_secret.key"
    if not p.exists():
        p.write_bytes(Fernet.generate_key())
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    return p.read_bytes()


class CloudIn(BaseModel):
    host: str = Field(min_length=1, max_length=200)
    port: int = Field(default=5432, ge=1, le=65535)
    dbname: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)
    sslmode: Literal["require", "verify-full"] = "require"


@router.put("/sync/cloud-settings")
def save_cloud(x: CloudIn, user=Depends(require_owner), c=Depends(get_db)):
    ensure_p6_schema(c)
    b = user["business_id"]
    Fernet = _fernet()
    enc = Fernet(_key(c)).encrypt(x.password.encode()).decode()
    c.execute("INSERT INTO cloud_settings(business_id,host,port,dbname,username,password_enc,sslmode,updated_at) VALUES(?,?,?,?,?,?,?,?) "
              "ON CONFLICT(business_id) DO UPDATE SET host=excluded.host,port=excluded.port,dbname=excluded.dbname,username=excluded.username,"
              "password_enc=excluded.password_enc,sslmode=excluded.sslmode,updated_at=excluded.updated_at",
              (b, x.host.strip(), x.port, x.dbname.strip(), x.username.strip(), enc, x.sslmode, stamp()))
    audit_log(c, b, user["id"], user["username"], "cloud_settings_saved", f"{x.host}:{x.port}/{x.dbname}")
    c.commit()
    return {"ok": True, "message": "Cloud settings saved (password stored encrypted). Cloud sync is still NOT running: no cloud server connection is built yet."}


@router.delete("/sync/cloud-settings")
def delete_cloud(user=Depends(require_owner), c=Depends(get_db)):
    ensure_p6_schema(c)
    c.execute("DELETE FROM cloud_settings WHERE business_id=?", (user["business_id"],))
    audit_log(c, user["business_id"], user["id"], user["username"], "cloud_settings_removed", "")
    c.commit()
    return {"ok": True}


# ------------------------------------------------------------------ status
@router.get("/sync/status")
def sync_status(user=Depends(current_user), c=Depends(get_db)):
    ensure_p6_schema(c)
    b = user["business_id"]
    cs = c.execute("SELECT host,port,dbname,username,sslmode,updated_at FROM cloud_settings WHERE business_id=?", (b,)).fetchone()
    cloud = {"configured": False, "state": "not_configured", "message": "Cloud sync is not configured. All data is saved on this computer only."}
    if cs:
        cloud = {"configured": True, "state": "settings_saved_not_connected", "host": cs["host"], "port": cs["port"], "dbname": cs["dbname"],
                 "message": "Cloud settings are saved, but the cloud connection is not built yet. Nothing has been sent to the cloud."}
    outbox = c.execute("SELECT COUNT(*) n FROM sync_outbox WHERE business_id=? AND status='pending_cloud'", (b,)).fetchone()["n"]
    last = c.execute("SELECT verified_at, filename FROM backups WHERE business_id=? AND status='verified' ORDER BY id DESC LIMIT 1", (b,)).fetchone()
    hours = None
    if last and last["verified_at"]:
        hours = round((datetime.now(timezone.utc) - datetime.fromisoformat(last["verified_at"])).total_seconds() / 3600, 1)
    errors = c.execute("SELECT COUNT(*) n FROM sync_log WHERE business_id=? AND result='error' AND created_at>=?",
                       (b, (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds"))).fetchone()["n"]
    return {"server": "ok", "cloud": cloud, "waiting_for_cloud": outbox, "recent_errors": errors,
            "last_verified_backup": last["verified_at"] if last else None, "hours_since_backup": hours,
            "backup_warning": None if hours is not None and hours < 48 else "No verified backup in the last 2 days." if last else "No verified backup yet."}


@router.get("/sync/log")
def sync_log(user=Depends(require_owner), c=Depends(get_db)):
    ensure_p6_schema(c)
    rows = c.execute("SELECT kind,client_uuid,result,detail,created_at FROM sync_log WHERE business_id=? ORDER BY id DESC LIMIT 200", (user["business_id"],)).fetchall()
    return {"items": [dict(r) for r in rows]}
