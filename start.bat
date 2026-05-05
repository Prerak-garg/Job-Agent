@echo off
echo Starting Job Agent...

:: Start backend
start "Job Agent Backend" cmd /k "cd /d %~dp0backend && py -3.12 -m uvicorn main:app --reload --port 8000"

:: Wait 2 seconds for backend to start
timeout /t 2 /nobreak >nul

:: Start frontend
start "Job Agent Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo Backend running at http://localhost:8000
echo Frontend running at http://localhost:3000
echo.
echo Open http://localhost:3000 in your browser
pause
