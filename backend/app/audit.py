from .util import now_iso


def log(conn, business_id: int, user_id, username, action: str, details: str | None = None, ip: str | None = None) -> None:
    conn.execute(
        "INSERT INTO audit_logs (business_id, user_id, username, action, details, ip_address, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (business_id, user_id, username, action, details, ip, now_iso()),
    )
