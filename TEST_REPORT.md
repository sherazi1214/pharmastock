# TEST REPORT - PharmaStock 2027 (Phase 7)

Run: `cd backend && python -m pytest tests -q` -> **40 passed** (16 Phase 5, 10 security, 14 acceptance).

## IMPORTANT - what these tests ran against
The Phase 1 (login, users, settings) and Phase 2 (products, import, GS1) source files were NOT available when Phases 5-7 were written.
The tests therefore run the REAL Phase 3, 4, 5, 6 and 7 code against small stand-ins for login and the products table (`backend/tests/stubs`).
So a PASS below means "the code written for Phases 3-7 behaves correctly", NOT "the finished product was proven end to end".
Please run the same tests and the checks in the last section on your full project.

## The 14 acceptance tests

| # | Test | Result | Notes |
|---|------|--------|-------|
| 1 | Import thousands of products | **NOT RUN** | Phase 2 import code was not available. Needs the Phase 2 5,000-row test run on the full project. |
| 2 | Known barcode loads the correct product | **PARTIAL PASS** | Tested through the POS scan lookup (plain barcode). The Phase 2 Scan Medicine screen and real GS1 parser were not tested. |
| 3 | Unknown barcode handled safely | **PARTIAL PASS** | POS scan: clear message, nothing saved. Phase 2 "add product / attach barcode" screen not tested. |
| 4 | Purchases increase stock correctly | PASS | 3 boxes of 100 = exactly 300 base units; movement written; supplier balance up, payment lowers it; invalid purchases change nothing. |
| 5 | Sales reduce stock correctly | PASS | Stock, sale items and movements agree; oversize sale refused, nothing changed. |
| 6 | Box, strip, tablet conversions accurate | PASS | 2 strips + 5 tablets = 25 tablets deducted, price 125. |
| 7 | Different batches keep own expiry | PASS | Two batches keep their dates; FEFO uses earliest first and splits across batches. |
| 8 | Expired / recalled stock cannot be sold | PASS | Expired, recalled and quarantined all refused; stock unchanged. |
| 9 | Credit sales update balances | PASS | Balance rises, limit enforced, payment lowers balance (oldest invoice first). |
| 10 | Offline sales synchronize without duplication | PASS (server side) | Same sale/purchase/payment replayed 4 times -> 1 record each. The browser queue (`offlineQueue.ts`) was NOT executed (no browser test). |
| 11 | Each business's data stays isolated | PASS | Two businesses: lists, 11 reports, dashboard, backups and log show nothing of the other; id-guessing on sales, returns, customers, payments, stock, batch status, suppliers all refused/no change. |
| 12 | Backup and restore work | PASS | Verified backup; restore returns exact earlier row counts and stock; safety copy made; wrong confirmation, non-owner, changed file, missing file refused; failed verification is never shown as backed up. |
| 13 | Reports reconcile with transactions | PASS | Sales, returns, stock value (= Stock page = dashboard), customer/supplier balances, estimated gross profit reconcile with raw records. |
| 14 | Person with basic computer knowledge can use it | **NOT TESTED** | Needs a real person and the real screens. The screens were not clicked through; the frontend was only syntax-checked (TypeScript parse), never compiled or opened in a browser in this work. |

## Security checks (all automated, all PASS on the stand-in base)
- Every `/api` endpoint depends on a login/permission check (`endpoints_without_login` returns `[]`); every endpoint refuses a call with no login.
- Owner-only actions refused for salesperson / stock operator (backup, restore, cloud settings, sync log, negative-stock switch, batch status, credit settings, stock adjustment).
- Bad input refused (negative / zero / fractional quantity, negative discount, bad type, empty lines, too-long notes, bad dates); nothing saved.
- SQL-injection style text in search / scan / report name / dates is harmless.
- Login rate limit (429 + Retry-After), request size limits (413; bigger for imports), safe headers (nosniff, no-frame, no-store for API).
- Backend serves the built frontend (SPA fallback) while `/api` keeps working.
- `scripts/check_secrets.py`: no hard-coded secrets, no database/key files in the project.

## NOT done / needs the full project
1. Run `python -m pytest tests -q` and the endpoint audit command in README on the real project (real login code, real Phase 2).
2. Phase 2 import test with 5,000 rows, GS1 tests and Phase 1 auth tests (written in their own phases) must still be run.
3. Login rate limit matches any `POST .../login`. Confirm that is your login URL.
4. The frontend must be built (`python scripts/enable_static_export.py`, then `start.bat`/`start.sh`). If `lib/api.ts` uses a fixed `http://localhost:8000` address, change it to a relative `/api` so the single-program setup works from any address.
5. Phase 1 token secret / password settings were not visible: confirm no secret is hard-coded there (`check_secrets.py` will tell you).
6. Usability pass (big buttons, wording on every screen) was not done: those screens were not available. Test 14 must be done with a real person.
7. Cloud sync: not built. Needs a real PostgreSQL server. The app says "Local only" and never "Synced".
8. Browser offline queue, and restore while several users are signed in, were not tested.
9. Request size limit applies to chunked uploads too, but file-type checks for imports are Phase 2's responsibility.
