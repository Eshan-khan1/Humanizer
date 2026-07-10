@echo off
setlocal EnableExtensions
title Humanizer Server
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo First-time setup...
  call "scripts\install.bat"
  if errorlevel 1 (
    echo Setup failed.
    pause
    exit /b 1
  )
)

echo Stopping any previous server on port 8000...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do (
  taskkill /F /PID %%P >nul 2>&1
)

where ollama >nul 2>&1
if not errorlevel 1 (
  curl -sf http://127.0.0.1:11434/api/tags >nul 2>&1
  if errorlevel 1 (
    echo Starting Ollama...
    start "" ollama serve
    timeout /t 3 /nobreak >nul
  )
)

call ".venv\Scripts\activate.bat"
echo Starting Humanizer local server at http://127.0.0.1:8000
echo   Keep this window open while using the Chrome extension.
echo   Press Ctrl+C to stop.
echo.
python server.py
set EXITCODE=%ERRORLEVEL%
echo.
if not "%EXITCODE%"=="0" (
  echo Server exited with code %EXITCODE%.
)
pause
endlocal
exit /b %EXITCODE%
