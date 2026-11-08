"""Makes the Next.js app build into plain files (frontend/out) so the backend can serve them.
Run once:  python scripts/enable_static_export.py"""
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "frontend"
for name in ("next.config.mjs", "next.config.js", "next.config.ts"):
    f = root / name
    if f.exists():
        break
else:
    f = root / "next.config.mjs"
    f.write_text('/** @type {import("next").NextConfig} */\nconst nextConfig = {\n  output: "export",\n  trailingSlash: true,\n  images: { unoptimized: true },\n};\nexport default nextConfig;\n')
    print("Created", f); sys.exit(0)

text = f.read_text()
if re.search(r'output\s*:\s*["\']export["\']', text):
    print("Already set up:", f); sys.exit(0)
new, n = re.subn(r"(nextConfig[^=]*=\s*\{)", r'\1\n  output: "export",\n  trailingSlash: true,\n  images: { unoptimized: true },', text, count=1)
if not n:
    print("Could not edit", f, "- add these three lines inside the config object by hand:\n  output: \"export\",\n  trailingSlash: true,\n  images: { unoptimized: true },")
    sys.exit(1)
f.write_text(new)
print("Updated", f)
