"""Install Humanizer to relaunch at login without prompting the user."""

from __future__ import annotations

import logging
import os
import plistlib
from pathlib import Path

logger = logging.getLogger("humanizer.menubar")

LAUNCH_AGENT_LABEL = "com.humanizer.app"
LAUNCH_AGENT_PATH = (
    Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
)


def _app_executable() -> str | None:
    # When running inside an .app, this is .../Humanizer.app/Contents/MacOS/Humanizer
    exe = os.environ.get("HUMANIZER_APP_EXECUTABLE", "").strip()
    if exe and Path(exe).is_file():
        return exe

    # Detect if we were launched via an .app bundle.
    # argv[0] for the bash launcher ends with Contents/MacOS/Humanizer
    import sys

    cand = Path(sys.argv[0]).resolve()
    if cand.name == "Humanizer" and "Contents/MacOS" in str(cand):
        return str(cand)
    return None


def ensure_login_item(program_arguments: list[str] | None = None) -> None:
    """Write a LaunchAgent so Humanizer starts after login/restart."""
    args = program_arguments
    if not args:
        exe = _app_executable()
        if exe:
            args = [exe]
        else:
            # Dev fallback: relaunch this module with python
            import sys

            args = [sys.executable, "-m", "macos.menubar.app"]

    plist = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": args,
        "RunAtLoad": True,
        "KeepAlive": False,
        "ProcessType": "Interactive",
        "StandardOutPath": str(
            Path.home() / "Library" / "Logs" / "Humanizer" / "launchagent.out.log"
        ),
        "StandardErrorPath": str(
            Path.home() / "Library" / "Logs" / "Humanizer" / "launchagent.err.log"
        ),
    }

    LAUNCH_AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if LAUNCH_AGENT_PATH.is_file():
        try:
            with LAUNCH_AGENT_PATH.open("rb") as handle:
                existing = plistlib.load(handle)
        except Exception:  # noqa: BLE001
            existing = {}

    if existing.get("ProgramArguments") == args and existing.get("RunAtLoad") is True:
        return

    with LAUNCH_AGENT_PATH.open("wb") as handle:
        plistlib.dump(plist, handle)

    # Only register the file for future logins. Do not bootstrap/kickstart now,
    # or macOS would launch a second copy of the app during first-run setup.
    logger.info("Login item installed at %s", LAUNCH_AGENT_PATH)
