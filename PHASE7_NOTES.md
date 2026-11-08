# Phase 7 update - Security, tests, start scripts, guides

## Apply
Unzip INSIDE the `pharmastock` folder (Phase 6 version), replace files, then run once: `python scripts/enable_static_export.py`. Start with `start.bat` (Windows) or `./start.sh` (Linux).

## New / changed
- NEW backend/app/security.py (login rate limit, size limits, headers, serves built frontend, endpoint audit), CHANGED backend/app/main.py (version 1.0.0; mounts frontend LAST)
- NEW backend/tests/test_security.py, test_acceptance.py; CHANGED backend/tests/conftest.py
- NEW start.bat, start.sh, .env.example, scripts/ (enable_static_export, check_secrets, make_final_zip)
- NEW/REPLACED README.md, USER_GUIDE.md, ADMIN_GUIDE.md, TEST_REPORT.md

## Final zip
This update zip is NOT the full project: the Phase 1-2 files were never in the files I received. On your complete project run `python scripts/make_final_zip.py` -> `pharmastock-final.zip` (clean: no database, keys, node_modules, backups).

## Honest status
40 automated tests pass against stand-ins for Phase 1/2. Tests 1 and 14 are not run, 2 and 3 partial. See TEST_REPORT.md.
