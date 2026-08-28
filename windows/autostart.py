"""Register Thoth to start at Windows login."""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

logger = logging.getLogger("thoth.windows")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_VALUE = "Thoth"


def _launcher_command() -> str:
    bundle = Path(os.environ.get("THOTH_BUNDLE_ROOT", "")).expanduser()
    if bundle.is_dir():
        bat = bundle / "Start Thoth.bat"
        if bat.is_file():
            return f'"{bat}"'

    pythonw = shutil.which("pythonw.exe") or sys.executable
    return f'"{pythonw}" -m windows.tray.app'


def is_login_item_enabled() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_VALUE)
        return True
    except OSError:
        return False


def ensure_login_item() -> None:
    import winreg

    command = _launcher_command()
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        RUN_KEY,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, APP_VALUE, 0, winreg.REG_SZ, command)
    logger.info("Registered Windows login item: %s", command)


def remove_login_item() -> None:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, APP_VALUE)
    except OSError:
        pass
