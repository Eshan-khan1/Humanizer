"""Humanizer macOS menu-bar app."""

from __future__ import annotations

import logging
import os
import platform
import sys
import threading
from pathlib import Path

# Allow `python -m macos.menubar.app` from repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from macos.menubar import autostart, manager  # noqa: E402
from macos.menubar.icons_util import write_status_icons  # noqa: E402

logging.basicConfig(
    filename=str(manager.logs_dir() / "menubar.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("humanizer.menubar")


def _reexec_native_if_needed() -> None:
    """Avoid Rosetta/x86_64 Python on Apple Silicon (breaks native wheels)."""
    if not manager.hardware_is_apple_silicon():
        return
    if platform.machine() == "arm64":
        return
    exe = manager.preferred_host_python()
    logger.info("Re-exec under arm64 with %s (was %s)", exe, sys.executable)
    os.execv(str(exe), [str(exe), "-m", "macos.menubar.app", *sys.argv[1:]])


_reexec_native_if_needed()


def _try_import_rumps():
    try:
        import rumps  # type: ignore

        return rumps
    except ImportError:
        python = manager.ensure_venv(manager.resolve_project_root())
        import subprocess

        subprocess.run(
            [str(python), "-m", "pip", "install", "rumps"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        import rumps  # type: ignore

        return rumps


rumps = _try_import_rumps()


class HumanizerMenuBarApp(rumps.App):
    def __init__(self, root: Path):
        self.root = root
        icon_online, icon_offline = _icon_paths()
        super().__init__(
            name="Humanizer",
            title="",
            icon=str(icon_offline),
            template=True,
            quit_button=None,
        )
        self.icon_online = icon_online
        self.icon_offline = icon_offline
        self.status_item = rumps.MenuItem("Status: Checking…")
        self.restart_item = rumps.MenuItem("Restart server", callback=self.on_restart)
        self.quit_item = rumps.MenuItem("Quit Humanizer", callback=self.on_quit)
        self.menu = [
            self.status_item,
            None,
            self.restart_item,
            self.quit_item,
        ]
        self._busy = False

    def _set_online(self, online: bool, detail: str) -> None:
        self.status_item.title = f"Status: {detail}"
        try:
            self.icon = str(self.icon_online if online else self.icon_offline)
        except Exception:  # noqa: BLE001
            self.title = "●" if online else "○"

    def _refresh_status(self) -> None:
        snap = manager.check_health()
        self._set_online(snap.server_ok, snap.detail)

    @rumps.timer(4)
    def poll_health(self, _):
        if self._busy:
            return
        self._refresh_status()

    def on_restart(self, _):
        if self._busy:
            return
        self._busy = True
        self.status_item.title = "Status: Restarting…"

        def work():
            try:
                ok = manager.restart_server(self.root)
                detail = "Server online" if ok else "Server offline"
                if not ok:
                    rumps.notification(
                        title="Humanizer",
                        subtitle="",
                        message="Could not start the server. Check Ollama is installed.",
                    )
                self._set_online(ok, detail)
            finally:
                self._busy = False

        threading.Thread(target=work, daemon=True).start()

    def on_quit(self, _):
        # Leave the background server running so the Chrome extension keeps working.
        rumps.quit_application()


def _icon_paths() -> tuple[Path, Path]:
    base = Path(__file__).resolve().parent / "icons"
    online = base / "status-online.png"
    offline = base / "status-offline.png"
    if not online.is_file() or not offline.is_file():
        return write_status_icons(base)
    return online, offline


def bootstrap_root() -> Path:
    resources = Path(os.environ.get("HUMANIZER_BUNDLE_RESOURCES", "")).expanduser()
    if resources.is_dir() and (resources / "HumanizerHome" / "server.py").is_file():
        return manager.ensure_home_payload(resources)
    return manager.resolve_project_root()


def main() -> None:
    root = bootstrap_root()
    logger.info("Humanizer root: %s", root)

    # Invisible first-run: open at login forever after.
    try:
        autostart.ensure_login_item()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Autostart setup failed: %s", exc)

    def warmup():
        try:
            manager.ensure_ollama_running()
            manager.start_server(root)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Startup failed: %s", exc)

    threading.Thread(target=warmup, daemon=True).start()
    HumanizerMenuBarApp(root).run()


if __name__ == "__main__":
    main()
