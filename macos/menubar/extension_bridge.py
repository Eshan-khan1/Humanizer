"""Bridge between Thoth.app and the Chrome extension.

Keeps a stable unpacked-extension folder in Application Support, registers a
Chrome Native Messaging host so the extension can auto-discover the local app,
and exposes a one-click connect helper for first-time load.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import time
from pathlib import Path
from typing import Any

from macos.menubar import manager

# Stable ID from the public key in extension/manifest.json ("key" field).
EXTENSION_ID = "mhenjgoinbneknfpjjemjlhjjifmgmdi"
NATIVE_HOST_NAME = "com.thoth.app"
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
        Path(os.environ.get("THOTH_BUNDLE_RESOURCES", "")) / "ThothHome" / "extension",
        manager.support_dir() / "Home" / "extension",
    ]
    for path in candidates:
        if path.is_dir() and (path / "manifest.json").is_file():
            return path
    return None


def sync_chrome_extension(root: Path | None = None) -> Path:
    """Copy extension files into the stable Application Support install path.

    Updates files in place (no full-folder wipe) so Chrome's unpacked install
    keeps working across Chrome restarts.
    """
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
            # Merge/update instead of delete+recreate — wiping icons/ while Chrome
            # is closed can make Chrome drop the unpacked extension on next launch.
            if target.exists() and target.is_dir():
                for child in item.rglob("*"):
                    if child.is_dir():
                        continue
                    rel = child.relative_to(item)
                    if any(part.startswith(".") for part in rel.parts):
                        continue
                    if child.suffix in {".pyc"} or child.name == ".DS_Store":
                        continue
                    out = target / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(child, out)
            else:
                if target.exists():
                    if target.is_dir():
                        shutil.rmtree(target, ignore_errors=True)
                    else:
                        target.unlink(missing_ok=True)
                shutil.copytree(item, target, ignore=ignore)
        else:
            shutil.copy2(item, target)
    return dest


def _native_host_launcher() -> Path:
    """Writable wrapper script Chrome invokes for native messaging."""
    home = manager.support_dir() / "Home"
    venv_py = manager.venv_python_path(home)

    if platform.system() == "Windows":
        path = manager.support_dir() / "native_host.bat"
        script = f"""@echo off
set THOTH_ROOT={home}
set PYTHONPATH={home}%PYTHONPATH%
cd /d "{home}"
if exist "{venv_py}" (
  "{venv_py}" -m macos.menubar.native_host
) else (
  python -m macos.menubar.native_host
)
"""
        path.write_text(script, encoding="utf-8")
        return path

    path = manager.support_dir() / "native_host.sh"
    venv_py_unix = home / ".venv" / "bin" / "python"
    script = f"""#!/bin/bash
export THOTH_ROOT="{home}"
export PYTHONPATH="{home}${{PYTHONPATH:+:$PYTHONPATH}}"
cd "{home}"
if [[ -x "{venv_py_unix}" ]]; then
  exec "{venv_py_unix}" -m macos.menubar.native_host
fi
exec /usr/bin/python3 -m macos.menubar.native_host
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)
    return path


def _native_messaging_dirs() -> list[Path]:
    if platform.system() == "Windows":
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        names = (
            "Google/Chrome/NativeMessagingHosts",
            "Google/Chrome Beta/NativeMessagingHosts",
            "Chromium/NativeMessagingHosts",
            "BraveSoftware/Brave-Browser/NativeMessagingHosts",
            "Microsoft/Edge/NativeMessagingHosts",
        )
        return [local / name for name in names]

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
        "description": "Thoth local writing assistant",
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

    port = int(os.environ.get("THOTH_PORT", str(DEFAULT_PORT)))
    auth_required = bool(REQUIRE_AUTH and API_TOKEN)
    info = {
        "ok": True,
        "app": "Thoth",
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
    diagnosis = diagnose_chrome_extension_install()
    instructions = [
        "Chrome opened to chrome://extensions",
        "Remove any old Thoth / Humanizer cards (trash icon)",
        "Turn on Developer mode (top right) and leave it ON",
        "Click Load unpacked",
        "Paste the folder path from the clipboard (⌘V) — must be Application Support/Thoth/ChromeExtension, not the repo",
        "If Chrome asks to disable developer extensions when you reopen, click Cancel",
    ]
    if diagnosis.get("wrong_path"):
        instructions.insert(
            1,
            "WARNING: Chrome currently points at a temporary/repo folder — that is why Thoth disappears after quit. Reload from the path below.",
        )
    return {
        "ok": True,
        "extension_path": str(path),
        "extension_id": EXTENSION_ID,
        "native_messaging": nm,
        "chrome_extensions_url": "chrome://extensions",
        "instructions": instructions,
        "diagnosis": diagnosis,
    }


def diagnose_chrome_extension_install() -> dict:
    """Detect unpacked Thoth installs that use an unstable folder path."""
    stable = str(extension_install_dir().resolve())
    if platform.system() == "Windows":
        chrome_root = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
    else:
        chrome_root = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
    installs: list[dict[str, Any]] = []
    wrong: list[dict[str, Any]] = []
    if not chrome_root.is_dir():
        return {
            "stable_path": stable,
            "wrong_path": False,
            "installs": [],
            "developer_mode": None,
        }

    developer_mode: bool | None = None
    for secure in chrome_root.glob("*/Secure Preferences"):
        try:
            data = json.loads(secure.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        ext = data.get("extensions") or {}
        ui = ext.get("ui") or {}
        if "developer_mode" in ui and developer_mode is None:
            developer_mode = bool(ui.get("developer_mode"))
        settings = ext.get("settings") or {}
        for eid, info in settings.items():
            if not isinstance(info, dict):
                continue
            path = str(info.get("path") or "").strip()
            if not path:
                continue
            name = str((info.get("manifest") or {}).get("name") or "")
            is_thoth = (
                eid == EXTENSION_ID
                or "thoth" in name.lower()
                or "humanizer" in name.lower()
                or "chromeextension" in path.lower()
                or (
                    "/extension" in path.lower()
                    and ("thoth" in path.lower() or "humanizer" in path.lower())
                )
            )
            if not is_thoth and info.get("location") != 4:
                continue
            if not is_thoth:
                continue
            try:
                resolved = str(Path(path).expanduser().resolve())
            except OSError:
                resolved = path
            entry = {
                "profile": secure.parent.name,
                "extension_id": eid,
                "path": resolved,
                "location": info.get("location"),
                "state": info.get("state"),
            }
            installs.append(entry)
            if resolved != stable:
                wrong.append(entry)

    return {
        "stable_path": stable,
        "wrong_path": bool(wrong),
        "wrong_installs": wrong,
        "installs": installs,
        "developer_mode": developer_mode,
    }
