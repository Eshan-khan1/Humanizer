@echo off
REM Thoth Windows tray app (no console window). Double-click to start.
setlocal
cd /d "%~dp0"
if exist "%~dp0ThothHome\server.py" (
  set "THOTH_BUNDLE_RESOURCES=%~dp0"
  set "THOTH_BUNDLE_ROOT=%~dp0"
)
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" -m windows.tray.app
) else if exist ".venv\Scripts\python.exe" (
  start "" ".venv\Scripts\python.exe" -m windows.tray.app
) else (
  where pythonw >nul 2>&1
  if %ERRORLEVEL%==0 (
    start "" pythonw -m windows.tray.app
  ) else (
    start "" python -m windows.tray.app
  )
)
endlocal
