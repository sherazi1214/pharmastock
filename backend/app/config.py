import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def db_path() -> str:
    """Database file location. Can be changed with PHARMASTOCK_DB."""
    return os.environ.get("PHARMASTOCK_DB", str(BASE_DIR / "data" / "pharmastock.db"))


def bcrypt_rounds() -> int:
    return int(os.environ.get("PHARMASTOCK_BCRYPT_ROUNDS", "12"))


SESSION_HOURS = 12
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 5
