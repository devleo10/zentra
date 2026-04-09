@echo off
echo ====================================
echo  BTC Macro AI Agentic System
echo ====================================
echo.

REM Check if backend .env exists
if not exist "backend\.env" (
    echo [ERROR] backend\.env file not found!
    echo Please create backend\.env with your API keys.
    echo See backend\README.md for setup instructions.
    pause
    exit /b 1
)

REM Check if frontend .env.local exists (optional but recommended)
if not exist "frontend\.env.local" (
    echo [WARNING] frontend\.env.local not found. Using default localhost:8001
    echo.
)

echo [1/4] Starting Backend Server...
echo.
cd backend
start "BTC Backend Server" cmd /k "python -m uvicorn main_v2:app --reload --host 0.0.0.0 --port 8001"
timeout /t 3 /nobreak >nul

echo [2/4] Waiting for backend to initialize...
timeout /t 5 /nobreak >nul

echo.
echo [3/4] Starting Frontend Server...
echo.
cd ..\frontend
start "BTC Frontend Server" cmd /k "npm run dev"
timeout /t 3 /nobreak >nul

echo.
echo [4/4] Opening browser...
timeout /t 8 /nobreak >nul
start http://localhost:3000

echo.
echo ====================================
echo  Application Started Successfully!
echo ====================================
echo.
echo Backend:  http://localhost:8001
echo Frontend: http://localhost:3000
echo.
echo Press any key to stop all servers...
pause >nul

echo.
echo Stopping servers...
taskkill /FI "WindowTitle eq BTC Backend Server*" /T /F >nul 2>&1
taskkill /FI "WindowTitle eq BTC Frontend Server*" /T /F >nul 2>&1
echo Servers stopped.
