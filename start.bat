@echo off
title BTC Macro - Smart Start
echo ============================================
echo  BTC Macro - Smart Start
echo ============================================
echo.

REM --- Preflight checks ---
if not exist "backend\.env" (
    echo [ERROR] backend\.env not found. Create it with your API keys.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found. Run: python -m venv .venv
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate .venv
    pause
    exit /b 1
)

REM --- Check if ingestion already ran today ---
echo [1/3] Checking if analysis was already run today...
echo.

python -c "import sqlite3, sys; from pathlib import Path; from datetime import date; db=Path('backend/storage/macro_snapshots.db'); sys.exit(0) if db.exists() and sqlite3.connect(str(db)).execute('SELECT COUNT(*) FROM macro_snapshots WHERE timestamp LIKE ?', (date.today().isoformat()+'%%',)).fetchone()[0]>0 else sys.exit(1)"

if %errorlevel% equ 0 (
    echo [SKIP] Analysis snapshot found for today. Skipping ingestion.
    echo.
) else (
    echo No analysis found for today. Running ingestion...
    echo.
    python backend\run_analysis.py
    if errorlevel 1 (
        echo [WARNING] Analysis had errors, but continuing to start servers...
        echo.
    ) else (
        echo Analysis complete.
        echo.
    )
)

REM --- Start backend ---
echo [2/3] Starting backend (FastAPI v2 on port 8000)...
echo.
start "BTC Backend" cmd /k "call .venv\Scripts\activate.bat && python -m uvicorn backend.main_v2:app --reload --host 0.0.0.0 --port 8000"
timeout /t 3 /nobreak >nul

REM --- Start frontend ---
echo [3/3] Starting frontend (Next.js on port 3000)...
echo.
cd frontend
if not exist "node_modules" (
    echo Installing frontend dependencies...
    npm install
)
start "BTC Frontend" cmd /k "npm run dev"
cd ..
timeout /t 5 /nobreak >nul

REM --- Open browser ---
start http://localhost:3000

echo.
echo ============================================
echo  All services started
echo ============================================
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:3000
echo   API docs: http://localhost:8000/docs
echo ============================================
echo.
echo Close the Backend and Frontend windows to stop servers.
pause
