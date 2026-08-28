"""Thoth Windows tray app — mirrors the macOS menu-bar host."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from macos.menubar import extension_bridge, manager  # noqa: E402
from macos.menubar.icons_util import write_status_icons  # noqa: E402
from windows import autostart  # noqa: E402

logging.basicConfig(
    filename=str(manager.logs_dir() / "tray.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("thoth.windows.tray")

CHROME_STORE_URL = (
    "https://chromewebstore.google.com/detail/begfbbjincimcjcimpfpkoilbhjphppn"
    "?utm_source=item-share-cb"
)


def bootstrap_root() -> Path:
    resources = Path(os.environ.get("THOTH_BUNDLE_RESOURCES", "")).expanduser()
    if resources.is_dir() and (resources / "ThothHome" / "server.py").is_file():
        return manager.ensure_home_payload(resources)
    return manager.resolve_project_root()


def _tray_python(root: Path) -> Path:
    if sys.platform == "win32":
        pythonw = root / ".venv" / "Scripts" / "pythonw.exe"
        if pythonw.is_file():
            return pythonw
        return manager.venv_python_path(root)
    return manager.python_bin(root)


def _reexec_in_home_venv_if_needed(root: Path) -> None:
    """After venv bootstrap, run the tray under the Home venv (has pystray)."""
    try:
        manager.ensure_venv(root)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Venv bootstrap failed: %s", exc)
        return
    target = _tray_python(root)
    if not target.is_file():
        return
    try:
        if Path(sys.executable).resolve() == target.resolve():
            return
    except OSError:
        pass
    logger.info("Re-exec tray with %s", target)
    os.execv(str(target), [str(target), "-m", "windows.tray.app"])


def _run_service(args: list[str]) -> dict:
    root = bootstrap_root()
    python = manager.python_bin(root)
    proc = subprocess.run(
        [str(python), "-m", "macos.menubar.service", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        creationflags=manager._subprocess_flags(),  # noqa: SLF001
    )
    raw = (proc.stdout or proc.stderr or "").strip()
    if not raw:
        return {"ok": False, "error": "empty service response"}
    try:
        return json.loads(raw.splitlines()[-1])
    except json.JSONDecodeError:
        return {"ok": False, "error": raw[:300]}


class ThothTrayApp:
    def __init__(self) -> None:
        self.root = bootstrap_root()
        self.icon_dir = Path(__file__).resolve().parent.parent.parent / "macos" / "menubar" / "icons"
        write_status_icons(self.icon_dir)
        self.online_path = self.icon_dir / "status-online.png"
        self.offline_path = self.icon_dir / "status-offline.png"
        self.server_online = False
        self._icon = None
        self._stop_polling = threading.Event()

    def _load_icon(self, online: bool):
        from PIL import Image

        path = self.online_path if online else self.offline_path
        return Image.open(path)

    def _status_label(self) -> str:
        snap = manager.check_health()
        self.server_online = snap.server_ok
        if snap.server_ok:
            return f"Server online — {snap.detail}"
        if snap.ollama_ok:
            return "Server offline (Ollama is running)"
        return "Server offline"

    def _refresh_menu(self) -> None:
        if self._icon is None:
            return
        self._icon.title = "Thoth — online" if self.server_online else "Thoth — offline"
        self._icon.icon = self._load_icon(self.server_online)
        self._icon.menu = self._build_menu()

    def _poll_health(self) -> None:
        while not self._stop_polling.is_set():
            try:
                self._refresh_menu()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Health poll failed: %s", exc)
            time.sleep(4.0)

    def _on_start(self, _icon, _item) -> None:
        threading.Thread(target=self._start_server, daemon=True).start()

    def _start_server(self) -> None:
        try:
            extension_bridge.sync_chrome_extension(self.root)
            extension_bridge.register_native_messaging_host()
            manager.ensure_local_runtime()
            manager.start_server(self.root)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Start server failed: %s", exc)
        self._refresh_menu()

    def _on_restart(self, _icon, _item) -> None:
        threading.Thread(target=self._restart_server, daemon=True).start()

    def _restart_server(self) -> None:
        try:
            manager.restart_server(self.root)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Restart failed: %s", exc)
        self._refresh_menu()

    def _on_connect_extension(self, _icon, _item) -> None:
        def work() -> None:
            try:
                result = _run_service(["connect-extension"])
                path = result.get("extension_path") or str(extension_bridge.extension_install_dir())
                logger.info("Extension connect: %s", result)
                subprocess.Popen(
                    ["cmd", "/c", "start", "chrome://extensions"],
                    creationflags=manager._subprocess_flags(),  # noqa: SLF001
                )
                subprocess.Popen(
                    ["cmd", "/c", "start", CHROME_STORE_URL],
                    creationflags=manager._subprocess_flags(),  # noqa: SLF001
                )
                logger.info("Stable extension folder: %s", path)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Connect extension failed: %s", exc)

        threading.Thread(target=work, daemon=True).start()

    def _on_open_store(self, _icon, _item) -> None:
        webbrowser.open(CHROME_STORE_URL)

    def _on_open_health(self, _icon, _item) -> None:
        webbrowser.open("http://127.0.0.1:8000/health")

    def _on_toggle_autostart(self, _icon, _item) -> None:
        if autostart.is_login_item_enabled():
            autostart.remove_login_item()
        else:
            autostart.ensure_login_item()
        self._refresh_menu()

    def _on_quit(self, _icon, _item) -> None:
        self._stop_polling.set()
        manager.stop_server()
        self._icon.stop()

    def _build_menu(self):
        import pystray

        return pystray.Menu(
            pystray.MenuItem(self._status_label(), None, enabled=False),
            pystray.MenuItem("Restart server", self._on_restart),
            pystray.MenuItem("Connect Chrome extension…", self._on_connect_extension),
            pystray.MenuItem("Install extension (Chrome Web Store)", self._on_open_store),
            pystray.MenuItem("Open health check", self._on_open_health),
            pystray.MenuItem(
                "Start with Windows",
                self._on_toggle_autostart,
                checked=lambda _item: autostart.is_login_item_enabled(),
            ),
            pystray.MenuItem("Quit Thoth", self._on_quit),
        )

    def run(self) -> None:
        import pystray

        logger.info("Thoth Windows tray starting (root=%s)", self.root)

        threading.Thread(target=self._start_server, daemon=True).start()
        threading.Thread(target=self._poll_health, daemon=True).start()

        self._icon = pystray.Icon(
            "Thoth",
            self._load_icon(False),
            "Thoth — starting…",
            menu=self._build_menu(),
        )
        self._icon.run()


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("windows.tray.app is only supported on Windows")
    root = bootstrap_root()
    _reexec_in_home_venv_if_needed(root)
    ThothTrayApp().run()


if __name__ == "__main__":
    main()
