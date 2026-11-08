PERMISSIONS = [
    ("view_dashboard", "Open the Dashboard"),
    ("view_products", "See products"),
    ("manage_products", "Add, edit and import products"),
    ("view_purchase_price", "See purchase price and cost"),
    ("manage_purchases", "Enter purchases"),
    ("manage_sales", "Make sales"),
    ("give_discount", "Give discounts on sales"),
    ("view_stock", "See stock"),
    ("adjust_stock", "Adjust stock, damaged goods, supplier returns"),
    ("manage_suppliers", "Manage suppliers and their payments"),
    ("manage_customers", "Manage customers and their payments"),
    ("view_reports", "See reports"),
    ("view_profit", "See profit, cost and balance reports"),
]
PERMISSION_KEYS = [key for key, _ in PERMISSIONS]

EDITABLE_ROLES = ["salesperson", "stock_operator"]
ROLES = ["owner", *EDITABLE_ROLES]

# Owner always has every permission (and is the only one who can open Settings / Users).
DEFAULT_ROLE_PERMISSIONS = {
    "salesperson": [
        "view_dashboard", "view_products", "manage_sales", "view_stock", "manage_customers",
    ],
    "stock_operator": [
        "view_dashboard", "view_products", "manage_products", "view_purchase_price",
        "manage_purchases", "view_stock", "adjust_stock", "manage_suppliers",
    ],
}


def seed_role_permissions(conn, business_id: int) -> None:
    for role, keys in DEFAULT_ROLE_PERMISSIONS.items():
        for key in keys:
            conn.execute(
                "INSERT INTO role_permissions (business_id, role, permission) VALUES (?, ?, ?)",
                (business_id, role, key),
            )


def permissions_for(conn, business_id: int, role: str) -> list[str]:
    if role == "owner":
        return list(PERMISSION_KEYS)
    rows = conn.execute(
        "SELECT permission FROM role_permissions WHERE business_id = ? AND role = ?",
        (business_id, role),
    ).fetchall()
    granted = {r["permission"] for r in rows}
    return [k for k in PERMISSION_KEYS if k in granted]
