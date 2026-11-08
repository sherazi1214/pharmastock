import sqlite3
from pathlib import Path

from .config import db_path

# Each item is one migration. Never edit an old one; add a new one at the end.
MIGRATIONS = [
    """
    CREATE TABLE businesses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        owner_name TEXT NOT NULL,
        address TEXT NOT NULL DEFAULT '',
        phone TEXT NOT NULL DEFAULT '',
        licence_number TEXT NOT NULL DEFAULT '',
        payment_methods TEXT NOT NULL DEFAULT '["Cash","Bank Transfer"]',
        near_expiry_days INTEGER NOT NULL DEFAULT 90,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER NOT NULL REFERENCES businesses(id),
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        full_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('owner','salesperson','stock_operator')),
        is_active INTEGER NOT NULL DEFAULT 1,
        failed_attempts INTEGER NOT NULL DEFAULT 0,
        locked_until TEXT,
        last_login_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_users_business ON users(business_id);

    CREATE TABLE role_permissions (
        business_id INTEGER NOT NULL REFERENCES businesses(id),
        role TEXT NOT NULL,
        permission TEXT NOT NULL,
        PRIMARY KEY (business_id, role, permission)
    );

    CREATE TABLE sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER NOT NULL REFERENCES businesses(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        token_hash TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    );
    CREATE INDEX idx_sessions_user ON sessions(business_id, user_id);

    CREATE TABLE audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER NOT NULL REFERENCES businesses(id),
        user_id INTEGER,
        username TEXT,
        action TEXT NOT NULL,
        details TEXT,
        ip_address TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_audit_business ON audit_logs(business_id, id);
    """,
]


def connect() -> sqlite3.Connection:
    path = Path(db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    """Create the database and apply any missing migrations."""
    conn = connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        conn.commit()
        current = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()["v"] or 0
        for number, sql in enumerate(MIGRATIONS, start=1):
            if number > current:
                conn.executescript(sql)
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (number,))
                conn.commit()
    finally:
        conn.close()


def get_db():
    """One connection per request. Saved when the request finishes without error."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
