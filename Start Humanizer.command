#!/bin/bash
# Double-click this file on macOS to start the Humanizer server.
cd "$(dirname "$0")"
osascript -e 'tell application "Terminal" to activate' 2>/dev/null || true
if [[ ! -d .venv ]]; then
  echo "First-time setup..."
  chmod +x scripts/install.sh
  ./scripts/install.sh
fi
chmod +x start_server.sh
./start_server.sh
