def ensure_schema(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INT NOT NULL, name TEXT NOT NULL, generic_name TEXT DEFAULT '',
      strength TEXT DEFAULT '', dosage_form TEXT DEFAULT '', barcode TEXT DEFAULT '', retail_price REAL DEFAULT 0, wholesale_price REAL DEFAULT 0,
      mrp REAL DEFAULT 0, purchase_price REAL DEFAULT 0, minimum_stock INT DEFAULT 0, status TEXT DEFAULT 'active', prescription_required INT DEFAULT 0);
    CREATE TABLE IF NOT EXISTS product_units(id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INT, product_id INT, name TEXT, factor INT);
    CREATE TABLE IF NOT EXISTS product_barcodes(id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INT, product_id INT, barcode TEXT);
    """)
def parse_gs1(raw):
    return {"is_gs1": False, "gtin": "", "batch": "", "expiry": ""}
