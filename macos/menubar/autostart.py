"""Legacy LaunchAgent cleanup. Background Activity is registered via SMAppService in Swift."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger("humanizer.menubar")

LAUNCH_AGENT_LABEL = "com.humanizer.app"
LAUNCH_AGENT_PATH = (
    Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
)


def ensure_login_item(program_arguments: list[str] | None = None) -> None:
    """Remove the old silent LaunchAgent.

    macOS System Settings → Login Items & Background Activity only lists apps
    registered with SMAppService (handled by the native Humanizer host).
    Leaving a hand-written LaunchAgent behind can confuse Background Task
    Management and hide Humanizer from that pane.
    """
    del program_arguments  # unused; kept for call-site compatibility
    if LAUNCH_AGENT_PATH.is_file():
        try:
            LAUNCH_AGENT_PATH.unlink()
            logger.info("Removed legacy LaunchAgent at %s", LAUNCH_AGENT_PATH)
        except OSError as exc:
            logger.warning("Could not remove legacy LaunchAgent: %s", exc)
    # Best-effort unload if still registered with launchd.
    try:
        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}/{LAUNCH_AGENT_LABEL}"],
            check=False,
            capture_output=True,
        )
    except Exception:  # noqa: BLE001
        pass
