@echo off
echo ====================================
echo  BTC Macro AI Agentic System Setup
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

echo [1/6] Activating Python virtual environment...
echo.
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)

echo [2/6] Installing backend dependencies...
echo.
echo Upgrading pip...
python -m pip install --upgrade pip
echo.
echo Uninstalling old incompatible packages...
pip uninstall -y pydantic fastapi uvicorn starlette 2>nul
echo.
echo Installing fresh packages...
pip install fastapi uvicorn[standard] pydantic python-dotenv --prefer-binary
pip install openai --prefer-binary
pip install yfinance requests python-dateutil --prefer-binary
pip install numpy pandas --prefer-binary
if errorlevel 1 (
    echo [ERROR] Failed to install backend dependencies.
    pause
    exit /b 1
)

echo [3/6] Installing frontend dependencies...
echo.
cd frontend
if not exist "node_modules" (
    npm install
    if errorlevel 1 (
        echo [ERROR] Failed to install frontend dependencies.
        cd ..
        pause
        exit /b 1
    )
) else (
    echo Frontend dependencies already installed, skipping npm install.
)
cd ..

echo [4/6] Running deterministic macro analysis...
echo.
python backend\run_analysis.py
if errorlevel 1 (
    echo [WARNING] Analysis failed, but continuing to start servers...
    echo.
)

echo [5/6] Starting Backend Server...
echo.
start "BTC Backend Server" cmd /k "call .venv\Scripts\activate.bat && python -m uvicorn backend.main_v2:app --reload --host 0.0.0.0 --port 8001"
timeout /t 3 /nobreak >nul

echo [6/6] Starting Frontend Server...
echo.
cd frontend
start "BTC Frontend Server" cmd /k "npm run dev"
cd ..
timeout /t 3 /nobreak >nul

echo.
echo ====================================
echo  Application Started Successfully!
echo ====================================
echo.
echo Backend:  http://localhost:8001
echo Frontend: http://localhost:3000
echo.
echo Opening browser in 5 seconds...
timeout /t 5 /nobreak >nul
start http://localhost:3000

pause
