# Phase 6 update - Offline queue, sync, verified backup & restore

## Apply
Unzip INSIDE the `pharmastock` folder (Phase 5 version), replace files, then:
`pip install cryptography` (only needed for saving cloud settings), restart backend + frontend.

## New / changed
- NEW backend/app/routes_phase6.py, CHANGED backend/app/main.py
- NEW frontend/lib/offlineQueue.ts, components/SyncStatus.tsx, components/settings/BackupPanel.tsx, app/(app)/settings/backup/page.tsx
- CHANGED components/sales/Pos.tsx (sale goes through the queue), app/(app)/customers/page.tsx (payment goes through the queue), app/(app)/sales/page.tsx and app/(app)/dashboard/page.tsx (status badge)
- NEW docs/SYNC_DESIGN.md

## Do these 2 things by hand (those files were not in the zip)
1. Settings page: add `<Link href="/settings/backup">Backup and sync</Link>` (a big button) - the page is /settings/backup.
2. Purchase form + supplier payment form: replace the direct `api(...)` save with
   `submitOrQueue("purchase", body, uuid)` / `submitOrQueue("supplier_payment", {supplier_id, ...}, uuid)` from `@/lib/offlineQueue`.
   (`uuid` = `newId()` made once per form and reused if the save failed.) Until then purchases are NOT queued offline.
3. Optional: put `<SyncStatus />` in the layout header so it shows on every page.

## Rules
- Backup is "verified" only after: integrity_check = ok, all tables present, record counts match, checksum saved. Otherwise it shows FAILED and the file is deleted.
- Restore: owner only, must type RESTORE, safety backup first (stops if it fails), checksum re-checked.
- Cloud: status is always "not configured" or "settings saved, not connected". Nothing is ever sent to a cloud.
- Backup folder: `backups/` next to the database file, or set env `PHARMASTOCK_BACKUP_DIR`.

## Not done / not checked
- NO tests were written or run for this phase (as requested). Python syntax compiled and TypeScript syntax parsed only.
- Restore copies the backup over the live database inside the running server: restart the backend after a restore, and users may need to sign in again.
- Queue lives in the browser of that computer; if a different user signs in there before it is sent, the records are saved under the user who sends them.
- Network-error detection looks at the error text from `lib/api.ts` (not in the zip); if your api() hides it, adjust `isNetworkError`.
- A backup file contains ALL data of the database (all businesses); keep it safe.
