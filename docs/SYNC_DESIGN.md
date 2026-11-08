# PharmaStock 2027 - Sync design (cloud side NOT built)

## Status today
- Everything works on the local SQLite database. No internet is needed.
- Cloud sync is **not configured / not implemented**. The app says "Local only" and never says "Synced".
- Built now (local side): offline queue in the browser, duplicate protection on the server, `sync_log`, `sync_outbox`, encrypted cloud settings, verified backups.

## Offline queue (browser -> local server)
1. Save a sale / purchase / customer payment / supplier payment with a `client_uuid` (made once per form).
2. Server reachable -> saved at once. Not reachable -> stored in the browser queue (`localStorage`) and retried every 15 s and when the network returns.
3. `POST /api/sync/push` takes up to 50 items in order and answers per item: `saved`, `duplicate`, `error` (refused, e.g. not enough stock), `retry`.
4. `saved` and `duplicate` leave the queue. `error` stays visible for the user (retry or delete). A refusal is never retried silently.

## Duplicate protection
- Sales, sale returns, customer payments: `UNIQUE(business_id, client_uuid)` in their own table.
- Purchases and supplier payments: `client_requests(business_id, kind, client_uuid)` UNIQUE. The row is reserved first, the record is saved, then `ref_id` is filled. A failed save removes the reservation. A reservation older than 2 minutes with no record (crash) is taken over.
- Replaying the same item any number of times creates one record.

## Cloud design (for later)
- Each record that must reach the cloud gets a row in `sync_outbox(entity, record_id, sync_uuid, action, status)`. `sync_uuid` is the client_uuid and is the global record id.
- Cloud PostgreSQL has the same tables plus `business_id`; the cloud uses `UNIQUE(business_id, sync_uuid)` so a re-sent record is ignored.
- Direction: local -> cloud first (push in order of `sync_outbox.id`), then cloud -> local for other computers of the same business.
- Records are append-only (sales, purchases, payments, stock movements are never edited, only reversed by new records), so most records never conflict.
- Conflict rules for the few editable records:
  - Stock quantity: never copied; it is recalculated from stock movements.
  - Products, customers, suppliers: last change wins by `updated_at`; the losing version is kept in `sync_log`.
  - Batch status (blocked/recalled): the MOST RESTRICTIVE status wins (recalled > blocked > quarantine > active) until the owner changes it.
  - Prices: last change wins.
- Connection settings are stored in `cloud_settings`; the password is encrypted (Fernet, key file `cloud_secret.key` next to the database, never returned by the API). TLS is required (`sslmode=require` or `verify-full`).
- Status words: Local only / Pending / Error. "Synced" may only be shown when a cloud connection exists and `sync_outbox` has no `pending_cloud` rows.

## Backup
- Online SQLite backup -> copy is opened read-only -> `PRAGMA integrity_check` must return `ok` -> all tables must exist -> record counts compared with the live database before/after the copy -> SHA-256 saved -> only then `status='verified'`.
- Restore (owner only): file checksum re-checked, integrity re-checked, a verified safety backup of today's data is made first (restore stops if that fails), then the backup replaces the data. Backup list is kept.
