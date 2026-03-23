@echo off
echo ========================================
echo   金融即時偵測系統 Financial Radar
echo ========================================
echo.

:: Copy .env if not exists
if not exist .env (
    copy .env.example .env
    echo [INFO] Created .env from .env.example
    echo [WARN] Please edit .env and add your API keys!
    echo.
)

:: Start backend
echo [1/2] Starting backend server on http://localhost:8000 ...
start "Financial Radar Backend" cmd /c "cd /d %~dp0 && python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload"

:: Wait for backend
timeout /t 3 /nobreak > nul

:: Start frontend
echo [2/2] Starting frontend dev server on http://localhost:5173 ...
start "Financial Radar Frontend" cmd /c "cd /d %~dp0\frontend && npm run dev"

echo.
echo ========================================
echo   System started successfully!
echo   Frontend: http://localhost:5173
echo   Backend:  http://localhost:8000
echo   API Docs: http://localhost:8000/docs
echo ========================================
echo.
echo Press any key to exit (servers will keep running)...
pause > nul
