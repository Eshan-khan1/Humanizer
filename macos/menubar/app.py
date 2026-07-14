"""Humanizer macOS menu-bar app (native AppKit — works on macOS 26+)."""

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

logging.basicConfig(
    filename=str(manager.logs_dir() / "menubar.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("humanizer.menubar")


def _reexec_native_if_needed() -> None:
    if not manager.hardware_is_apple_silicon():
        return
    if platform.machine() == "arm64":
        return
    exe = manager.preferred_host_python()
    logger.info("Re-exec under arm64 with %s (was %s)", exe, sys.executable)
    os.execv(str(exe), [str(exe), "-m", "macos.menubar.app", *sys.argv[1:]])


_reexec_native_if_needed()


def main() -> None:
    try:
        import AppKit
        import Foundation
        import objc
        from PyObjCTools import AppHelper
    except ImportError as exc:
        logger.exception("AppKit/PyObjC missing: %s", exc)
        raise SystemExit(
            "Humanizer needs PyObjC (pyobjc-framework-Cocoa). Re-open after deps install."
        ) from exc

    root = bootstrap_root()
    logger.info("Humanizer root: %s", root)
    logger.info(
        "System: macOS %s %s",
        platform.mac_ver()[0] or "unknown",
        platform.machine(),
    )

    try:
        autostart.ensure_login_item()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Autostart setup failed: %s", exc)

    def notify_user(title: str, message: str) -> None:
        try:
            note = AppKit.NSUserNotification.alloc().init()
            note.setTitle_(title)
            note.setInformativeText_(message)
            AppKit.NSUserNotificationCenter.defaultUserNotificationCenter().deliverNotification_(
                note
            )
        except Exception:  # noqa: BLE001
            logger.info("Notify: %s — %s", title, message)

    class AppDelegate(Foundation.NSObject):
        def init(self):
            self = objc.super(AppDelegate, self).init()
            if self is None:
                return None
            self.status_item = None
            self.status_menu_item = None
            self.restart_menu_item = None
            self.root_path = None
            self.busy = False
            self.notified_ready = False
            return self

        def applicationDidFinishLaunching_(self, _notification):
            Foundation.NSProcessInfo.processInfo().setProcessName_("Humanizer")
            AppKit.NSApp.setActivationPolicy_(
                AppKit.NSApplicationActivationPolicyRegular
            )
            self.buildStatusItem()
            self.startServerAsync()
            self.scheduleHealthTimer()
            notify_user(
                "Humanizer is running",
                'Look for "Hz" near the clock (top-right). Click the Dock icon anytime for a tip.',
            )

        def applicationShouldHandleReopen_hasVisibleWindows_(self, _app, _flag):
            notify_user(
                "Humanizer",
                'No window — use the "Hz" item in the menu bar (top-right).',
            )
            self.popStatusMenu()
            return True

        def buildStatusItem(self):
            bar = AppKit.NSStatusBar.systemStatusBar()
            item = bar.statusItemWithLength_(AppKit.NSVariableStatusItemLength)
            button = item.button()
            if button is not None:
                button.setTitle_("Hz…")
                button.setToolTip_("Humanizer — local writing server")
            menu = AppKit.NSMenu.alloc().init()

            self.status_menu_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Status: Checking…", None, ""
            )
            self.status_menu_item.setEnabled_(False)
            menu.addItem_(self.status_menu_item)
            menu.addItem_(AppKit.NSMenuItem.separatorItem())

            self.restart_menu_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Restart server", "onRestart:", ""
            )
            self.restart_menu_item.setTarget_(self)
            menu.addItem_(self.restart_menu_item)

            quit_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Quit Humanizer", "onQuit:", "q"
            )
            quit_item.setTarget_(self)
            menu.addItem_(quit_item)

            item.setMenu_(menu)
            self.status_item = item
            logger.info("Menu bar status item created: %s", type(item).__name__)

        def popStatusMenu(self):
            try:
                button = self.status_item.button() if self.status_item else None
                if button is not None:
                    button.performClick_(None)
            except Exception:  # noqa: BLE001
                pass

        def scheduleHealthTimer(self):
            Foundation.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                4.0, self, "onHealthTick:", None, True
            )
            self.onHealthTick_(None)

        def onHealthTick_(self, _timer):
            if self.busy:
                return
            snap = manager.check_health()
            self.applyHealth_detail_(snap.server_ok, snap.detail)

        def applyHealth_detail_(self, online, detail):
            if self.status_menu_item is not None:
                self.status_menu_item.setTitle_(f"Status: {detail}")
            button = self.status_item.button() if self.status_item else None
            if button is not None:
                button.setTitle_("Hz" if online else "Hz…")
            if online and not self.notified_ready:
                self.notified_ready = True
                notify_user(
                    "Server online",
                    'Humanizer is ready — look for "Hz" in the menu bar.',
                )

        def startServerAsync(self):
            def work():
                try:
                    manager.ensure_ollama_running()
                    manager.start_server(self.root_path)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Startup failed: %s", exc)

            threading.Thread(target=work, daemon=True).start()

        def onRestart_(self, _sender):
            if self.busy:
                return
            self.busy = True
            if self.status_menu_item is not None:
                self.status_menu_item.setTitle_("Status: Restarting…")
            button = self.status_item.button() if self.status_item else None
            if button is not None:
                button.setTitle_("Hz…")

            def work():
                try:
                    ok = manager.restart_server(self.root_path)
                    detail = "Server online" if ok else "Server offline"
                    if not ok:
                        notify_user(
                            "Could not start server",
                            "Check that Ollama is installed and open.",
                        )
                    AppHelper.callAfter(self.applyHealth_detail_, ok, detail)
                finally:
                    self.busy = False

            threading.Thread(target=work, daemon=True).start()

        def onQuit_(self, _sender):
            AppKit.NSApp.terminate_(None)

    app = AppKit.NSApplication.sharedApplication()
    delegate = AppDelegate.alloc().init()
    delegate.root_path = root
    app.setDelegate_(delegate)
    # Ensure finish-launching runs even when started without a normal GUI session.
    AppKit.NSApp.finishLaunching()
    AppHelper.runEventLoop()


def bootstrap_root() -> Path:
    resources = Path(os.environ.get("HUMANIZER_BUNDLE_RESOURCES", "")).expanduser()
    if resources.is_dir() and (resources / "HumanizerHome" / "server.py").is_file():
        return manager.ensure_home_payload(resources)
    return manager.resolve_project_root()


if __name__ == "__main__":
    main()
