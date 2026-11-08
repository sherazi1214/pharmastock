# PharmaStock - Admin Guide

## Users and roles (Settings -> Users)
- Owner/Admin: everything. Salesperson: sales and customers. Stock/Purchase Operator: purchases and stock (cannot see profit).
- The owner can change what each role may do (permissions list). Permissions needed for Phase 5-6 screens: `view_reports`, `view_profit`, `view_balances`, `view_purchase_price`, `give_discount`, `manage_sales`, `manage_purchases`, `manage_customers`, `manage_suppliers`, `adjust_stock`.
- Add a user, disable a user (do not share logins), reset a password. After 5 wrong passwords an account is locked for 5 minutes. More than 10 login tries per minute from one computer are blocked.
- Every login, user change and settings change is saved in the audit log.

## Backup (do it every day)
Settings -> Backup and sync -> Make backup now. The copy is checked (integrity check, tables, record counts) and only then called "Backed up and verified". FAILED = no backup exists.
Files are in the `backups` folder next to the database (or `PHARMASTOCK_BACKUP_DIR`). Copy them off the computer (USB / another PC). A backup file holds ALL data - keep it safe.

## Restore (owner only)
1. Close other open PharmaStock windows.
2. Settings -> Backup and sync -> Restore next to the backup -> type RESTORE.
3. The program first makes a "Safety copy" of today's data. If that fails, nothing is restored.
4. Restart PharmaStock and sign in again.
A backup file that was changed after it was made is refused.

## Moving to a new computer
Copy the whole PharmaStock folder's database file and `backups` folder, install the new copy, then restore the newest backup.

## Updating
Stop the program, unzip the new files over the old folder, start again. Database tables update by themselves. Make a backup before updating.

## Security checklist
- Run only on a trusted computer; keep Windows/Linux updated; use strong owner password.
- The program listens only on this computer (127.0.0.1). Do not change PHARMASTOCK_HOST unless you also protect the network.
- Run `python scripts/check_secrets.py` before giving the folder to anyone.
- Cloud sync is NOT available yet. Nothing leaves the computer.
