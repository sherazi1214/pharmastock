import os, sqlite3
def connect():
    c = sqlite3.connect(os.environ["TEST_DB"], check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c
def get_db():
    c = connect()
    try:
        yield c
        c.commit()
    finally:
        c.close()
def init_db():
    c = connect()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS businesses(id INTEGER PRIMARY KEY, name TEXT, address TEXT DEFAULT '', phone TEXT DEFAULT '',
      licence_number TEXT DEFAULT '', payment_methods TEXT DEFAULT '["Cash","Bank Transfer"]', near_expiry_days INTEGER DEFAULT 90);
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, business_id INTEGER, username TEXT, full_name TEXT, role TEXT, permissions TEXT);
    """)
    c.commit(); c.close()
