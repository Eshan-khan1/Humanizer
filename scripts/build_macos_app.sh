#!/usr/bin/env bash
# Build a double-clickable Humanizer.app (menu bar) for macOS.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

APP_NAME="Humanizer"
DIST="$ROOT/dist"
APP="$DIST/${APP_NAME}.app"
CONTENTS="$APP/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
HOME_PAYLOAD="$RESOURCES/HumanizerHome"
MENUBAR_SRC="$ROOT/macos/menubar"

echo "==> Building ${APP_NAME}.app"

rm -rf "$APP"
mkdir -p "$MACOS" "$RESOURCES" "$HOME_PAYLOAD"

VERSION="$(python3 -c "import json; print(json.load(open('$ROOT/extension/manifest.json'))['version'])")"

# Bundle a lightweight server home (no huge model weights).
COPY_PATHS=(
  server.py
  writing_agent.py
  claim_check.py
  security.py
  cloud_ai.py
  rag.py
  grammar_rules.json
  generate_feature_rules.json
  requirements.txt
  scripts/ollama_gpu_env.sh
  extension
)
for rel in "${COPY_PATHS[@]}"; do
  src="$ROOT/$rel"
  dst="$HOME_PAYLOAD/$rel"
  mkdir -p "$(dirname "$dst")"
  if [[ -d "$src" ]]; then
    rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' --exclude '.DS_Store' --exclude '*.pem' "$src/" "$dst/"
  else
    cp "$src" "$dst"
  fi
done

mkdir -p "$HOME_PAYLOAD/macos"
cp "$ROOT/macos/__init__.py" "$HOME_PAYLOAD/macos/__init__.py"
rsync -a --delete --exclude '__pycache__' "$MENUBAR_SRC/" "$HOME_PAYLOAD/macos/menubar/"

python3 - <<PY
from pathlib import Path
import sys
sys.path.insert(0, "$ROOT")
from macos.menubar.icons_util import write_status_icons, write_app_iconset, write_extension_icons
write_status_icons(Path("$HOME_PAYLOAD/macos/menubar/icons"))
write_extension_icons(Path("$HOME_PAYLOAD/extension/icons"))
# Also refresh repo extension icons for Chrome reload from workspace.
write_extension_icons(Path("$ROOT/extension/icons"))
print("  status icons ready")
PY

# Keep logo next to icons so runtime helpers can find it if needed.
mkdir -p "$HOME_PAYLOAD/assets"
cp "$ROOT/assets/logo.png" "$HOME_PAYLOAD/assets/logo.png"
cp "$ROOT/assets/logo.png" "$HOME_PAYLOAD/macos/menubar/icons/logo.png"

ICONSET="$DIST/Humanizer.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
python3 - <<PY
from pathlib import Path
import sys
sys.path.insert(0, "$ROOT")
from macos.menubar.icons_util import write_app_iconset
write_app_iconset(Path("$ICONSET"))
print("  iconset ready")
PY

iconutil -c icns "$ICONSET" -o "$RESOURCES/AppIcon.icns"
rm -rf "$ICONSET"

cat > "$CONTENTS/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleExecutable</key>
  <string>Humanizer</string>
  <key>CFBundleIdentifier</key>
  <string>com.humanizer.macos</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>Humanizer</string>
  <key>CFBundleDisplayName</key>
  <string>Humanizer</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>${VERSION}</string>
  <key>CFBundleVersion</key>
  <string>${VERSION}</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>LSUIElement</key>
  <true/>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>NSHumanReadableCopyright</key>
  <string>Copyright (c) Humanizer</string>
</dict>
</plist>
PLIST

# Bundled LaunchAgent — required for System Settings → Login Items &
# Background Activity (“Allow in the Background”) via SMAppService.
LAUNCH_AGENTS_DIR="$CONTENTS/Library/LaunchAgents"
mkdir -p "$LAUNCH_AGENTS_DIR"
cat > "$LAUNCH_AGENTS_DIR/com.humanizer.macos.agent.plist" <<'AGENT'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.humanizer.macos.agent</string>
  <key>AssociatedBundleIdentifiers</key>
  <array>
    <string>com.humanizer.macos</string>
  </array>
  <key>BundleProgram</key>
  <string>Contents/MacOS/Humanizer</string>
  <key>RunAtLoad</key>
  <true/>
  <key>ProcessType</key>
  <string>Interactive</string>
</dict>
</plist>
AGENT

# Login Item helper (same pattern Stats / Raycast use). This is what gets
# Humanizer a row in System Settings → Login Items & Background Activity.
LOGIN_ITEM_APP="$CONTENTS/Library/LoginItems/LaunchAtLogin.app"
LOGIN_ITEM_CONTENTS="$LOGIN_ITEM_APP/Contents"
LOGIN_ITEM_MACOS="$LOGIN_ITEM_CONTENTS/MacOS"
mkdir -p "$LOGIN_ITEM_MACOS"
cat > "$LOGIN_ITEM_CONTENTS/Info.plist" <<LOGINPLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleExecutable</key>
  <string>LaunchAtLogin</string>
  <key>CFBundleIdentifier</key>
  <string>com.humanizer.macos.LaunchAtLogin</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>Humanizer</string>
  <key>CFBundleDisplayName</key>
  <string>Humanizer</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>${VERSION}</string>
  <key>CFBundleVersion</key>
  <string>${VERSION}</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>LSUIElement</key>
  <true/>
  <key>LSBackgroundOnly</key>
  <true/>
</dict>
</plist>
LOGINPLIST
echo "  compiling LaunchAtLogin helper"
swiftc -O \
  -target arm64-apple-macos13.0 \
  -sdk "$(xcrun --show-sdk-path)" \
  -framework AppKit -framework Foundation \
  -o "$LOGIN_ITEM_MACOS/LaunchAtLogin" \
  "$ROOT/macos/launcher/LaunchAtLogin.swift"
codesign --force --sign - "$LOGIN_ITEM_APP" >/dev/null 2>&1 || true

# Native AppKit host (Swift). Required on macOS 26 so Humanizer appears in
# System Settings → Menu Bar / Background Activity.
LAUNCHER_SRC="$ROOT/macos/launcher/HumanizerApp.swift"
echo "  compiling native menu-bar host (Swift/AppKit + ServiceManagement)"
swiftc -O \
  -target arm64-apple-macos13.0 \
  -sdk "$(xcrun --show-sdk-path)" \
  -framework AppKit -framework Foundation -framework ServiceManagement \
  -o "$MACOS/Humanizer" \
  "$LAUNCHER_SRC"

# Ad-hoc sign so Gatekeeper is less likely to block double-click opens.
codesign --force --sign - "$MACOS/Humanizer" >/dev/null 2>&1 || true
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true

echo ""
echo "Built: $APP"
echo ""
echo "To use:"
echo "  1. Drag into /Applications and open once"
echo "  2. System Settings → Menu Bar → turn Humanizer ON"
echo "  3. Look for the H icon near the clock"
echo ""
echo "Needs: Python 3, Ollama app, Chrome extension (Connect Chrome Extension… in the app)"
