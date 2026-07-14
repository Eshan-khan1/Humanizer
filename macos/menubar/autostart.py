"""Legacy LaunchAgent cleanup. Background Activity is registered via SMAppService in Swift."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger("humanizer.menubar")

LEGACY_LAUNCH_AGENT_LABELS = (
    "com.humanizer.app",
    "com.humanizer.macos",
    "com.humanizer.menubar",
)


def ensure_login_item(program_arguments: list[str] | None = None) -> None:
    """Remove old silent LaunchAgents.

    macOS System Settings → Login Items & Background Activity only lists apps
    registered with SMAppService (handled by the native Humanizer host).
    """
    del program_arguments  # unused; kept for call-site compatibility
    agents = Path.home() / "Library" / "LaunchAgents"
    for label in LEGACY_LAUNCH_AGENT_LABELS:
        path = agents / f"{label}.plist"
        if path.is_file():
            try:
                path.unlink()
                logger.info("Removed legacy LaunchAgent at %s", path)
            except OSError as exc:
                logger.warning("Could not remove legacy LaunchAgent: %s", exc)
        try:
            subprocess.run(
                ["launchctl", "bootout", f"gui/{os.getuid()}/{label}"],
                check=False,
                capture_output=True,
            )
        except Exception:  # noqa: BLE001
            pass
