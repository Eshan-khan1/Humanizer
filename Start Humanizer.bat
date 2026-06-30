@echo off
title Humanizer Server
cd /d "%~dp0"

if not exist .venv (
  echo First-time setup — run scripts\install.sh in Git Bash or WSL first.
  echo See README.md for Windows setup.
  pause
  exit /b 1
)

call .venv\Scripts\activate.bat
python server.py
pause
