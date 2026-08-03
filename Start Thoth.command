#!/bin/bash
# Double-click this in Finder. Prefers the menu-bar app (no Terminal).
cd "$(dirname "$0")"

if [[ -d "dist/Thoth.app" ]]; then
  open "dist/Thoth.app"
  exit 0
fi

if [[ -d "/Applications/Thoth.app" ]]; then
  open "/Applications/Thoth.app"
  exit 0
fi

# Fallback for developers who have not built the .app yet.
osascript -e 'tell application "Terminal" to activate' 2>/dev/null || true
if [[ ! -d .venv ]]; then
  echo "First-time setup..."
  chmod +x scripts/install.sh
  ./scripts/install.sh
fi
chmod +x start_server.sh
./start_server.sh
