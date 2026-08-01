"""Bridge between Humanizer.app and the Chrome extension.

Keeps a stable unpacked-extension folder in Application Support, registers a
Chrome Native Messaging host so the extension can auto-discover the local app,
and exposes a one-click connect helper for first-time load.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from macos.menubar import manager

# Stable ID from the public key in extension/manifest.json ("key" field).
EXTENSION_ID = "mhenjgoinbneknfpjjemjlhjjifmgmdi"
NATIVE_HOST_NAME = "com.humanizer.app"
DEFAULT_PORT = manager.DEFAULT_PORT


def extension_install_dir() -> Path:
    path = manager.support_dir() / "ChromeExtension"
    path.mkdir(parents=True, exist_ok=True)
    return path


def extension_ping_file() -> Path:
    return manager.support_dir() / "extension_ping.json"


def _extension_source(root: Path) -> Path | None:
    candidates = [
        root / "extension",
        Path(os.environ.get("HUMANIZER_BUNDLE_RESOURCES", "")) / "HumanizerHome" / "extension",
        manager.support_dir() / "Home" / "extension",
    ]
    for path in candidates:
        if path.is_dir() and (path / "manifest.json").is_file():
            return path
    return None


def sync_chrome_extension(root: Path | None = None) -> Path:
    """Copy extension files into the stable Application Support install path."""
    root = root or manager.resolve_project_root()
    src = _extension_source(root)
    dest = extension_install_dir()
    if src is None:
        return dest

    ignore = shutil.ignore_patterns(
        "__pycache__",
        "*.pyc",
        ".DS_Store",
        ".chrome-extension-id",
        "*.pem",
    )
    for item in src.iterdir():
        if item.name.startswith("."):
            continue
        target = dest / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(item, target, ignore=ignore)
        else:
            shutil.copy2(item, target)
    return dest


def _native_host_launcher() -> Path:
    """Writable wrapper script Chrome invokes for native messaging."""
    path = manager.support_dir() / "native_host.sh"
    home = manager.support_dir() / "Home"
    venv_py = home / ".venv" / "bin" / "python"
    script = f"""#!/bin/bash
export HUMANIZER_ROOT="{home}"
export PYTHONPATH="{home}${{PYTHONPATH:+:$PYTHONPATH}}"
cd "{home}"
if [[ -x "{venv_py}" ]]; then
  exec "{venv_py}" -m macos.menubar.native_host
fi
exec /usr/bin/python3 -m macos.menubar.native_host
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)
    return path


def _native_messaging_dirs() -> list[Path]:
    base = Path.home() / "Library" / "Application Support"
    return [
        base / "Google" / "Chrome" / "NativeMessagingHosts",
        base / "Chromium" / "NativeMessagingHosts",
        base / "BraveSoftware" / "Brave-Browser" / "NativeMessagingHosts",
        base / "Microsoft Edge" / "NativeMessagingHosts",
    ]


def register_native_messaging_host() -> dict:
    host_path = _native_host_launcher()
    manifest = {
        "name": NATIVE_HOST_NAME,
        "description": "Humanizer local writing assistant",
        "path": str(host_path),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{EXTENSION_ID}/"],
    }
    written: list[str] = []
    for directory in _native_messaging_dirs():
        try:
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / f"{NATIVE_HOST_NAME}.json"
            target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            written.append(str(target))
        except OSError:
            continue
    return {
        "host": NATIVE_HOST_NAME,
        "extension_id": EXTENSION_ID,
        "path": str(host_path),
        "manifests": written,
    }


def record_extension_ping(payload: dict | None = None) -> dict:
    data = {
        "ts": time.time(),
        "extension_id": EXTENSION_ID,
        **(payload or {}),
    }
    path = extension_ping_file()
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def extension_link_status(max_age_sec: float = 120.0) -> dict:
    path = extension_ping_file()
    if not path.is_file():
        return {"linked": False, "age_sec": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ts = float(data.get("ts") or 0)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"linked": False, "age_sec": None}
    age = max(0.0, time.time() - ts)
    return {"linked": age <= max_age_sec, "age_sec": round(age, 1), "last_ping": data}


def connect_info(*, include_token: bool = True) -> dict:
    """Payload returned to the extension via /connect or native messaging."""
    from security import API_TOKEN, REQUIRE_AUTH  # local import: server deps

    port = int(os.environ.get("HUMANIZER_PORT", str(DEFAULT_PORT)))
    auth_required = bool(REQUIRE_AUTH and API_TOKEN)
    info = {
        "ok": True,
        "app": "Humanizer",
        "host": "127.0.0.1",
        "port": port,
        "base_url": f"http://127.0.0.1:{port}",
        "auth_required": auth_required,
        "native_host": NATIVE_HOST_NAME,
        "extension_id": EXTENSION_ID,
        "extension_path": str(extension_install_dir()),
    }
    try:
        from macos.menubar import settings as app_settings

        info["features"] = app_settings.features_summary()
    except Exception:  # noqa: BLE001
        info["features"] = {
            "feature_grammar": True,
            "feature_rewrite": True,
            "feature_generate": True,
        }
    if include_token and auth_required and API_TOKEN:
        info["token"] = API_TOKEN
    return info


def prepare_extension_connection(root: Path | None = None) -> dict:
    """Sync files, register native host, return one-click connect details."""
    root = root or manager.resolve_project_root()
    path = sync_chrome_extension(root)
    nm = register_native_messaging_host()
    return {
        "ok": True,
        "extension_path": str(path),
        "extension_id": EXTENSION_ID,
        "native_messaging": nm,
        "chrome_extensions_url": "chrome://extensions",
        "instructions": [
            "Chrome opened to chrome://extensions",
            "Turn on Developer mode (top right)",
            "Click Load unpacked",
            "Paste the folder path from the clipboard (⌘V) and Open",
        ],
    }
