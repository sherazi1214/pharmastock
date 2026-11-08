from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def now_iso() -> str:
    return iso(utcnow())


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)
