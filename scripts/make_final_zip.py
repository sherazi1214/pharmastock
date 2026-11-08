"""Builds pharmastock-final.zip from the project folder: clean, no test data, no secrets, no build junk.
Run:  python scripts/make_final_zip.py"""
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if subprocess.call([sys.executable, str(ROOT / "scripts" / "check_secrets.py")]) != 0:
    sys.exit("Fix the problems above first.")
SKIP = {"node_modules", ".next", ".venv", "__pycache__", ".git", ".pytest_cache", "backups"}
SKIP_SUFFIX = (".db", ".sqlite", ".sqlite3", ".key", ".pem", ".pyc", ".log", ".zip")
out = ROOT.parent / "pharmastock-final.zip"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT)
        if not p.is_file() or any(part in SKIP for part in rel.parts) or p.suffix.lower() in SKIP_SUFFIX or p.name == ".env":
            continue
        z.write(p, Path("pharmastock") / rel)
print("Created", out)
