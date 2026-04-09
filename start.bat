@echo off
setlocal EnableExtensions EnableDelayedExpansion
title BTC Macro - Start

REM Always run from the folder that contains this script (repo root)
cd /d "%~dp0"
set "ROOT=%CD%"

echo ============================================
echo  BTC Macro - Start
echo ============================================
echo  Root:    %ROOT%
echo.

REM --- Ports (override before launch: set BACKEND_PORT=8080 ^&^& start.bat) ---
if not defined BACKEND_PORT set "BACKEND_PORT=8001"
if not defined FRONTEND_PORT set "FRONTEND_PORT=3000"

REM --- Preflight ---
if not exist "%ROOT%\backend\.env" (
    echo [ERROR] backend\.env not found. Create it with your API keys.
    pause
    exit /b 1
)

if not exist "%ROOT%\.venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found at: %ROOT%\.venv
    echo Create it from the repo root:  python -m venv .venv
    echo Then:  .venv\Scripts\activate  ^&^& pip install -r backend\requirements.txt
    pause
    exit /b 1
)

call "%ROOT%\.venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] Failed to activate .venv
    pause
    exit /b 1
)

REM --- Frontend API URL (must match page origin for CORS: use localhost, not 127.0.0.1) ---
if not exist "%ROOT%\frontend\.env.local" (
    echo NEXT_PUBLIC_API_URL=http://localhost:%BACKEND_PORT%> "%ROOT%\frontend\.env.local"
    echo [INFO] Created frontend\.env.local ^(NEXT_PUBLIC_API_URL=http://localhost:%BACKEND_PORT%^)
) else (
    findstr /I "NEXT_PUBLIC_API_URL" "%ROOT%\frontend\.env.local" >nul 2>&1
    if errorlevel 1 (
        echo NEXT_PUBLIC_API_URL=http://localhost:%BACKEND_PORT%>> "%ROOT%\frontend\.env.local"
        echo [INFO] Appended NEXT_PUBLIC_API_URL to frontend\.env.local
    )
)

REM --- Optional: daily snapshot (skip if already run today) ---
echo [1/4] Checking for today's analysis snapshot...
pushd "%ROOT%"
python -c "import sqlite3, sys; from pathlib import Path; from datetime import date; db=Path('backend/storage/macro_snapshots.db'); sys.exit(0) if db.exists() and sqlite3.connect(str(db)).execute('SELECT COUNT(*) FROM macro_snapshots WHERE timestamp LIKE ?', (date.today().isoformat()+'%%',)).fetchone()[0]>0 else sys.exit(1)" 2>nul
if errorlevel 1 (
    echo No snapshot for today — running backend\run_analysis.py ...
    python "%ROOT%\backend\run_analysis.py"
    if errorlevel 1 (
        echo [WARNING] Analysis reported errors; continuing to start servers...
    )
) else (
    echo [SKIP] Snapshot already exists for today.
)
popd
echo.

REM --- Backend: /D sets cwd so main_v2:app resolves; venv is one level up ---
echo [2/4] Starting backend — http://localhost:%BACKEND_PORT%  ^(FastAPI v2^)
start "BTC Macro - Backend" /D "%ROOT%\backend" cmd /k "call ..\.venv\Scripts\activate.bat && python -m uvicorn main_v2:app --reload --host 0.0.0.0 --port %BACKEND_PORT%"

timeout /t 2 /nobreak >nul

REM --- Wait for health (up to ~35s) ---
echo [3/4] Waiting for backend /api/health ...
set /a _try=0
:__health_loop
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -Uri 'http://localhost:%BACKEND_PORT%/api/health' -UseBasicParsing -TimeoutSec 2; exit [int]($r.StatusCode -ne 200) } catch { exit 1 }"
if not errorlevel 1 goto __health_ok
set /a _try+=1
if !_try! geq 35 (
    echo [WARNING] Health check timed out — is port %BACKEND_PORT% free? Backend window may show errors.
    goto __frontend
)
timeout /t 1 /nobreak >nul
goto __health_loop
:__health_ok
echo [OK] Backend is up.
:__frontend

REM --- Frontend ---
echo [4/4] Starting frontend — http://localhost:%FRONTEND_PORT%
cd /d "%ROOT%\frontend"
if not exist "node_modules" (
    echo Installing frontend dependencies...
    call npm install
    if errorlevel 1 (
        echo [ERROR] npm install failed.
        cd /d "%ROOT%"
        pause
        exit /b 1
    )
)
cd /d "%ROOT%"
start "BTC Macro - Frontend" /D "%ROOT%\frontend" cmd /k "npm run dev -- -p %FRONTEND_PORT%"

timeout /t 4 /nobreak >nul
start http://localhost:%FRONTEND_PORT%/

echo.
echo ============================================
echo  Services started
echo ============================================
echo   Backend:  http://localhost:%BACKEND_PORT%/
echo   API docs: http://localhost:%BACKEND_PORT%/docs
echo   Frontend: http://localhost:%FRONTEND_PORT%/
echo ============================================
echo   Close the "Backend" and "Frontend" windows to stop.
echo ============================================
echo.
pause
endlocal
