@echo off
REM PharmaStock 2027 - one-command start (Windows). Runs ONE program: backend + built frontend on http://127.0.0.1:8000
cd /d "%~dp0"

if not exist .venv ( python -m venv .venv || goto :error )
call .venv\Scripts\activate.bat || goto :error

if exist backend\requirements.txt (
  pip install -q -r backend\requirements.txt || goto :error
) else (
  pip install -q fastapi "uvicorn[standard]" bcrypt openpyxl python-multipart || goto :error
)
pip install -q cryptography || goto :error

if not exist frontend\out\index.html (
  echo Building the screens - first time only, needs internet and Node.js...
  pushd frontend
  call npm install || goto :error
  call npm run build || goto :error
  popd
)

if "%PHARMASTOCK_PORT%"=="" set PHARMASTOCK_PORT=8000
if "%PHARMASTOCK_HOST%"=="" set PHARMASTOCK_HOST=127.0.0.1
echo PharmaStock is starting. Your browser will open. Close this window to stop PharmaStock.
start "" http://127.0.0.1:%PHARMASTOCK_PORT%
cd backend
uvicorn app.main:app --host %PHARMASTOCK_HOST% --port %PHARMASTOCK_PORT%
goto :eof

:error
echo.
echo Something went wrong. Please read the message above and see README.md (Problems section).
pause
exit /b 1
