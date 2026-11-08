# Phase 5 update — Customers, payments, dashboard, reports

## How to apply
Unzip INSIDE your existing `pharmastock` folder (the Phase 4 one), choose "replace" for existing files, restart backend and frontend.
No `npm install` / `pip install` needed (Excel export uses `openpyxl`, already used by the Phase 2 import/export). New tables are created automatically.

## New / changed files
- NEW  backend/app/routes_phase5.py  (customer account + payments, dashboard, 11 reports, CSV/Excel export)
- CHANGED backend/app/main.py (adds the Phase 5 router)
- NEW  backend/tests/ (conftest.py, stubs/, test_phase5.py)
- NEW  frontend/lib/reportTools.ts (print + download)
- NEW/REPLACED frontend/app/(app)/dashboard/page.tsx, frontend/app/(app)/reports/page.tsx
- CHANGED frontend/app/(app)/customers/page.tsx (Account & payments panel)

## What it does
- Customers: "Account & payments" shows balance, credit left, unpaid invoices, payments, sales history.
- Receive payment: money goes to the OLDEST unpaid invoice first (paid + unpaid always equals total). Paying more than owed is refused. Same `client_uuid` is saved only once.
- Dashboard (real database numbers only): today's sales, today's purchases, stock value, low-stock count, near-expiry count, customers owe + shortcut buttons.
- Reports: daily sales, monthly sales, purchase history, current stock, low stock, near expiry, expired stock, best-selling, customer balances, supplier balances, estimated gross profit. Each one: Print, Save as Excel, Save as CSV.
- Estimated gross profit = sales - batch cost of goods sold - returns (+ cost of returned medicine put back in stock). Labelled "Estimated gross profit" with the note that net profit needs expenses, which are not tracked.

## Permissions (checked on the server)
- Reports page / list: `view_reports`
- Profit report: `view_profit`; customer + supplier balance reports and dashboard "Customers owe": `view_balances`
- Purchase history, stock value / cost columns, dashboard purchases + stock value: `view_purchase_price` (existing). Without it, cost columns are removed.
- The owner always has everything.
- !! `view_reports`, `view_profit`, `view_balances` must exist in your Phase 1 permissions list so the owner can tick them for other roles. I could not see that file (it was not in the update zip). If they are missing, add the three names there. Until then only the owner can open reports.
- Dashboard shortcuts use `manage_sales`, `manage_purchases`, `manage_products`, `view_stock` (guessed names for products; adjust in `dashboard()` if yours differ). "Scan Medicine" and "Add Product" link to /products.

## Rules used
- "Today" = the server computer's local day. Money in reports is rounded to 2 decimals.
- Low stock = active, non-expired quantity <= minimum stock (minimum must be above 0). Near expiry = active batches with stock expiring within the Settings days.
- Stock value uses the same rule as the Stock page (quantity x cost of one base unit), so both always agree.
- CSV/Excel cells that start with = + - @ get a leading ' so a spreadsheet never runs them as a formula.

## Tested
`cd backend && python -m pytest tests -q` -> 16 passed. The tests run the REAL Phase 3, 4 and 5 routes against simple stand-ins for login/products (the Phase 1/2 files were not in the update zip). Covers: oldest-first payments, duplicate payment, overpay refused, dashboard = raw records, reports reconcile (sales, returns, stock value, balances, profit), permission refusals, two-business isolation, CSV/Excel open correctly.

## Not done / not checked
- Frontend was only syntax-checked (TypeScript parse), not compiled or clicked through, because the base frontend is not in the zip.
- Not run against your real Phase 1/2 code: please run the pytest once and open Dashboard / Reports / Customers.
- Offline queue, backup/restore, security hardening belong to Phases 6-7.
