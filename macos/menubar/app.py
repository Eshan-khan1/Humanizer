"""Humanizer macOS app — control window + right-side menu bar icon."""

from __future__ import annotations

import logging
import os
import platform
import sys
import threading
from pathlib import Path

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

# Claude-inspired tokens from Humanizer ui theme.json
_BG = (0.941, 0.925, 0.878, 1.0)  # #F0ECE0
_CARD = (1.0, 1.0, 1.0, 1.0)
_TEXT = (0.102, 0.102, 0.094, 1.0)  # #1a1a18
_MUTED = (0.357, 0.349, 0.314, 1.0)  # #5b5950
_ACCENT = (0.788, 0.392, 0.259, 1.0)  # #c96442
_OK = (0.23, 0.60, 0.40, 1.0)
_OFF = (0.55, 0.52, 0.48, 1.0)


def _reexec_native_if_needed() -> None:
    if not manager.hardware_is_apple_silicon():
        return
    if platform.machine() == "arm64":
        return
    exe = manager.preferred_host_python()
    logger.info("Re-exec under arm64 with %s (was %s)", exe, sys.executable)
    os.execv(str(exe), [str(exe), "-m", "macos.menubar.app", *sys.argv[1:]])


_reexec_native_if_needed()


def bootstrap_root() -> Path:
    resources = Path(os.environ.get("HUMANIZER_BUNDLE_RESOURCES", "")).expanduser()
    if resources.is_dir() and (resources / "HumanizerHome" / "server.py").is_file():
        return manager.ensure_home_payload(resources)
    return manager.resolve_project_root()


def _icon_dir() -> Path:
    base = Path(__file__).resolve().parent / "icons"
    write_status_icons(base)
    return base


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

    icon_dir = _icon_dir()
    online_icon_path = str(icon_dir / "status-online.png")
    offline_icon_path = str(icon_dir / "status-offline.png")
    mark_path = str(icon_dir / "humanizer-mark.png")

    def color(rgba):
        r, g, b, a = rgba
        return AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)

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

    def load_template_image(path: str):
        image = AppKit.NSImage.alloc().initWithContentsOfFile_(path)
        if image is None:
            return None
        image.setTemplate_(True)
        image.setSize_((18.0, 18.0))
        return image

    class AppDelegate(Foundation.NSObject):
        def init(self):
            self = objc.super(AppDelegate, self).init()
            if self is None:
                return None
            self.status_item = None
            self.status_menu_item = None
            self.window = None
            self.brand_label = None
            self.status_title = None
            self.status_detail = None
            self.status_dot = None
            self.power_switch = None
            self.mark_view = None
            self.root_path = None
            self.busy = False
            self.notified_ready = False
            self.server_online = False
            self.online_image = load_template_image(online_icon_path)
            self.offline_image = load_template_image(offline_icon_path)
            return self

        def applicationDidFinishLaunching_(self, _notification):
            Foundation.NSProcessInfo.processInfo().setProcessName_("Humanizer")
            AppKit.NSApp.setActivationPolicy_(
                AppKit.NSApplicationActivationPolicyRegular
            )
            self.buildMainWindow()
            self.buildStatusItem()
            self.startServerAsync()
            self.scheduleHealthTimer()
            self.showMainWindow()

        def applicationShouldHandleReopen_hasVisibleWindows_(self, _app, has_visible):
            self.showMainWindow()
            return True

        def applicationShouldTerminateAfterLastWindowClosed_(self, _app):
            # Closing the window keeps the menu-bar icon / server alive.
            return False

        def buildMainWindow(self):
            style = (
                AppKit.NSWindowStyleMaskTitled
                | AppKit.NSWindowStyleMaskClosable
                | AppKit.NSWindowStyleMaskMiniaturizable
            )
            frame = Foundation.NSMakeRect(0, 0, 420, 280)
            window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                frame,
                style,
                AppKit.NSBackingStoreBuffered,
                False,
            )
            window.setTitle_("Humanizer")
            window.setBackgroundColor_(color(_BG))
            window.center()
            window.setReleasedWhenClosed_(False)

            content = window.contentView()

            # Brand mark (left)
            mark = AppKit.NSImageView.alloc().initWithFrame_(
                Foundation.NSMakeRect(28, 188, 56, 56)
            )
            mark_img = AppKit.NSImage.alloc().initWithContentsOfFile_(mark_path)
            if mark_img is not None:
                mark.setImage_(mark_img)
            mark.setImageScaling_(AppKit.NSImageScaleProportionallyUpOrDown)
            content.addSubview_(mark)
            self.mark_view = mark

            # Title
            title = AppKit.NSTextField.labelWithString_("Humanizer")
            title.setFont_(
                AppKit.NSFont.fontWithName_size_("Georgia", 28.0)
                or AppKit.NSFont.systemFontOfSize_weight_(28.0, AppKit.NSFontWeightRegular)
            )
            title.setTextColor_(color(_TEXT))
            title.setFrame_(Foundation.NSMakeRect(98, 214, 200, 34))
            content.addSubview_(title)
            self.brand_label = title

            subtitle = AppKit.NSTextField.labelWithString_("Local writing server")
            subtitle.setFont_(AppKit.NSFont.systemFontOfSize_(13.0))
            subtitle.setTextColor_(color(_MUTED))
            subtitle.setFrame_(Foundation.NSMakeRect(98, 192, 200, 20))
            content.addSubview_(subtitle)

            # Power / status cluster on the RIGHT
            right_x = 300
            status_caption = AppKit.NSTextField.labelWithString_("Server")
            status_caption.setFont_(AppKit.NSFont.systemFontOfSize_(11.0))
            status_caption.setTextColor_(color(_MUTED))
            status_caption.setAlignment_(AppKit.NSTextAlignmentRight)
            status_caption.setFrame_(Foundation.NSMakeRect(right_x, 232, 90, 16))
            content.addSubview_(status_caption)

            switch = AppKit.NSSwitch.alloc().initWithFrame_(
                Foundation.NSMakeRect(right_x + 48, 200, 51, 31)
            )
            switch.setTarget_(self)
            switch.setAction_("onPowerToggle:")
            content.addSubview_(switch)
            self.power_switch = switch

            # Card
            card = AppKit.NSView.alloc().initWithFrame_(
                Foundation.NSMakeRect(28, 72, 364, 100)
            )
            card.setWantsLayer_(True)
            card.layer().setBackgroundColor_(color(_CARD).CGColor())
            card.layer().setCornerRadius_(14.0)
            content.addSubview_(card)

            dot = AppKit.NSView.alloc().initWithFrame_(
                Foundation.NSMakeRect(20, 58, 12, 12)
            )
            dot.setWantsLayer_(True)
            dot.layer().setCornerRadius_(6.0)
            dot.layer().setBackgroundColor_(color(_OFF).CGColor())
            card.addSubview_(dot)
            self.status_dot = dot

            status_title = AppKit.NSTextField.labelWithString_("Checking…")
            status_title.setFont_(
                AppKit.NSFont.systemFontOfSize_weight_(16.0, AppKit.NSFontWeightMedium)
            )
            status_title.setTextColor_(color(_TEXT))
            status_title.setFrame_(Foundation.NSMakeRect(44, 52, 280, 24))
            card.addSubview_(status_title)
            self.status_title = status_title

            status_detail = AppKit.NSTextField.labelWithString_(
                "Starting Ollama and the grammar server…"
            )
            status_detail.setFont_(AppKit.NSFont.systemFontOfSize_(12.0))
            status_detail.setTextColor_(color(_MUTED))
            status_detail.setFrame_(Foundation.NSMakeRect(44, 28, 300, 20))
            card.addSubview_(status_detail)
            self.status_detail = status_detail

            restart = AppKit.NSButton.buttonWithTitle_target_action_(
                "Restart server", self, "onRestart:"
            )
            restart.setBezelStyle_(AppKit.NSBezelStyleRounded)
            restart.setFrame_(Foundation.NSMakeRect(28, 24, 140, 32))
            content.addSubview_(restart)

            quit_btn = AppKit.NSButton.buttonWithTitle_target_action_(
                "Quit", self, "onQuit:"
            )
            quit_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
            quit_btn.setFrame_(Foundation.NSMakeRect(180, 24, 80, 32))
            content.addSubview_(quit_btn)

            tip = AppKit.NSTextField.labelWithString_(
                "On macOS 26: System Settings → Menu Bar → turn Humanizer ON."
            )
            tip.setFont_(AppKit.NSFont.systemFontOfSize_(11.0))
            tip.setTextColor_(color(_MUTED))
            tip.setFrame_(Foundation.NSMakeRect(28, 4, 364, 16))
            content.addSubview_(tip)

            menu_bar_btn = AppKit.NSButton.buttonWithTitle_target_action_(
                "Add to Menu Bar…", self, "openMenuBarSettings:"
            )
            menu_bar_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
            menu_bar_btn.setFrame_(Foundation.NSMakeRect(268, 24, 124, 32))
            content.addSubview_(menu_bar_btn)

            self.window = window

        def showMainWindow(self):
            if self.window is None:
                return
            self.window.makeKeyAndOrderFront_(None)
            AppKit.NSApp.activateIgnoringOtherApps_(True)

        def buildStatusItem(self):
            # Registers with the system menu bar (right side, near the clock).
            # autosaveName lets macOS Menu Bar / Control Center remember visibility.
            bar = AppKit.NSStatusBar.systemStatusBar()
            item = bar.statusItemWithLength_(AppKit.NSVariableStatusItemLength)
            try:
                item.setAutosaveName_("com.humanizer.menubar.statusItem")
            except Exception:  # noqa: BLE001
                logger.warning("Could not set status item autosaveName")
            try:
                item.setVisible_(True)
            except Exception:  # noqa: BLE001
                pass

            button = item.button()
            if button is not None:
                if self.offline_image is not None:
                    button.setImage_(self.offline_image)
                    button.setTitle_("")
                else:
                    button.setTitle_("Hz")
                button.setToolTip_("Humanizer — local writing server")

            menu = AppKit.NSMenu.alloc().init()

            self.status_menu_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Status: Checking…", None, ""
            )
            self.status_menu_item.setEnabled_(False)
            menu.addItem_(self.status_menu_item)
            menu.addItem_(AppKit.NSMenuItem.separatorItem())

            open_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Open Humanizer", "showWindow:", ""
            )
            open_item.setTarget_(self)
            menu.addItem_(open_item)

            settings_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Menu Bar Settings…", "openMenuBarSettings:", ""
            )
            settings_item.setTarget_(self)
            menu.addItem_(settings_item)

            restart_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Restart server", "onRestart:", ""
            )
            restart_item.setTarget_(self)
            menu.addItem_(restart_item)
            menu.addItem_(AppKit.NSMenuItem.separatorItem())

            quit_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Quit Humanizer", "onQuit:", "q"
            )
            quit_item.setTarget_(self)
            menu.addItem_(quit_item)

            item.setMenu_(menu)
            self.status_item = item
            logger.info(
                "Menu bar status item registered (autosaveName=com.humanizer.menubar.statusItem)"
            )
            # After Control Center settles, warn if macOS is still hiding the icon.
            Foundation.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1.2, self, "checkStatusItemVisibility:", None, False
            )

        def openMenuBarSettings_(self, _sender):
            # Opens System Settings where the user can enable Humanizer in the menu bar.
            opened = False
            for url in (
                "x-apple.systempreferences:com.apple.ControlCenter-Settings.extension",
                "x-apple.systempreferences:com.apple.preference.dock?MenuBar",
            ):
                try:
                    ok = AppKit.NSWorkspace.sharedWorkspace().openURL_(
                        Foundation.NSURL.URLWithString_(url)
                    )
                    if ok:
                        opened = True
                        break
                except Exception:  # noqa: BLE001
                    continue
            if not opened:
                AppKit.NSWorkspace.sharedWorkspace().launchApplication_("System Settings")
            notify_user(
                "Add Humanizer to the menu bar",
                "In System Settings, open Menu Bar (or Control Center) and turn Humanizer ON / Show in Menu Bar.",
            )

        def checkStatusItemVisibility_(self, _timer):
            item = self.status_item
            if item is None:
                return
            visible = True
            try:
                visible = bool(item.isVisible())
            except Exception:  # noqa: BLE001
                visible = True
            button = item.button()
            screen = None
            try:
                if button is not None:
                    screen = button.window().screen() if button.window() else None
            except Exception:  # noqa: BLE001
                screen = None
            if visible and screen is not None:
                logger.info("Menu bar icon is visible on screen")
                return
            logger.warning(
                "Menu bar icon may be hidden by macOS (visible=%s screen=%s)",
                visible,
                screen,
            )
            alert = AppKit.NSAlert.alloc().init()
            alert.setMessageText_("Show Humanizer in the menu bar")
            alert.setInformativeText_(
                "macOS may be hiding the Humanizer icon.\n\n"
                "1. Open System Settings → Menu Bar (or Control Center)\n"
                "2. Find Humanizer\n"
                "3. Turn it ON / set “Show in Menu Bar”\n\n"
                "You can also click “Add to Menu Bar…” in the Humanizer window."
            )
            alert.addButtonWithTitle_("Open Settings")
            alert.addButtonWithTitle_("Later")
            response = alert.runModal()
            if response == AppKit.NSAlertFirstButtonReturn:
                self.openMenuBarSettings_(None)

        def showWindow_(self, _sender):
            self.showMainWindow()

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
            self.server_online = bool(online)
            if self.status_menu_item is not None:
                self.status_menu_item.setTitle_(f"Status: {detail}")

            button = self.status_item.button() if self.status_item else None
            if button is not None:
                img = self.online_image if online else self.offline_image
                if img is not None:
                    button.setImage_(img)
                    button.setTitle_("")
                else:
                    button.setTitle_("Hz" if online else "Hz…")

            if self.power_switch is not None:
                self.power_switch.setState_(
                    AppKit.NSControlStateValueOn if online else AppKit.NSControlStateValueOff
                )
            if self.status_title is not None:
                self.status_title.setStringValue_(
                    "Server online" if online else "Server offline"
                )
            if self.status_detail is not None:
                self.status_detail.setStringValue_(str(detail))
            if self.status_dot is not None and self.status_dot.layer() is not None:
                self.status_dot.layer().setBackgroundColor_(
                    color(_OK if online else _OFF).CGColor()
                )

            if online and not self.notified_ready:
                self.notified_ready = True
                notify_user("Server online", "Humanizer is ready.")

        def startServerAsync(self):
            def work():
                try:
                    manager.ensure_ollama_running()
                    manager.start_server(self.root_path)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Startup failed: %s", exc)

            threading.Thread(target=work, daemon=True).start()

        def onPowerToggle_(self, sender):
            # Switch on the right: ON starts/restarts, OFF stops the local server.
            if self.busy:
                return
            want_on = sender.state() == AppKit.NSControlStateValueOn
            self.busy = True

            def work():
                try:
                    if want_on:
                        ok = manager.restart_server(self.root_path)
                        detail = "Server online" if ok else "Server offline"
                    else:
                        manager.stop_server()
                        ok = False
                        detail = "Server offline"
                    AppHelper.callAfter(self.applyHealth_detail_, ok, detail)
                finally:
                    self.busy = False

            threading.Thread(target=work, daemon=True).start()

        def onRestart_(self, _sender):
            if self.busy:
                return
            self.busy = True
            if self.status_title is not None:
                self.status_title.setStringValue_("Restarting…")

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
    AppKit.NSApp.finishLaunching()
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
