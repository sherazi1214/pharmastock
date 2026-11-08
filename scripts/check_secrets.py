"""Looks for passwords/keys written inside the code, and for files that must never be shipped.
Run:  python scripts/check_secrets.py        (exit code 1 = problem found)"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"node_modules", ".next", "out", ".venv", "__pycache__", ".git", "tests"}
BAD_FILES = (".db", ".sqlite", ".sqlite3", ".key", ".pem", ".env")
PATTERN = re.compile(r"""(?ix)\b(secret|password|passwd|token|api[_-]?key|private[_-]?key)\w*\s*[:=]\s*["'][^"'\s]{8,}["']""")
ALLOWED = ("example", "placeholder", "changeme", "your_", "<")

problems = []
for p in ROOT.rglob("*"):
    if not p.is_file() or any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts):
        continue
    if p.name == ".env.example":
        continue
    if p.suffix.lower() in BAD_FILES or p.name == ".env":
        problems.append(f"{p.relative_to(ROOT)}: file must not be shipped (data or secret)")
        continue
    if p.suffix.lower() not in (".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".sh", ".bat", ".md", ".yml", ".yaml", ".toml"):
        continue
    try:
        lines = p.read_text(errors="ignore").splitlines()
    except OSError:
        continue
    for i, line in enumerate(lines, 1):
        m = PATTERN.search(line)
        if m and not any(a in line.lower() for a in ALLOWED):
            problems.append(f"{p.relative_to(ROOT)}:{i}: looks like a hard-coded secret -> {line.strip()[:80]}")
for x in problems:
    print("PROBLEM", x)
print("No hard-coded secrets or leftover data files found." if not problems else f"{len(problems)} problem(s) found.")
sys.exit(1 if problems else 0)
