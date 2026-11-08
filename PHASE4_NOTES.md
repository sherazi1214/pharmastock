# Phase 4 update — Retail & Wholesale Sales (POS)

## How to apply
Unzip this file INSIDE your existing `pharmastock` project folder (the one from phase 3) and choose "replace" for files that already exist.
Then restart the backend and the frontend (README of Phase 3 has the commands). No `npm install` or `pip install` is needed. The new database tables are created automatically on first use.

## New / changed files
- NEW  backend/app/routes_phase4.py  (sales, FEFO, returns, customers, customer prices)
- NEW  frontend/components/sales/Pos.tsx, frontend/components/sales/History.tsx, frontend/lib/printSale.ts
- CHANGED frontend/app/(app)/sales/page.tsx, frontend/app/(app)/customers/page.tsx
- CHANGED backend/app/main.py (adds the Phase 4 router)
- CHANGED backend/app/routes_phase3.py (stock value fix, see below)

## What it does
- Sales screen with two big buttons: Retail Sale and Wholesale Sale. Scan (plain barcode or GS1) or search by name.
- Quantity in any unit; everything is converted to base units (2 strips + 5 tablets of a 10x10 box = 25 tablets).
- FEFO: earliest-expiry sellable batch first, split across batches when needed.
- Expired, recalled, blocked and quarantine batches are never sold.
- Not enough stock = sale refused with a clear message. Owner can switch on an exception (negative stock) on the Sales page.
- Discount (per line and whole invoice) only for users with the "give discount" permission. Price above MRP is refused.
- Wholesale uses the customer's special price if one exists, else the wholesale price.
- Payment methods come from Settings. Paying less than the total = credit sale: customer must have credit allowed and stay inside the credit limit (only the owner can set credit).
- A4 invoice and small receipt printing. Past sales list with search.
- Sale returns: put back into the same batch, or write off. Reason is required. Returns reduce the customer's balance first, then the rest is money to give back.
- Every sale and return has a `client_uuid`: sending the same one again never creates a second sale.
- Every stock change is saved in stock movements (kinds: sale, sale_return, return_write_off).
- Customers (basic): add/edit, type, credit, special prices. The full customer accounts and payments are Phase 5.

## Price rule (please read)
Product prices (retail, wholesale, MRP) and customer special prices are treated as the price of the BIGGEST unit (the pack/box).
Smaller units are worked out from it: price x unit size / biggest unit size. Example: box of 100 tablets, retail 500 per box -> 1 strip of 10 = 50.00.
If your prices are per tablet, give the product only one unit (Tablet, factor 1) — then the price is per tablet.

## Fix included for Phase 3
Stock value on the Stock page multiplied quantity (in base units) by the cost of a whole purchase unit, so value could be too high.
It now uses cost per base unit (cost of the purchase line divided by its unit size).

## Not done / not checked
- No automated tests were written or run for this phase, as requested. Only a Python syntax check was done. Frontend was not compiled here.
- Offline queue, backups, reports, customer payments and dashboard numbers belong to later phases.
