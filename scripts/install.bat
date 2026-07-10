@echo off
setlocal EnableExtensions
title Humanizer — Install
cd /d "%~dp0.."

echo ============================================
echo   Humanizer installer ^(Windows^)
echo ============================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python was not found on PATH.
  echo Install Python 3.10+ from https://www.python.org/downloads/
  echo During setup, check "Add python.exe to PATH".
  exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo Found Python %PYVER%

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo ERROR: Failed to create .venv
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"
echo Upgrading pip...
python -m pip install --upgrade pip -q
echo Installing requirements...
python -m pip install -r requirements.txt -q
if errorlevel 1 (
  echo ERROR: pip install failed
  exit /b 1
)

echo Downloading NLTK data...
python -c "import nltk; [nltk.download(p, quiet=True) for p in ('punkt','punkt_tab','averaged_perceptron_tagger','averaged_perceptron_tagger_eng')]" 2>nul

where java >nul 2>&1
if errorlevel 1 (
  echo.
  echo WARNING: Java not found. Grammar checks need Java 11+.
  echo   Download: https://adoptium.net/
) else (
  echo Java found.
)

where ollama >nul 2>&1
if errorlevel 1 (
  echo.
  echo WARNING: Ollama not found. Rewrite / Generate need Ollama.
  echo   Download: https://ollama.com
  echo   After installing, open Ollama, then run: scripts\setup_models.bat
) else (
  echo Ollama found.
  curl -sf http://127.0.0.1:11434/api/tags >nul 2>&1
  if errorlevel 1 (
    echo   Start the Ollama app, then run: scripts\setup_models.bat
  ) else (
    call "%~dp0setup_models.bat"
  )
)

echo.
echo ============================================
echo   Install complete!
echo.
echo   Next steps:
echo     1. Double-click "Start Humanizer.bat"  OR  run start_server.bat
echo     2. Chrome -^> chrome://extensions -^> Developer mode
echo        Load unpacked -^> select the extension folder
echo     3. Full Windows guide: docs\INSTALL_WINDOWS.md
echo ============================================
endlocal
exit /b 0
