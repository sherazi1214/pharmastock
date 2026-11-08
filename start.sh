#!/usr/bin/env bash
# PharmaStock 2027 - one-command start (Linux). Runs ONE program: backend + built frontend on http://127.0.0.1:8000
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then python3 -m venv .venv; fi
. .venv/bin/activate

if [ -f backend/requirements.txt ]; then pip install -q -r backend/requirements.txt; else pip install -q fastapi "uvicorn[standard]" bcrypt openpyxl python-multipart; fi
pip install -q cryptography

if [ ! -f frontend/out/index.html ]; then
  echo "Building the screens (first time only, needs internet and Node.js)..."
  (cd frontend && npm install && npm run build)
fi

HOST="${PHARMASTOCK_HOST:-127.0.0.1}"
PORT="${PHARMASTOCK_PORT:-8000}"
echo "PharmaStock is starting. Open http://127.0.0.1:${PORT} in your browser. Press Ctrl+C to stop."
cd backend
exec uvicorn app.main:app --host "$HOST" --port "$PORT"
