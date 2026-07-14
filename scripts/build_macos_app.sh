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

# Bundle a lightweight server home (no huge model weights).
COPY_PATHS=(
  server.py
  writing_agent.py
  security.py
  cloud_ai.py
  rag.py
  grammar_rules.json
  requirements.txt
  scripts/ollama_gpu_env.sh
)
for rel in "${COPY_PATHS[@]}"; do
  src="$ROOT/$rel"
  dst="$HOME_PAYLOAD/$rel"
  mkdir -p "$(dirname "$dst")"
  if [[ -d "$src" ]]; then
    rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' --exclude '.DS_Store' "$src/" "$dst/"
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
from macos.menubar.icons_util import write_status_icons
write_status_icons(Path("$HOME_PAYLOAD/macos/menubar/icons"))
print("  status icons ready")
PY

ICONSET="$DIST/Humanizer.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
python3 - <<'PY'
from pathlib import Path
import struct
import zlib

def write_png(path: Path, size: int) -> None:
    def pixel(x, y):
        cx = cy = (size - 1) / 2
        dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
        if dist <= size * 0.42:
            return (201, 100, 66, 255)
        if dist <= size * 0.48:
            return (201, 100, 66, 90)
        return (0, 0, 0, 0)

    raw = b""
    for y in range(size):
        raw += b"\x00"
        for x in range(size):
            raw += bytes(pixel(x, y))
    compressed = zlib.compress(raw, 9)

    def chunk(tag, data):
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )

iconset = Path("dist/Humanizer.iconset")
mapping = {
    16: ["icon_16x16.png"],
    32: ["icon_16x16@2x.png", "icon_32x32.png"],
    64: ["icon_32x32@2x.png"],
    128: ["icon_128x128.png"],
    256: ["icon_128x128@2x.png", "icon_256x256.png"],
    512: ["icon_256x256@2x.png", "icon_512x512.png"],
    1024: ["icon_512x512@2x.png"],
}
for size, names in mapping.items():
    for name in names:
        write_png(iconset / name, size)
print("  iconset ready")
PY

iconutil -c icns "$ICONSET" -o "$RESOURCES/AppIcon.icns"
rm -rf "$ICONSET"

cat > "$CONTENTS/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleExecutable</key>
  <string>Humanizer</string>
  <key>CFBundleIdentifier</key>
  <string>com.humanizer.menubar</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>Humanizer</string>
  <key>CFBundleDisplayName</key>
  <string>Humanizer</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.9.1</string>
  <key>CFBundleVersion</key>
  <string>1.9.1</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>LSUIElement</key>
  <true/>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>NSHumanReadableCopyright</key>
  <string>Copyright (c) Humanizer</string>
</dict>
</plist>
PLIST

cat > "$MACOS/Humanizer" <<'LAUNCHER'
#!/bin/bash
set -euo pipefail

SELF="$(cd "$(dirname "$0")" && pwd)"
CONTENTS="$(cd "$SELF/.." && pwd)"
RESOURCES="$CONTENTS/Resources"

# GUI/login launches often omit Homebrew from PATH.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

export HUMANIZER_APP_EXECUTABLE="$SELF/Humanizer"
export HUMANIZER_BUNDLE_RESOURCES="$RESOURCES"
export PYTHONUNBUFFERED=1

HOME_PAYLOAD="$RESOURCES/HumanizerHome"
SUPPORT_HOME="$HOME/Library/Application Support/Humanizer/Home"
mkdir -p "$HOME/Library/Logs/Humanizer"
mkdir -p "$HOME/Library/Application Support/Humanizer"

# Force native CPU if this .app was opened under Rosetta.
PREFERRED_ARCH="x86_64"
if [[ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" == "1" ]]; then
  PREFERRED_ARCH="arm64"
fi
if [[ "${HUMANIZER_ARCH_OK:-0}" != "1" ]]; then
  export HUMANIZER_ARCH_OK=1
  exec /usr/bin/arch -"$PREFERRED_ARCH" /bin/bash "$0" "$@"
fi

pick_python() {
  # Prefer a healthy Application Support venv once it exists.
  if [[ -x "$SUPPORT_HOME/.venv/bin/python" ]]; then
    if "$SUPPORT_HOME/.venv/bin/python" -c "import fastapi, uvicorn, rumps" >/dev/null 2>&1; then
      echo "$SUPPORT_HOME/.venv/bin/python"
      return
    fi
  fi
  for candidate in \
    /opt/homebrew/bin/python3.12 \
    /opt/homebrew/bin/python3.11 \
    /opt/homebrew/bin/python3.10 \
    /usr/bin/python3 \
    /opt/homebrew/bin/python3 \
    /usr/local/bin/python3
  do
    if [[ -x "$candidate" ]]; then
      echo "$candidate"
      return
    fi
  done
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return
  fi
  echo "/usr/bin/python3"
}

PYTHON="$(pick_python)"
export PYTHONPATH="$HOME_PAYLOAD${PYTHONPATH:+:$PYTHONPATH}"
if [[ -d "$SUPPORT_HOME" ]]; then
  export PYTHONPATH="$SUPPORT_HOME:$PYTHONPATH"
fi

# rumps is installed into the managed venv on first run; best-effort for host python.
"$PYTHON" -m pip install --user rumps >/dev/null 2>&1 || \
  "$PYTHON" -m pip install rumps >/dev/null 2>&1 || true

cd "$HOME_PAYLOAD"
exec /usr/bin/arch -"$PREFERRED_ARCH" "$PYTHON" -m macos.menubar.app \
  >>"$HOME/Library/Logs/Humanizer/menubar.stdout.log" \
  2>>"$HOME/Library/Logs/Humanizer/menubar.stderr.log"
LAUNCHER

chmod +x "$MACOS/Humanizer"

echo ""
echo "Built: $APP"
echo ""
echo "To use:"
echo "  1. Open the app once (or drag into /Applications, then open it)"
echo "  2. A Humanizer icon appears in the menu bar"
echo "  3. After restart/login it opens by itself"
echo ""
echo "Needs: Python 3, Ollama app, Chrome extension loaded from extension/"
