# PharmaStock 2027

Simple wholesale + retail pharmacy software. Works on one computer, no internet needed for daily work.

## Start it (one command)
You need Python 3.11+ and (first time only) Node.js 20+ with internet.

**Windows:** double-click `start.bat`
**Linux:** `./start.sh`

First time only, before the first start, run once: `python scripts/enable_static_export.py`
(this makes the screens build into plain files, so only ONE program runs).

The browser opens at http://127.0.0.1:8000. First run asks for business name, owner name, username and password. That screen never appears again.

## Where is my data?
In the SQLite database file created by the backend (see ADMIN_GUIDE.md). Backups go to the `backups` folder next to it.
Make a backup every day: Settings -> Backup and sync -> Make backup now.

## Guides
- `USER_GUIDE.md` - step-by-step for daily work (workflows A-E)
- `ADMIN_GUIDE.md` - users, backup, restore, updates
- `TEST_REPORT.md` - what was tested and what was NOT
- `docs/SYNC_DESIGN.md` - offline queue and cloud design (cloud is not built)

## For the person who installs it
- Check every API endpoint needs a login (run in `backend`):
  `python -c "from app.main import app; from app.security import endpoints_without_login as e; print(e(app))"` -> must print `[]`
- Run tests: `cd backend && pip install pytest httpx && python -m pytest tests -q`
- Look for secrets/leftover data: `python scripts/check_secrets.py`
- Build the clean final zip: `python scripts/make_final_zip.py`
- Settings you can change with environment variables are listed in `.env.example`.

## Problems
- "Python not found": install Python from python.org and tick "Add to PATH".
- Blank page / screens missing: delete the `frontend/out` folder and start again (it rebuilds).
- Port busy: set `PHARMASTOCK_PORT=8001` and start again.
- Forgot owner password: another Owner/Admin user can reset it in Settings -> Users.
# pharmastock
