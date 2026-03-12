@echo off
title BTC Macro - Run All
echo ============================================
echo  BTC Macro - Ingestion + Backend + Frontend
echo ============================================
echo.

REM Check backend .env
if not exist "backend\.env" (
    echo [ERROR] backend\.env not found. Create it with your API keys. See backend\README.md
    pause
    exit /b 1
)

REM Activate venv
if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found. Run setup first (e.g. python -m venv .venv).
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate .venv
    pause
    exit /b 1
)

echo [1/4] RAG ingestion (knowledge base -> vector store)...
echo.
cd backend
python -m rag.ingest
set INGEST_ERR=%errorlevel%
cd ..
if %INGEST_ERR% neq 0 (
    echo [WARNING] Ingestion had errors. Continuing to start servers...
    echo.
) else (
    echo Ingestion done.
    echo.
)

echo [2/4] Starting backend (FastAPI v2)...
echo.
start "BTC Backend" cmd /k "call .venv\Scripts\activate.bat && python -m uvicorn backend.main_v2:app --reload --host 0.0.0.0 --port 8000"
timeout /t 3 /nobreak >nul

echo [3/4] Starting frontend (Next.js)...
echo.
cd frontend
if not exist "node_modules" (
    echo Installing frontend dependencies...
    npm install
)
start "BTC Frontend" cmd /k "npm run dev"
cd ..
timeout /t 3 /nobreak >nul

echo [4/4] Opening browser...
timeout /t 5 /nobreak >nul
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
