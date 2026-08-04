import Cocoa
import Darwin
import Foundation
import QuartzCore
import ServiceManagement

private let accent = NSColor(calibratedRed: 1.0, green: 1.0, blue: 1.0, alpha: 1) // #FFFFFF
private let bg = NSColor(calibratedRed: 0.0, green: 0.0, blue: 0.0, alpha: 1) // #000000
private let textColor = NSColor(calibratedRed: 1.0, green: 1.0, blue: 1.0, alpha: 1) // #FFFFFF
private let muted = NSColor(calibratedRed: 0.663, green: 0.663, blue: 0.663, alpha: 1) // #A9A9A9
private let okColor = NSColor(calibratedRed: 0.024, green: 0.757, blue: 0.404, alpha: 1) // #06C167
private let offlineColor = NSColor(calibratedRed: 0.882, green: 0.098, blue: 0.0, alpha: 1) // #E11900
private let offColor = NSColor(calibratedRed: 0.478, green: 0.478, blue: 0.478, alpha: 1) // #7A7A7A
private let surface = NSColor(calibratedRed: 0.122, green: 0.122, blue: 0.122, alpha: 1) // #1F1F1F
private let inverse = NSColor(calibratedRed: 0.0, green: 0.0, blue: 0.0, alpha: 1) // #000000

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private var statusItem: NSStatusItem!
    private var window: NSWindow!
    private var settingsWindow: NSWindow!
    private var menuBarSheet: NSWindow!
    private var statusTitle: NSTextField!
    private var statusDetail: NSTextField!
    private var statusDot: NSView!
    private var statusCard: NSView!
    private var statusFill: NSView!
    private var restartButton: NSButton!
    private var restartSpinner: NSProgressIndicator!
    private var powerSwitch: NSSwitch!
    private var grammarPopup: NSPopUpButton!
    private var writingPopup: NSPopUpButton!
    private var modelsHelpLabel: NSTextField!
    private var aiProviderControl: NSSegmentedControl!
    private var aiApiKeyField: NSSecureTextField!
    private var aiBaseUrlField: NSTextField!
    private var aiHelpLabel: NSTextField!
    private var aiConnectedTag: NSView!
    private var aiConnectedTagLabel: NSTextField!
    private var settingsLocalCard: NSView!
    private var settingsApiCard: NSView!
    private var settingsHardwareCard: NSView!
    private var settingsFeaturesCard: NSView!
    private var settingsChromeCard: NSView!
    private var ramSlider: NSSlider!
    private var gpuSlider: NSSlider!
    private var ramValueLabel: NSTextField!
    private var gpuValueLabel: NSTextField!
    private var tokensEstimateLabel: NSTextField!
    private var hardwareHelpLabel: NSTextField!
    private var hardwareSummaryLabel: NSTextField!
    private var hardwareRecommendLabel: NSTextField!
    private var recommendedRamGB: Int = 8
    private var recommendedGpuPercent: Int = 75
    private var systemRamGB: Int = 16
    private var refreshModelsButton: NSButton!
    private var applyModelsButton: NSButton!
    private var saveApiButton: NSButton!
    private var settingsDoneButton: NSButton!
    private var featureGrammarSwitch: NSSwitch!
    private var featureRewriteSwitch: NSSwitch!
    private var featureGenerateSwitch: NSSwitch!
    private var featuresHelpLabel: NSTextField!
    private var featuresSummaryLabel: NSTextField!
    private var settingsRootView: NSView!
    private var settingsFeaturesView: NSView!
    private var settingsHardwareView: NSView!
    private var menuBarBanner: NSView!
    private var menuBarConnectButton: NSButton!
    private var chromeConnectButton: NSButton!
    private var chromeConnectSheet: NSWindow!
    private var chromeConnectPathLabel: NSTextField!
    private var bgStatusLabel: NSTextField!
    private var busy = false
    /// Prevents programmatic power-switch updates from firing stop/start.
    private var syncingPowerSwitch = false
    private var online = false
    private var aiConfiguredCached = false
    private var availableModels: [String] = []
    private var modelLabels: [String: String] = [:]
    private var selectedGrammar = "thoth-grammar"
    private var selectedWriting = "thoth-writing"
    private var menuBarPromptPresented = false
    private var lastStatusRecreate = Date.distantPast
    private var didAutoResetControlCenter = false
    private var menuBarAutoConnectRunning = false

    private let defaults = UserDefaults.standard
    private let menuBarAckKey = "thoth.menuBar.acknowledged"

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        ProcessInfo.processInfo.processName = "Thoth"
        setupMainMenu()
        setupStatusItem()
        setupWindow()
        setupSettingsWindow()
        setupMenuBarConnectSheet()
        setupChromeConnectSheet()
        // Keep the window available, but prioritize attaching the menu bar icon first.
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        // Register with macOS Login Items & Background Activity (SMAppService).
        let regKey = "thoth.background.reregistered.v3"
        let force = !defaults.bool(forKey: regKey)
        let summary = registerBackgroundActivity(forceReregister: force)
        if force { defaults.set(true, forKey: regKey) }
        bgStatusLabel?.stringValue = "Background status: \(summary)"
        DispatchQueue.global(qos: .utility).async { [weak self] in
            _ = self?.runService(["autostart"])
            // Sync Chrome extension + register native messaging host on every launch.
            _ = self?.runService(["connect-extension"])
        }
        startServerAsync()
        Timer.scheduledTimer(withTimeInterval: 4.0, repeats: true) { [weak self] _ in
            guard let self else { return }
            self.refreshHealth()
            self.statusItem.isVisible = true
            self.updateMenuBarBanner()
            self.bgStatusLabel?.stringValue = "Background status: \(self.backgroundStatusSummary())"
            // Quiet reconnect if the icon slips off-screen — don't keep reopening Settings.
            if !self.isMenuBarItemShowing(), !self.menuBarAutoConnectRunning {
                self.lastStatusRecreate = Date()
                self.recreateStatusItem()
                if !self.isMenuBarItemShowing() {
                    self.softResetMenuBarPlacement()
                }
            }
        }
        refreshHealth()
        // Automatically attach to the menu bar on open — only show a prompt if
        // macOS still blocks after silent recovery.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
            self?.autoConnectMenuBar(attempt: 1)
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        autoConnectMenuBar(attempt: 1)
        return true
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    /// Menu-bar (LSUIElement) apps get no Edit menu by default, so ⌘C/⌘V fail in text fields.
    private func setupMainMenu() {
        let mainMenu = NSMenu()

        let appItem = NSMenuItem()
        mainMenu.addItem(appItem)
        let appMenu = NSMenu()
        appItem.submenu = appMenu
        appMenu.addItem(withTitle: "About Thoth", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Settings…", action: #selector(showSettings), keyEquivalent: ",")
        appMenu.addItem(.separator())
        let hideItem = appMenu.addItem(withTitle: "Hide Thoth", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        hideItem.keyEquivalentModifierMask = .command
        let hideOthers = appMenu.addItem(
            withTitle: "Hide Others",
            action: #selector(NSApplication.hideOtherApplications(_:)),
            keyEquivalent: "h"
        )
        hideOthers.keyEquivalentModifierMask = [.command, .option]
        appMenu.addItem(withTitle: "Show All", action: #selector(NSApplication.unhideAllApplications(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit Thoth", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")

        let editItem = NSMenuItem()
        mainMenu.addItem(editItem)
        let editMenu = NSMenu(title: "Edit")
        editItem.submenu = editMenu
        editMenu.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        editMenu.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "Z")
        editMenu.addItem(.separator())
        editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Delete", action: #selector(NSText.delete(_:)), keyEquivalent: "")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")

        let windowItem = NSMenuItem()
        mainMenu.addItem(windowItem)
        let windowMenu = NSMenu(title: "Window")
        windowItem.submenu = windowMenu
        windowMenu.addItem(withTitle: "Close", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        windowMenu.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        NSApp.windowsMenu = windowMenu

        NSApp.mainMenu = mainMenu
    }

    private func setupStatusItem() {
        // Do NOT set autosaveName — on macOS 26 StatusKit often restores an off-screen
        // y=-17 frame from a prior blocked launch, so the icon never becomes visible.
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        item.isVisible = true
        configureStatusButton(item.button, online: online)

        let menu = NSMenu()
        let status = NSMenuItem(title: "Status: Checking…", action: nil, keyEquivalent: "")
        status.isEnabled = false
        status.tag = 100
        menu.addItem(status)
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Open Thoth", action: #selector(showWindow), keyEquivalent: "o"))
        menu.addItem(NSMenuItem(title: "Settings…", action: #selector(showSettings), keyEquivalent: ","))
        menu.addItem(NSMenuItem(title: "Add to Menu Bar…", action: #selector(openMenuBarSettings), keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "Restart server", action: #selector(restartServer), keyEquivalent: "r"))
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Quit Thoth", action: #selector(quitApp), keyEquivalent: "q"))
        item.menu = menu
        statusItem = item
        logMenuBarGeometry("setup")
    }

    private func configureStatusButton(_ button: NSStatusBarButton?, online: Bool) {
        guard let button else { return }
        if let image = loadTemplateIcon(named: online ? "status-online" : "status-offline") {
            image.isTemplate = true
            button.image = image
            button.imagePosition = .imageOnly
            button.title = ""
        } else {
            // Fallback letter if icons are missing.
            button.title = "H"
            button.image = nil
        }
        button.toolTip = "Thoth — local writing server"
        button.appearsDisabled = false
        button.setAccessibilityTitle("Thoth")
    }

    private func setupWindow() {
        let rect = NSRect(x: 0, y: 0, width: 420, height: 330)
        let style: NSWindow.StyleMask = [.titled, .closable, .miniaturizable]
        let win = NSWindow(contentRect: rect, styleMask: style, backing: .buffered, defer: false)
        win.title = "Thoth"
        win.backgroundColor = bg
        win.isReleasedWhenClosed = false
        win.center()
        win.delegate = self

        guard let content = win.contentView else { return }

        let mark = NSImageView(frame: NSRect(x: 28, y: 238, width: 56, height: 56))
        mark.image = loadBrandMark()
        mark.imageScaling = .scaleProportionallyUpOrDown
        content.addSubview(mark)

        let title = NSTextField(labelWithString: "Thoth")
        title.font = .systemFont(ofSize: 28, weight: .bold)
        title.textColor = textColor
        title.frame = NSRect(x: 98, y: 264, width: 180, height: 34)
        content.addSubview(title)

        let subtitle = NSTextField(labelWithString: "Local writing server")
        subtitle.font = .systemFont(ofSize: 13)
        subtitle.textColor = muted
        subtitle.frame = NSRect(x: 98, y: 242, width: 200, height: 20)
        content.addSubview(subtitle)

        // Top-right settings gear
        let settings = NSButton(frame: NSRect(x: 372, y: 274, width: 28, height: 28))
        settings.bezelStyle = .inline
        settings.isBordered = false
        settings.imagePosition = .imageOnly
        settings.imageScaling = .scaleProportionallyDown
        if let gear = NSImage(systemSymbolName: "gearshape", accessibilityDescription: "Settings") {
            let cfg = NSImage.SymbolConfiguration(pointSize: 15, weight: .medium)
            settings.image = gear.withSymbolConfiguration(cfg)
        } else {
            settings.title = "⚙︎"
        }
        settings.contentTintColor = muted
        settings.target = self
        settings.action = #selector(showSettings)
        settings.toolTip = "Settings"
        settings.setAccessibilityLabel("Settings")
        content.addSubview(settings)

        let serverCaption = NSTextField(labelWithString: "Server")
        serverCaption.font = .systemFont(ofSize: 11)
        serverCaption.textColor = muted
        serverCaption.alignment = .right
        serverCaption.frame = NSRect(x: 268, y: 282, width: 90, height: 16)
        content.addSubview(serverCaption)

        let power = NSSwitch(frame: NSRect(x: 316, y: 250, width: 51, height: 31))
        power.target = self
        power.action = #selector(powerToggled(_:))
        content.addSubview(power)
        powerSwitch = power

        let card = NSView(frame: NSRect(x: 28, y: 122, width: 364, height: 100))
        card.wantsLayer = true
        card.layer?.backgroundColor = surface.cgColor
        card.layer?.cornerRadius = 14
        card.layer?.masksToBounds = true
        content.addSubview(card)
        statusCard = card

        // Green fill used for online state and the restart “charging” animation.
        let fill = NSView(frame: NSRect(x: 0, y: 0, width: 0, height: 100))
        fill.wantsLayer = true
        fill.layer?.backgroundColor = okColor.cgColor
        fill.autoresizingMask = []
        card.addSubview(fill)
        statusFill = fill

        let dot = NSView(frame: NSRect(x: 20, y: 58, width: 12, height: 12))
        dot.wantsLayer = true
        dot.layer?.cornerRadius = 6
        dot.layer?.backgroundColor = offColor.cgColor
        card.addSubview(dot)
        statusDot = dot

        let st = NSTextField(labelWithString: "Checking…")
        st.font = .systemFont(ofSize: 16, weight: .medium)
        st.textColor = textColor
        st.frame = NSRect(x: 44, y: 52, width: 250, height: 24)
        card.addSubview(st)
        statusTitle = st

        let detail = NSTextField(labelWithString: "Starting Ollama and the grammar server…")
        detail.font = .systemFont(ofSize: 12)
        detail.textColor = muted
        detail.frame = NSRect(x: 44, y: 28, width: 250, height: 20)
        card.addSubview(detail)
        statusDetail = detail

        // Restart icon on the right side of the Server online card
        let restart = NSButton(frame: NSRect(x: 318, y: 36, width: 30, height: 30))
        restart.bezelStyle = .inline
        restart.isBordered = false
        restart.imagePosition = .imageOnly
        restart.imageScaling = .scaleProportionallyDown
        if let icon = NSImage(systemSymbolName: "arrow.clockwise", accessibilityDescription: "Restart server") {
            let cfg = NSImage.SymbolConfiguration(pointSize: 14, weight: .semibold)
            restart.image = icon.withSymbolConfiguration(cfg)
        } else {
            restart.title = "↻"
        }
        restart.contentTintColor = muted
        restart.target = self
        restart.action = #selector(restartServer)
        restart.toolTip = "Restart server"
        restart.setAccessibilityLabel("Restart server")
        card.addSubview(restart)
        restartButton = restart

        let spinner = NSProgressIndicator(frame: NSRect(x: 320, y: 40, width: 24, height: 24))
        spinner.style = .spinning
        spinner.controlSize = .small
        spinner.isDisplayedWhenStopped = false
        spinner.isHidden = true
        card.addSubview(spinner)
        restartSpinner = spinner

        let connect = NSButton(title: "Connect Menu Bar…", target: self, action: #selector(showMenuBarConnect))
        connect.bezelStyle = .rounded
        connect.frame = NSRect(x: 28, y: 74, width: 170, height: 32)
        content.addSubview(connect)
        menuBarConnectButton = connect

        // Banner shown when macOS is still blocking the status item.
        let banner = NSView(frame: NSRect(x: 28, y: 36, width: 364, height: 26))
        banner.wantsLayer = true
        banner.layer?.backgroundColor = accent.withAlphaComponent(0.14).cgColor
        banner.layer?.cornerRadius = 8
        banner.isHidden = true
        content.addSubview(banner)
        menuBarBanner = banner

        let bannerText = NSTextField(labelWithString: "Menu bar icon is hidden — click Connect Menu Bar…")
        bannerText.font = .systemFont(ofSize: 11, weight: .medium)
        bannerText.textColor = textColor
        bannerText.frame = NSRect(x: 10, y: 4, width: 344, height: 18)
        banner.addSubview(bannerText)

        window = win
    }

    private func setupMenuBarConnectSheet() {
        let rect = NSRect(x: 0, y: 0, width: 460, height: 400)
        let win = NSWindow(
            contentRect: rect,
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        win.title = "Allow Background Activity"
        win.backgroundColor = bg
        win.isReleasedWhenClosed = false
        win.center()
        win.level = .floating

        guard let content = win.contentView else {
            menuBarSheet = win
            return
        }

        let icon = NSImageView(frame: NSRect(x: 202, y: 312, width: 56, height: 56))
        icon.image = loadBrandMark()
        icon.imageScaling = .scaleProportionallyUpOrDown
        content.addSubview(icon)

        let title = NSTextField(labelWithString: "Allow Thoth in Background?")
        title.font = .systemFont(ofSize: 20, weight: .bold)
        title.textColor = textColor
        title.alignment = .center
        title.frame = NSRect(x: 28, y: 272, width: 404, height: 28)
        content.addSubview(title)

        let body = NSTextField(wrappingLabelWithString: "macOS requires two permissions for menu bar apps: Background Activity (so Thoth can stay running) and Menu Bar (so the H icon can appear near the clock).")
        body.font = .systemFont(ofSize: 13)
        body.textColor = muted
        body.alignment = .center
        body.frame = NSRect(x: 36, y: 200, width: 388, height: 64)
        content.addSubview(body)

        let stepsCard = NSView(frame: NSRect(x: 36, y: 108, width: 388, height: 84))
        stepsCard.wantsLayer = true
        stepsCard.layer?.backgroundColor = surface.cgColor
        stepsCard.layer?.cornerRadius = 12
        content.addSubview(stepsCard)

        let steps = NSTextField(wrappingLabelWithString: "macOS parked this icon off-screen (StatusKit bug).\n1. Click Fix Menu Bar Icon\n2. In Menu Bar settings turn Thoth OFF, then ON\n3. Look for the H near the clock")
        steps.font = .systemFont(ofSize: 12)
        steps.textColor = textColor
        steps.frame = NSRect(x: 16, y: 10, width: 356, height: 70)
        stepsCard.addSubview(steps)

        let status = NSTextField(labelWithString: "Background status: checking…")
        status.font = .systemFont(ofSize: 11)
        status.textColor = muted
        status.alignment = .center
        status.frame = NSRect(x: 36, y: 88, width: 388, height: 16)
        content.addSubview(status)
        bgStatusLabel = status

        let fix = NSButton(title: "Fix Menu Bar Icon", target: self, action: #selector(fixMenuBarIcon))
        fix.bezelStyle = .rounded
        fix.keyEquivalent = "\r"
        fix.frame = NSRect(x: 36, y: 52, width: 160, height: 32)
        if #available(macOS 11.0, *) {
            fix.contentTintColor = accent
        }
        content.addSubview(fix)

        let openMenu = NSButton(title: "Menu Bar…", target: self, action: #selector(openMenuBarSettingsFromPrompt))
        openMenu.bezelStyle = .rounded
        openMenu.frame = NSRect(x: 204, y: 52, width: 100, height: 32)
        content.addSubview(openMenu)

        let openBg = NSButton(title: "Background…", target: self, action: #selector(openBackgroundActivityFromPrompt))
        openBg.bezelStyle = .rounded
        openBg.frame = NSRect(x: 312, y: 52, width: 110, height: 32)
        content.addSubview(openBg)

        let later = NSButton(title: "Not Now", target: self, action: #selector(dismissMenuBarConnect))
        later.bezelStyle = .rounded
        later.frame = NSRect(x: 36, y: 18, width: 100, height: 28)
        content.addSubview(later)

        let check = NSButton(title: "I’ve allowed it — check again", target: self, action: #selector(recheckMenuBarAfterAllow))
        check.bezelStyle = .recessed
        check.isBordered = false
        check.frame = NSRect(x: 150, y: 22, width: 260, height: 20)
        content.addSubview(check)

        menuBarSheet = win
    }

    /// Registers Thoth with System Settings → Login Items & Background Activity.
    @discardableResult
    private func registerBackgroundActivity(forceReregister: Bool = false) -> String {
        // Drop the old silent LaunchAgent — confuses Background Task Management.
        let home = FileManager.default.homeDirectoryForCurrentUser
        // Prefer Thoth Application Support; migrate from Humanizer once.
        let thothSupport = home.appendingPathComponent("Library/Application Support/Thoth")
        let humanizerSupport = home.appendingPathComponent("Library/Application Support/Humanizer")
        if !FileManager.default.fileExists(atPath: thothSupport.path),
           FileManager.default.fileExists(atPath: humanizerSupport.path) {
            try? FileManager.default.moveItem(at: humanizerSupport, to: thothSupport)
        }
        let thothLogs = home.appendingPathComponent("Library/Logs/Thoth")
        let humanizerLogs = home.appendingPathComponent("Library/Logs/Humanizer")
        if !FileManager.default.fileExists(atPath: thothLogs.path),
           FileManager.default.fileExists(atPath: humanizerLogs.path) {
            try? FileManager.default.moveItem(at: humanizerLogs, to: thothLogs)
        }

        let legacyPaths = [
            "Library/LaunchAgents/com.thoth.app.plist",
            "Library/LaunchAgents/com.thoth.macos.plist",
            "Library/LaunchAgents/com.humanizer.app.plist",
            "Library/LaunchAgents/com.humanizer.macos.plist",
        ].map { home.appendingPathComponent($0) }
        for path in legacyPaths where FileManager.default.fileExists(atPath: path.path) {
            try? FileManager.default.removeItem(at: path)
        }
        let uid = getuid()
        for label in [
            "com.thoth.app",
            "com.thoth.app.agent",
            "com.thoth.macos",
            "com.thoth.macos.agent",
            "com.humanizer.app",
            "com.humanizer.app.agent",
            "com.humanizer.macos",
            "com.humanizer.macos.agent",
        ] {
            let task = Process()
            task.executableURL = URL(fileURLWithPath: "/bin/launchctl")
            task.arguments = ["bootout", "gui/\(uid)/\(label)"]
            try? task.run()
            task.waitUntilExit()
        }

        guard #available(macOS 13.0, *) else {
            return "macOS 13+ required for Background Activity"
        }

        let loginItem = SMAppService.loginItem(identifier: "com.thoth.macos.LaunchAtLogin")
        let main = SMAppService.mainApp
        // Do NOT register the LaunchAgent that runs Contents/MacOS/Thoth —
        // that starts a second GUI process and a second menu bar icon.
        let staleAgents = [
            "com.thoth.macos.agent.plist",
            "com.thoth.app.agent.plist",
            "com.humanizer.macos.agent.plist",
            "com.humanizer.app.agent.plist",
        ]

        if forceReregister {
            try? loginItem.unregister()
            try? main.unregister()
            for name in staleAgents {
                try? SMAppService.agent(plistName: name).unregister()
            }
            Thread.sleep(forTimeInterval: 0.4)
        } else {
            // One-time cleanup of agents registered by earlier builds.
            for name in staleAgents {
                try? SMAppService.agent(plistName: name).unregister()
            }
            try? SMAppService.loginItem(identifier: "com.thoth.app.LaunchAtLogin").unregister()
            try? SMAppService.loginItem(identifier: "com.humanizer.macos.LaunchAtLogin").unregister()
            try? SMAppService.loginItem(identifier: "com.humanizer.app.LaunchAtLogin").unregister()
            // Also drop the old mainApp registration for the previous bundle id if present —
            // SMAppService.mainApp only covers this process's bundle.
        }

        // Only open the helper when first registering — avoids a second Thoth launch.
        if forceReregister {
            let helperURL = Bundle.main.bundleURL
                .appendingPathComponent("Contents/Library/LoginItems/LaunchAtLogin.app")
            if FileManager.default.fileExists(atPath: helperURL.path) {
                NSWorkspace.shared.openApplication(at: helperURL, configuration: NSWorkspace.OpenConfiguration()) { _, _ in }
                Thread.sleep(forTimeInterval: 0.5)
            }
        }

        var notes: [String] = []
        do {
            try main.register()
            notes.append("mainApp:ok")
        } catch {
            notes.append("mainApp:\(error.localizedDescription)")
        }
        do {
            try loginItem.register()
            notes.append("loginItem:ok")
        } catch {
            notes.append("loginItem:\(error.localizedDescription)")
        }
        notes.append("agent:unregistered")

        let summary = backgroundStatusSummary()
        writeBackgroundStatusLog(summary + " | " + notes.joined(separator: ", "))
        return summary
    }

    @available(macOS 13.0, *)
    private func statusLabel(_ status: SMAppService.Status) -> String {
        switch status {
        case .enabled: return "enabled"
        case .requiresApproval: return "requiresApproval"
        case .notRegistered: return "notRegistered"
        case .notFound: return "notFound"
        @unknown default: return "unknown(\(status.rawValue))"
        }
    }

    private func backgroundStatusSummary() -> String {
        guard #available(macOS 13.0, *) else { return "unsupported OS" }
        let main = statusLabel(SMAppService.mainApp.status)
        let login = statusLabel(SMAppService.loginItem(identifier: "com.thoth.macos.LaunchAtLogin").status)
        return "main=\(main) loginItem=\(login)"
    }

    private func writeBackgroundStatusLog(_ line: String) {
        let dir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/Thoth")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let url = dir.appendingPathComponent("background-status.log")
        let stamp = ISO8601DateFormatter().string(from: Date())
        let text = "[\(stamp)] \(line)\n"
        if let data = text.data(using: .utf8) {
            if FileManager.default.fileExists(atPath: url.path),
               let handle = try? FileHandle(forWritingTo: url) {
                defer { try? handle.close() }
                handle.seekToEndOfFile()
                handle.write(data)
            } else {
                try? data.write(to: url)
            }
        }
    }

    private func setupSettingsWindow() {
        let rect = NSRect(x: 0, y: 0, width: 480, height: 580)
        let style: NSWindow.StyleMask = [.titled, .closable]
        let win = NSWindow(contentRect: rect, styleMask: style, backing: .buffered, defer: false)
        win.title = "Thoth Settings"
        win.backgroundColor = bg
        win.isReleasedWhenClosed = false
        win.center()
        win.delegate = self

        guard let content = win.contentView else { return }

        var mem: UInt64 = 0
        var len = MemoryLayout<UInt64>.size
        sysctlbyname("hw.memsize", &mem, &len, nil, 0)
        systemRamGB = max(4, Int(mem / (1024 * 1024 * 1024)))

        let root = NSView(frame: content.bounds)
        root.autoresizingMask = [.width, .height]
        content.addSubview(root)
        settingsRootView = root

        let heading = NSTextField(labelWithString: "Settings")
        heading.font = .systemFont(ofSize: 24, weight: .bold)
        heading.textColor = textColor
        heading.frame = NSRect(x: 28, y: 534, width: 200, height: 28)
        root.addSubview(heading)

        // Top Local / API mode switch
        let provider = NSSegmentedControl(
            labels: ["Local", "API"],
            trackingMode: .selectOne,
            target: self,
            action: #selector(aiProviderChanged(_:))
        )
        provider.frame = NSRect(x: 260, y: 534, width: 192, height: 28)
        provider.selectedSegment = 0
        provider.setAccessibilityLabel("Writing backend")
        root.addSubview(provider)
        aiProviderControl = provider

        // Shared mode card frame — Local LLM and API key swap here.
        let modeFrame = NSRect(x: 28, y: 368, width: 424, height: 154)

        // Local LLM card
        let card = NSView(frame: modeFrame)
        card.wantsLayer = true
        card.layer?.backgroundColor = surface.cgColor
        card.layer?.cornerRadius = 14
        root.addSubview(card)
        settingsLocalCard = card

        let section = NSTextField(labelWithString: "Local LLM")
        section.font = .systemFont(ofSize: 15, weight: .semibold)
        section.textColor = textColor
        section.frame = NSRect(x: 20, y: 122, width: 280, height: 22)
        card.addSubview(section)

        let blurb = NSTextField(wrappingLabelWithString: "Pick Ollama models for grammar and for rewrite / generate.")
        blurb.font = .systemFont(ofSize: 12)
        blurb.textColor = muted
        blurb.frame = NSRect(x: 20, y: 98, width: 384, height: 20)
        card.addSubview(blurb)

        let grammarLabel = NSTextField(labelWithString: "Grammar model")
        grammarLabel.font = .systemFont(ofSize: 12)
        grammarLabel.textColor = muted
        grammarLabel.frame = NSRect(x: 20, y: 68, width: 120, height: 18)
        card.addSubview(grammarLabel)

        let grammar = NSPopUpButton(frame: NSRect(x: 150, y: 62, width: 250, height: 28), pullsDown: false)
        grammar.target = self
        grammar.action = #selector(modelSelectionChanged(_:))
        card.addSubview(grammar)
        grammarPopup = grammar

        let writingLabel = NSTextField(labelWithString: "Writing model")
        writingLabel.font = .systemFont(ofSize: 12)
        writingLabel.textColor = muted
        writingLabel.frame = NSRect(x: 20, y: 34, width: 120, height: 18)
        card.addSubview(writingLabel)

        let writing = NSPopUpButton(frame: NSRect(x: 150, y: 28, width: 250, height: 28), pullsDown: false)
        writing.target = self
        writing.action = #selector(modelSelectionChanged(_:))
        card.addSubview(writing)
        writingPopup = writing

        let help = NSTextField(labelWithString: "Loading models from Ollama…")
        help.font = .systemFont(ofSize: 11)
        help.textColor = muted
        help.frame = NSRect(x: 20, y: 6, width: 384, height: 16)
        card.addSubview(help)
        modelsHelpLabel = help

        // Hardware nav row → opens Hardware page (Local mode only)
        let hwCard = NSView(frame: NSRect(x: 28, y: 292, width: 424, height: 64))
        hwCard.wantsLayer = true
        hwCard.layer?.backgroundColor = surface.cgColor
        hwCard.layer?.cornerRadius = 14
        root.addSubview(hwCard)
        settingsHardwareCard = hwCard

        let hwSection = NSTextField(labelWithString: "Hardware")
        hwSection.font = .systemFont(ofSize: 15, weight: .semibold)
        hwSection.textColor = textColor
        hwSection.frame = NSRect(x: 20, y: 32, width: 280, height: 20)
        hwCard.addSubview(hwSection)

        let hwSummary = NSTextField(labelWithString: "RAM, GPU, estimated speed")
        hwSummary.font = .systemFont(ofSize: 12)
        hwSummary.textColor = muted
        hwSummary.frame = NSRect(x: 20, y: 10, width: 320, height: 16)
        hwCard.addSubview(hwSummary)
        hardwareSummaryLabel = hwSummary

        let hwChevron = NSTextField(labelWithString: "›")
        hwChevron.font = .systemFont(ofSize: 22, weight: .regular)
        hwChevron.textColor = muted
        hwChevron.alignment = .right
        hwChevron.frame = NSRect(x: 370, y: 16, width: 30, height: 28)
        hwCard.addSubview(hwChevron)

        let hwOpen = NSButton(frame: hwCard.bounds)
        hwOpen.title = ""
        hwOpen.bezelStyle = .inline
        hwOpen.isBordered = false
        hwOpen.setButtonType(.momentaryChange)
        hwOpen.target = self
        hwOpen.action = #selector(showHardwarePage)
        hwOpen.toolTip = "Open hardware settings"
        hwOpen.setAccessibilityLabel("Hardware")
        hwCard.addSubview(hwOpen)

        // API key card (same slot as Local LLM)
        let aiCard = NSView(frame: modeFrame)
        aiCard.wantsLayer = true
        aiCard.layer?.backgroundColor = surface.cgColor
        aiCard.layer?.cornerRadius = 14
        aiCard.isHidden = true
        root.addSubview(aiCard)
        settingsApiCard = aiCard

        let aiSection = NSTextField(labelWithString: "API key")
        aiSection.font = .systemFont(ofSize: 15, weight: .semibold)
        aiSection.textColor = textColor
        aiSection.frame = NSRect(x: 20, y: 122, width: 90, height: 22)
        aiCard.addSubview(aiSection)

        let connectedTag = NSView(frame: NSRect(x: 112, y: 122, width: 84, height: 22))
        connectedTag.wantsLayer = true
        connectedTag.layer?.cornerRadius = 11
        connectedTag.layer?.backgroundColor = okColor.withAlphaComponent(0.22).cgColor
        connectedTag.isHidden = true
        aiCard.addSubview(connectedTag)
        aiConnectedTag = connectedTag

        let connectedLabel = NSTextField(labelWithString: "Connected")
        connectedLabel.font = .systemFont(ofSize: 11, weight: .semibold)
        connectedLabel.textColor = okColor
        connectedLabel.alignment = .center
        connectedLabel.frame = NSRect(x: 0, y: 2, width: 84, height: 16)
        connectedTag.addSubview(connectedLabel)
        aiConnectedTagLabel = connectedLabel

        let aiBlurb = NSTextField(wrappingLabelWithString: "Use your own OpenAI, Groq, or compatible key for rewrite / generate.")
        aiBlurb.font = .systemFont(ofSize: 12)
        aiBlurb.textColor = muted
        aiBlurb.frame = NSRect(x: 20, y: 96, width: 384, height: 22)
        aiCard.addSubview(aiBlurb)

        let keyField = NSSecureTextField(frame: NSRect(x: 20, y: 60, width: 384, height: 28))
        keyField.placeholderString = "API key"
        keyField.font = .systemFont(ofSize: 13)
        aiCard.addSubview(keyField)
        aiApiKeyField = keyField

        let baseField = NSTextField(frame: NSRect(x: 20, y: 28, width: 384, height: 28))
        baseField.placeholderString = "Base URL (optional)"
        baseField.font = .systemFont(ofSize: 13)
        aiCard.addSubview(baseField)
        aiBaseUrlField = baseField

        let aiHelp = NSTextField(labelWithString: "Paste your key, then Save API key")
        aiHelp.font = .systemFont(ofSize: 11)
        aiHelp.textColor = muted
        aiHelp.frame = NSRect(x: 20, y: 6, width: 384, height: 16)
        aiCard.addSubview(aiHelp)
        aiHelpLabel = aiHelp

        // Features nav row → opens Features page
        let featuresCard = NSView(frame: NSRect(x: 28, y: 216, width: 424, height: 64))
        featuresCard.wantsLayer = true
        featuresCard.layer?.backgroundColor = surface.cgColor
        featuresCard.layer?.cornerRadius = 14
        root.addSubview(featuresCard)
        settingsFeaturesCard = featuresCard

        let featuresSection = NSTextField(labelWithString: "Features")
        featuresSection.font = .systemFont(ofSize: 15, weight: .semibold)
        featuresSection.textColor = textColor
        featuresSection.frame = NSRect(x: 20, y: 32, width: 280, height: 20)
        featuresCard.addSubview(featuresSection)

        let featuresSummary = NSTextField(labelWithString: "Grammar, Rewrite, Generate")
        featuresSummary.font = .systemFont(ofSize: 12)
        featuresSummary.textColor = muted
        featuresSummary.frame = NSRect(x: 20, y: 10, width: 320, height: 16)
        featuresCard.addSubview(featuresSummary)
        featuresSummaryLabel = featuresSummary

        let featuresChevron = NSTextField(labelWithString: "›")
        featuresChevron.font = .systemFont(ofSize: 22, weight: .regular)
        featuresChevron.textColor = muted
        featuresChevron.alignment = .right
        featuresChevron.frame = NSRect(x: 370, y: 16, width: 30, height: 28)
        featuresCard.addSubview(featuresChevron)

        let featuresOpen = NSButton(frame: featuresCard.bounds)
        featuresOpen.title = ""
        featuresOpen.bezelStyle = .inline
        featuresOpen.isBordered = false
        featuresOpen.setButtonType(.momentaryChange)
        featuresOpen.target = self
        featuresOpen.action = #selector(showFeaturesPage)
        featuresOpen.toolTip = "Open feature settings"
        featuresOpen.setAccessibilityLabel("Features")
        featuresCard.addSubview(featuresOpen)

        // Chrome extension section
        let chromeCard = NSView(frame: NSRect(x: 28, y: 140, width: 424, height: 64))
        chromeCard.wantsLayer = true
        chromeCard.layer?.backgroundColor = surface.cgColor
        chromeCard.layer?.cornerRadius = 14
        root.addSubview(chromeCard)
        settingsChromeCard = chromeCard

        let chromeSection = NSTextField(labelWithString: "Chrome extension")
        chromeSection.font = .systemFont(ofSize: 15, weight: .semibold)
        chromeSection.textColor = textColor
        chromeSection.frame = NSRect(x: 20, y: 32, width: 220, height: 20)
        chromeCard.addSubview(chromeSection)

        let chromeBlurb = NSTextField(wrappingLabelWithString: "Load the bundled extension so Chrome can talk to this app.")
        chromeBlurb.font = .systemFont(ofSize: 12)
        chromeBlurb.textColor = muted
        chromeBlurb.frame = NSRect(x: 20, y: 10, width: 250, height: 18)
        chromeCard.addSubview(chromeBlurb)

        let chrome = NSButton(title: "Connect…", target: self, action: #selector(showChromeConnect))
        chrome.bezelStyle = .rounded
        chrome.frame = NSRect(x: 300, y: 16, width: 104, height: 32)
        chrome.toolTip = "Connect Chrome Extension"
        chromeCard.addSubview(chrome)
        chromeConnectButton = chrome

        let refresh = NSButton(title: "Refresh models", target: self, action: #selector(refreshModels))
        refresh.bezelStyle = .rounded
        refresh.frame = NSRect(x: 28, y: 20, width: 130, height: 32)
        root.addSubview(refresh)
        refreshModelsButton = refresh

        let apply = NSButton(title: "Apply models", target: self, action: #selector(applyModelSettings))
        apply.bezelStyle = .rounded
        apply.frame = NSRect(x: 168, y: 20, width: 120, height: 32)
        root.addSubview(apply)
        applyModelsButton = apply

        let saveAi = NSButton(title: "Save API key", target: self, action: #selector(saveAiSettings))
        saveAi.bezelStyle = .rounded
        saveAi.frame = NSRect(x: 168, y: 20, width: 120, height: 32)
        saveAi.isHidden = true
        root.addSubview(saveAi)
        saveApiButton = saveAi

        let done = NSButton(title: "Done", target: self, action: #selector(closeSettings))
        done.bezelStyle = .rounded
        done.frame = NSRect(x: 372, y: 20, width: 80, height: 32)
        root.addSubview(done)
        settingsDoneButton = done

        setupFeaturesPage(in: content)
        setupHardwarePage(in: content)
        settingsWindow = win
        showSettingsRoot()
        updateSettingsModeUI()
        updateHardwareEstimate()
    }

    private func setupHardwarePage(in content: NSView) {
        let page = NSView(frame: content.bounds)
        page.autoresizingMask = [.width, .height]
        page.isHidden = true
        content.addSubview(page)
        settingsHardwareView = page

        let back = NSButton(title: "Settings", target: self, action: #selector(showSettingsRoot))
        back.bezelStyle = .inline
        back.isBordered = false
        back.font = .systemFont(ofSize: 16, weight: .semibold)
        back.contentTintColor = muted
        back.imagePosition = .imageLeading
        if let chevron = NSImage(systemSymbolName: "chevron.left", accessibilityDescription: "Back") {
            let cfg = NSImage.SymbolConfiguration(pointSize: 18, weight: .semibold)
            back.image = chevron.withSymbolConfiguration(cfg)
        }
        back.frame = NSRect(x: 16, y: 526, width: 140, height: 36)
        back.setAccessibilityLabel("Back to Settings")
        page.addSubview(back)

        let heading = NSTextField(labelWithString: "Hardware")
        heading.font = .systemFont(ofSize: 24, weight: .bold)
        heading.textColor = textColor
        heading.frame = NSRect(x: 28, y: 486, width: 300, height: 28)
        page.addSubview(heading)

        let blurb = NSTextField(wrappingLabelWithString: "Allocate RAM and GPU for local models. Estimated tokens/sec updates as you move the sliders.")
        blurb.font = .systemFont(ofSize: 13)
        blurb.textColor = muted
        blurb.frame = NSRect(x: 28, y: 448, width: 424, height: 32)
        page.addSubview(blurb)

        let card = NSView(frame: NSRect(x: 28, y: 210, width: 424, height: 220))
        card.wantsLayer = true
        card.layer?.backgroundColor = surface.cgColor
        card.layer?.cornerRadius = 14
        page.addSubview(card)

        let ramCaption = NSTextField(labelWithString: "RAM")
        ramCaption.font = .systemFont(ofSize: 12)
        ramCaption.textColor = muted
        ramCaption.frame = NSRect(x: 20, y: 178, width: 50, height: 16)
        card.addSubview(ramCaption)

        let defaultRam = Double(max(4, min(systemRamGB / 2, systemRamGB - 2)))
        let ramSliderControl = NSSlider(
            value: defaultRam,
            minValue: 4,
            maxValue: Double(max(4, systemRamGB - 2)),
            target: self,
            action: #selector(hardwareSliderChanged(_:))
        )
        ramSliderControl.frame = NSRect(x: 70, y: 174, width: 260, height: 24)
        card.addSubview(ramSliderControl)
        ramSlider = ramSliderControl

        let ramValue = NSTextField(labelWithString: "\(Int(defaultRam)) GB")
        ramValue.font = .systemFont(ofSize: 12, weight: .medium)
        ramValue.textColor = textColor
        ramValue.alignment = .right
        ramValue.frame = NSRect(x: 340, y: 178, width: 64, height: 16)
        card.addSubview(ramValue)
        ramValueLabel = ramValue

        let gpuCaption = NSTextField(labelWithString: "GPU")
        gpuCaption.font = .systemFont(ofSize: 12)
        gpuCaption.textColor = muted
        gpuCaption.frame = NSRect(x: 20, y: 134, width: 50, height: 16)
        card.addSubview(gpuCaption)

        let gpuSliderControl = NSSlider(
            value: 75,
            minValue: 25,
            maxValue: 95,
            target: self,
            action: #selector(hardwareSliderChanged(_:))
        )
        gpuSliderControl.frame = NSRect(x: 70, y: 130, width: 260, height: 24)
        card.addSubview(gpuSliderControl)
        gpuSlider = gpuSliderControl

        let gpuValue = NSTextField(labelWithString: "75%")
        gpuValue.font = .systemFont(ofSize: 12, weight: .medium)
        gpuValue.textColor = textColor
        gpuValue.alignment = .right
        gpuValue.frame = NSRect(x: 340, y: 134, width: 64, height: 16)
        card.addSubview(gpuValue)
        gpuValueLabel = gpuValue

        let tokens = NSTextField(labelWithString: "Estimated speed: — tokens/sec")
        tokens.font = .systemFont(ofSize: 13, weight: .semibold)
        tokens.textColor = okColor
        tokens.frame = NSRect(x: 20, y: 88, width: 384, height: 18)
        card.addSubview(tokens)
        tokensEstimateLabel = tokens

        let recommendLine = NSTextField(wrappingLabelWithString: "Recommended: —")
        recommendLine.font = .systemFont(ofSize: 12, weight: .medium)
        recommendLine.textColor = textColor
        recommendLine.frame = NSRect(x: 20, y: 50, width: 384, height: 30)
        card.addSubview(recommendLine)
        hardwareRecommendLabel = recommendLine

        let hwHint = NSTextField(wrappingLabelWithString: "Recommend picks balanced values for this Mac. Apply to save and restart.")
        hwHint.font = .systemFont(ofSize: 11)
        hwHint.textColor = muted
        hwHint.frame = NSRect(x: 20, y: 12, width: 384, height: 30)
        card.addSubview(hwHint)

        let hardwareHelp = NSTextField(labelWithString: "Move the sliders, then Apply")
        hardwareHelp.font = .systemFont(ofSize: 11)
        hardwareHelp.textColor = muted
        hardwareHelp.frame = NSRect(x: 28, y: 176, width: 424, height: 18)
        page.addSubview(hardwareHelp)
        hardwareHelpLabel = hardwareHelp

        let recommend = NSButton(title: "Recommend", target: self, action: #selector(applyHardwareRecommendation))
        recommend.bezelStyle = .rounded
        recommend.frame = NSRect(x: 28, y: 20, width: 110, height: 32)
        recommend.toolTip = "Set RAM and GPU to the recommended values for this Mac"
        page.addSubview(recommend)

        let apply = NSButton(title: "Apply", target: self, action: #selector(applyHardwareSettings))
        apply.bezelStyle = .rounded
        apply.frame = NSRect(x: 148, y: 20, width: 100, height: 32)
        page.addSubview(apply)

        let done = NSButton(title: "Done", target: self, action: #selector(closeSettings))
        done.bezelStyle = .rounded
        done.frame = NSRect(x: 372, y: 20, width: 80, height: 32)
        page.addSubview(done)

        refreshHardwareRecommendation()
    }

    private func setupFeaturesPage(in content: NSView) {
        let page = NSView(frame: content.bounds)
        page.autoresizingMask = [.width, .height]
        page.isHidden = true
        content.addSubview(page)
        settingsFeaturesView = page

        let back = NSButton(title: "Settings", target: self, action: #selector(showSettingsRoot))
        back.bezelStyle = .inline
        back.isBordered = false
        back.font = .systemFont(ofSize: 16, weight: .semibold)
        back.contentTintColor = muted
        back.imagePosition = .imageLeading
        if let chevron = NSImage(systemSymbolName: "chevron.left", accessibilityDescription: "Back") {
            let cfg = NSImage.SymbolConfiguration(pointSize: 18, weight: .semibold)
            back.image = chevron.withSymbolConfiguration(cfg)
        }
        back.frame = NSRect(x: 16, y: 526, width: 140, height: 36)
        back.setAccessibilityLabel("Back to Settings")
        page.addSubview(back)

        let heading = NSTextField(labelWithString: "Features")
        heading.font = .systemFont(ofSize: 24, weight: .bold)
        heading.textColor = textColor
        heading.frame = NSRect(x: 28, y: 486, width: 300, height: 28)
        page.addSubview(heading)

        let blurb = NSTextField(wrappingLabelWithString: "Turn features on or off for the Chrome extension and local server.")
        blurb.font = .systemFont(ofSize: 13)
        blurb.textColor = muted
        blurb.frame = NSRect(x: 28, y: 452, width: 424, height: 28)
        page.addSubview(blurb)

        let card = NSView(frame: NSRect(x: 28, y: 268, width: 424, height: 164))
        card.wantsLayer = true
        card.layer?.backgroundColor = surface.cgColor
        card.layer?.cornerRadius = 14
        page.addSubview(card)

        func addFeatureRow(title: String, detail: String, y: CGFloat) -> NSSwitch {
            let label = NSTextField(labelWithString: title)
            label.font = .systemFont(ofSize: 15, weight: .medium)
            label.textColor = textColor
            label.frame = NSRect(x: 20, y: y + 18, width: 280, height: 20)
            card.addSubview(label)

            let detailLabel = NSTextField(labelWithString: detail)
            detailLabel.font = .systemFont(ofSize: 11)
            detailLabel.textColor = muted
            detailLabel.frame = NSRect(x: 20, y: y, width: 300, height: 16)
            card.addSubview(detailLabel)

            let toggle = NSSwitch(frame: NSRect(x: 350, y: y + 10, width: 51, height: 28))
            toggle.state = .on
            toggle.target = self
            toggle.action = #selector(featureToggled(_:))
            card.addSubview(toggle)
            return toggle
        }

        featureGrammarSwitch = addFeatureRow(
            title: "Grammar",
            detail: "Inline spelling and grammar underlines",
            y: 112
        )
        featureRewriteSwitch = addFeatureRow(
            title: "Rewrite",
            detail: "Rewrite selected text from the floating menu",
            y: 58
        )
        featureGenerateSwitch = addFeatureRow(
            title: "Generate",
            detail: "Generate email or essay drafts from a selection",
            y: 4
        )

        let featuresHelp = NSTextField(labelWithString: "Changes apply immediately")
        featuresHelp.font = .systemFont(ofSize: 11)
        featuresHelp.textColor = muted
        featuresHelp.frame = NSRect(x: 28, y: 232, width: 424, height: 18)
        page.addSubview(featuresHelp)
        featuresHelpLabel = featuresHelp

        let done = NSButton(title: "Done", target: self, action: #selector(closeSettings))
        done.bezelStyle = .rounded
        done.frame = NSRect(x: 372, y: 20, width: 80, height: 32)
        page.addSubview(done)
    }

    @objc private func showSettingsRoot() {
        settingsRootView?.isHidden = false
        settingsFeaturesView?.isHidden = true
        settingsHardwareView?.isHidden = true
        settingsWindow?.title = "Thoth Settings"
        updateFeaturesSummaryLabel()
        updateHardwareSummaryLabel()
    }

    @objc private func showFeaturesPage() {
        loadFeatureSettings()
        settingsRootView?.isHidden = true
        settingsHardwareView?.isHidden = true
        settingsFeaturesView?.isHidden = false
        settingsWindow?.title = "Features"
    }

    @objc private func showHardwarePage() {
        settingsRootView?.isHidden = true
        settingsFeaturesView?.isHidden = true
        settingsHardwareView?.isHidden = false
        settingsWindow?.title = "Hardware"
        updateHardwareEstimate()
        hardwareHelpLabel?.stringValue = "Move the sliders, then Apply"
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let result = self?.runService(["models"]) ?? [:]
            DispatchQueue.main.async {
                self?.applyHardwareFields(from: result)
            }
        }
    }

    @objc private func showWindow() {
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc private func showSettings() {
        showSettingsRoot()
        refreshModels()
        loadAiSettings()
        loadFeatureSettings()
        settingsWindow.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc private func closeSettings() {
        showSettingsRoot()
        settingsWindow.orderOut(nil)
    }

    @objc private func quitApp() {
        NSApp.terminate(nil)
    }

    @objc private func showMenuBarConnect() {
        autoConnectMenuBar(attempt: 1)
    }

    @objc private func showChromeConnect() {
        presentChromeConnectSheet()
    }

    private func setupChromeConnectSheet() {
        let rect = NSRect(x: 0, y: 0, width: 460, height: 360)
        let win = NSWindow(
            contentRect: rect,
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        win.title = "Connect Chrome Extension"
        win.backgroundColor = bg
        win.isReleasedWhenClosed = false
        win.center()
        win.level = .floating

        guard let content = win.contentView else {
            chromeConnectSheet = win
            return
        }

        let title = NSTextField(labelWithString: "Link Chrome to Thoth")
        title.font = .systemFont(ofSize: 20, weight: .bold)
        title.textColor = textColor
        title.alignment = .center
        title.frame = NSRect(x: 28, y: 300, width: 404, height: 28)
        content.addSubview(title)

        let body = NSTextField(wrappingLabelWithString: "One-time setup: load the bundled extension from Application Support. After that, the extension reconnects to this app automatically whenever Thoth is running.")
        body.font = .systemFont(ofSize: 13)
        body.textColor = muted
        body.alignment = .center
        body.frame = NSRect(x: 36, y: 230, width: 388, height: 60)
        content.addSubview(body)

        let stepsCard = NSView(frame: NSRect(x: 36, y: 118, width: 388, height: 100))
        stepsCard.wantsLayer = true
        stepsCard.layer?.backgroundColor = surface.cgColor
        stepsCard.layer?.cornerRadius = 12
        content.addSubview(stepsCard)

        let steps = NSTextField(wrappingLabelWithString: "1. Click Open Chrome Extensions\n2. Turn on Developer mode (top right)\n3. Click Load unpacked\n4. Paste the folder path (⌘V) and Open")
        steps.font = .systemFont(ofSize: 12)
        steps.textColor = textColor
        steps.frame = NSRect(x: 16, y: 12, width: 356, height: 76)
        stepsCard.addSubview(steps)

        let path = NSTextField(labelWithString: "Path: preparing…")
        path.font = .systemFont(ofSize: 11)
        path.textColor = muted
        path.alignment = .center
        path.lineBreakMode = .byTruncatingMiddle
        path.frame = NSRect(x: 36, y: 88, width: 388, height: 16)
        content.addSubview(path)
        chromeConnectPathLabel = path

        let openBtn = NSButton(title: "Open Chrome Extensions", target: self, action: #selector(openChromeExtensions))
        openBtn.bezelStyle = .rounded
        openBtn.frame = NSRect(x: 100, y: 40, width: 200, height: 32)
        content.addSubview(openBtn)

        let done = NSButton(title: "Done", target: self, action: #selector(dismissChromeConnect))
        done.bezelStyle = .rounded
        done.frame = NSRect(x: 310, y: 40, width: 80, height: 32)
        content.addSubview(done)

        chromeConnectSheet = win
    }

    private func presentChromeConnectSheet() {
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let result = self?.runService(["connect-extension"]) ?? ["ok": false]
            let path = (result["extension_path"] as? String)
                ?? (FileManager.default.homeDirectoryForCurrentUser
                    .appendingPathComponent("Library/Application Support/Thoth/ChromeExtension").path)
            DispatchQueue.main.async {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(path, forType: .string)
                self?.chromeConnectPathLabel?.stringValue = "Path copied: \(path)"
                self?.chromeConnectSheet.makeKeyAndOrderFront(nil)
                NSApp.activate(ignoringOtherApps: true)
            }
        }
    }

    @objc private func openChromeExtensions() {
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let result = self?.runService(["connect-extension"]) ?? [:]
            let path = (result["extension_path"] as? String)
                ?? (FileManager.default.homeDirectoryForCurrentUser
                    .appendingPathComponent("Library/Application Support/Thoth/ChromeExtension").path)
            DispatchQueue.main.async {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(path, forType: .string)
                self?.chromeConnectPathLabel?.stringValue = "Path copied: \(path)"
            }
            let proc = Process()
            proc.executableURL = URL(fileURLWithPath: "/usr/bin/open")
            proc.arguments = ["-a", "Google Chrome", "chrome://extensions"]
            try? proc.run()
            proc.waitUntilExit()
            if proc.terminationStatus != 0 {
                let fallback = Process()
                fallback.executableURL = URL(fileURLWithPath: "/usr/bin/open")
                fallback.arguments = ["-a", "Chromium", "chrome://extensions"]
                try? fallback.run()
            }
        }
    }

    @objc private func dismissChromeConnect() {
        chromeConnectSheet.orderOut(nil)
    }

    @objc private func openMenuBarSettings() {
        openMenuBarSettingsURLs()
    }

    @objc private func openBackgroundActivityFromPrompt() {
        let summary = registerBackgroundActivity(forceReregister: true)
        bgStatusLabel?.stringValue = "Background status: \(summary)"
        openLoginItemsSettings()
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
            self?.menuBarSheet.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            self?.bgStatusLabel?.stringValue = "Background status: \(self?.backgroundStatusSummary() ?? "?")"
        }
    }

    @objc private func openMenuBarSettingsFromPrompt() {
        openMenuBarSettingsURLs()
        // Keep the sheet up so they can tap “I’ve allowed it” after flipping the toggle.
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
            self?.menuBarSheet.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    private func openLoginItemsSettings() {
        if #available(macOS 13.0, *) {
            SMAppService.openSystemSettingsLoginItems()
            return
        }
        let urls = [
            "x-apple.systempreferences:com.apple.LoginItems-Settings.extension",
            "x-apple.systempreferences:com.apple.preferences.users",
        ]
        for raw in urls {
            if let url = URL(string: raw), NSWorkspace.shared.open(url) {
                return
            }
        }
    }

    private func openMenuBarSettingsURLs() {
        let urls = [
            "x-apple.systempreferences:com.apple.ControlCenter-Settings.extension",
            "x-apple.systempreferences:com.apple.ControlCenter-Settings.extension?MenuBar",
            "x-apple.systempreferences:com.apple.preference.dock?MenuBar",
        ]
        var opened = false
        for raw in urls {
            if let url = URL(string: raw), NSWorkspace.shared.open(url) {
                opened = true
                break
            }
        }
        if !opened {
            NSWorkspace.shared.open(URL(fileURLWithPath: "/System/Applications/System Settings.app"))
        }
    }

    @objc private func dismissMenuBarConnect() {
        menuBarSheet.orderOut(nil)
        defaults.set(true, forKey: menuBarAckKey)
        updateMenuBarBanner()
    }

    @objc private func recheckMenuBarAfterAllow() {
        statusItem.isVisible = true
        // Recreate status item — helps StatusKit pick up a fresh allow.
        recreateStatusItem()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { [weak self] in
            guard let self else { return }
            if self.isMenuBarItemShowing() {
                self.defaults.set(true, forKey: self.menuBarAckKey)
                self.menuBarSheet.orderOut(nil)
                self.updateMenuBarBanner()
                let alert = NSAlert()
                alert.messageText = "Menu bar connected"
                alert.informativeText = "Look for the Thoth icon near the clock."
                alert.addButton(withTitle: "OK")
                alert.runModal()
            } else {
                let alert = NSAlert()
                alert.messageText = "Still waiting for Menu Bar access"
                alert.informativeText = """
                In System Settings → Menu Bar, find Thoth and turn it ON.

                Then click “I’ve allowed it — check again”.
                """
                alert.addButton(withTitle: "Open Settings Again")
                alert.addButton(withTitle: "OK")
                if alert.runModal() == .alertFirstButtonReturn {
                    self.openMenuBarSettingsURLs()
                }
                self.updateMenuBarBanner()
            }
        }
    }

    /// Attach the H icon on open. Prefer silent recovery; only ask the user if
    /// macOS still refuses after recreate + Control Center reset.
    private func autoConnectMenuBar(attempt: Int) {
        if menuBarAutoConnectRunning, attempt == 1 { return }
        menuBarAutoConnectRunning = true
        statusItem.isVisible = true

        if isMenuBarItemShowing() {
            defaults.set(true, forKey: menuBarAckKey)
            menuBarSheet.orderOut(nil)
            menuBarBanner?.isHidden = true
            menuBarAutoConnectRunning = false
            logMenuBarGeometry("auto-connected")
            return
        }

        switch attempt {
        case 1:
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { [weak self] in
                guard let self else { return }
                if self.isMenuBarItemShowing() {
                    self.autoConnectMenuBar(attempt: 99)
                    return
                }
                self.lastStatusRecreate = Date()
                self.recreateStatusItem()
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.9) {
                    self.autoConnectMenuBar(attempt: 2)
                }
            }
        case 2:
            softResetMenuBarPlacement()
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.4) { [weak self] in
                self?.autoConnectMenuBar(attempt: 3)
            }
        default:
            menuBarAutoConnectRunning = false
            if isMenuBarItemShowing() {
                defaults.set(true, forKey: menuBarAckKey)
                menuBarSheet.orderOut(nil)
                return
            }
            // Still blocked — open Menu Bar settings so they can allow once.
            presentMenuBarConnectSheet()
            openMenuBarSettingsURLs()
        }
    }

    private func presentMenuBarConnectIfNeeded(force: Bool) {
        if isMenuBarItemShowing() {
            defaults.set(true, forKey: menuBarAckKey)
            menuBarSheet.orderOut(nil)
            return
        }
        if force || !defaults.bool(forKey: menuBarAckKey) {
            autoConnectMenuBar(attempt: 1)
        }
    }

    private func presentMenuBarConnectSheet() {
        statusItem.isVisible = true
        window.makeKeyAndOrderFront(nil)
        menuBarSheet.center()
        menuBarSheet.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        menuBarPromptPresented = true
        updateMenuBarBanner()
    }

    private func isMenuBarItemShowing() -> Bool {
        statusItem.isVisible = true
        guard let button = statusItem.button else { return false }
        guard let win = button.window else { return false }
        let frame = win.frame
        // On macOS 26, blocked / misplaced items are off-screen (y ≤ 0) or have no screen.
        if frame.origin.y <= 0 { return false }
        if win.screen == nil { return false }
        if frame.width < 2 || frame.height < 2 { return false }
        return true
    }

    private func updateMenuBarBanner() {
        let showing = isMenuBarItemShowing()
        menuBarBanner?.isHidden = showing
        // Hide Connect once the menu bar icon is visible; show it again if macOS drops it.
        menuBarConnectButton?.isHidden = showing
        logMenuBarGeometry(showing ? "visible" : "hidden")
    }

    private func recreateStatusItem() {
        if let existing = statusItem {
            NSStatusBar.system.removeStatusItem(existing)
        }
        UserDefaults.standard.removeObject(forKey: "NSStatusItem Preferred Position com.thoth.macos.statusItem")
        UserDefaults.standard.removeObject(forKey: "NSStatusItem Preferred Position com.thoth.app.statusItem")
        UserDefaults.standard.removeObject(forKey: "NSStatusItem Preferred Position com.humanizer.macos.statusItem")
        UserDefaults.standard.removeObject(forKey: "NSStatusItem Preferred Position com.humanizer.app.statusItem")
        setupStatusItem()
    }

    private func softResetMenuBarPlacement() {
        guard !didAutoResetControlCenter else {
            recreateStatusItem()
            return
        }
        didAutoResetControlCenter = true
        UserDefaults.standard.removeObject(forKey: "NSStatusItem Preferred Position com.thoth.macos.statusItem")
        UserDefaults.standard.removeObject(forKey: "NSStatusItem Preferred Position com.thoth.app.statusItem")
        UserDefaults.standard.removeObject(forKey: "NSStatusItem Preferred Position com.humanizer.macos.statusItem")
        UserDefaults.standard.removeObject(forKey: "NSStatusItem Preferred Position com.humanizer.app.statusItem")
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/killall")
        task.arguments = ["ControlCenter"]
        try? task.run()
        task.waitUntilExit()
        Thread.sleep(forTimeInterval: 0.35)
        recreateStatusItem()
        logMenuBarGeometry("soft-reset")
    }

    @objc private func fixMenuBarIcon() {
        didAutoResetControlCenter = false
        softResetMenuBarPlacement()
        openMenuBarSettingsURLs()
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { [weak self] in
            guard let self else { return }
            if self.isMenuBarItemShowing() {
                self.defaults.set(true, forKey: self.menuBarAckKey)
                self.menuBarSheet.orderOut(nil)
                self.updateMenuBarBanner()
                return
            }
            let alert = NSAlert()
            alert.messageText = "Allow Thoth in the Menu Bar"
            alert.informativeText = """
            Turn Thoth ON in System Settings → Menu Bar.
            Thoth will reconnect automatically the next time it opens.
            """
            alert.addButton(withTitle: "OK")
            alert.runModal()
            self.updateMenuBarBanner()
        }
    }

    private func logMenuBarGeometry(_ reason: String) {
        var line = reason
        if let button = statusItem?.button, let win = button.window {
            let f = win.frame
            line += String(
                format: " visible=%@ frame=(%.0f,%.0f %.0fx%.0f) screen=%@",
                statusItem.isVisible ? "true" : "false",
                f.origin.x, f.origin.y, f.size.width, f.size.height,
                win.screen?.localizedName ?? "nil"
            )
        } else {
            line += " button/window=nil visible=\(statusItem?.isVisible == true)"
        }
        let dir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/Thoth")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let url = dir.appendingPathComponent("menubar-visibility.log")
        let stamp = ISO8601DateFormatter().string(from: Date())
        let text = "[\(stamp)] \(line)\n"
        if let data = text.data(using: .utf8) {
            if FileManager.default.fileExists(atPath: url.path),
               let handle = try? FileHandle(forWritingTo: url) {
                defer { try? handle.close() }
                handle.seekToEndOfFile()
                handle.write(data)
            } else {
                try? data.write(to: url)
            }
        }
        // Also surface on the main window banner tip.
        if let banner = menuBarBanner {
            for sub in banner.subviews {
                if let label = sub as? NSTextField {
                    label.stringValue = isMenuBarItemShowing()
                        ? "Menu bar icon is visible"
                        : "Menu bar icon still hidden — recreating… Open Menu Bar settings if this persists."
                }
            }
        }
    }

    @objc private func modelSelectionChanged(_ sender: NSPopUpButton) {
        if sender == grammarPopup {
            selectedGrammar = selectedModelName(from: sender) ?? selectedGrammar
        } else if sender == writingPopup {
            selectedWriting = selectedModelName(from: sender) ?? selectedWriting
        }
        updateHardwareEstimate()
    }

    private func selectedModelName(from popup: NSPopUpButton) -> String? {
        if let name = popup.selectedItem?.representedObject as? String, !name.isEmpty {
            return name
        }
        return popup.titleOfSelectedItem
    }

    private func displayLabel(for name: String) -> String {
        if let label = modelLabels[name], !label.isEmpty {
            return label
        }
        let base = name.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: true).first.map(String.init) ?? name
        if let label = modelLabels[base], !label.isEmpty {
            return label
        }
        // Local fallbacks when the service hasn't returned labels yet.
        switch base {
        case "thoth-writing", "qwen-7b-trained":
            return "Qwen 7B / trained"
        case "thoth-grammar":
            return "Qwen grammar / trained"
        case "qwen2.5":
            if name.hasPrefix("qwen2.5:7b") { return "Qwen 7B" }
            return name
        default:
            return name
        }
    }

    @objc private func refreshModels() {
        modelsHelpLabel.stringValue = "Loading models from Ollama…"
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let result = self?.runService(["models"]) ?? ["ok": false]
            DispatchQueue.main.async {
                self?.populateModelMenus(from: result)
            }
        }
    }

    private func populateModelMenus(from result: [String: Any]) {
        var names: [String] = []
        var labels: [String: String] = [:]
        if let models = result["models"] as? [[String: Any]] {
            for entry in models {
                guard let name = entry["name"] as? String, !name.isEmpty else { continue }
                names.append(name)
                if let label = entry["label"] as? String, !label.isEmpty {
                    labels[name] = label
                }
            }
        }
        availableModels = names
        modelLabels = labels

        if let g = result["grammar_model"] as? String, !g.isEmpty {
            selectedGrammar = g
        }
        if let w = result["writing_model"] as? String, !w.isEmpty {
            selectedWriting = w
        }

        fillPopup(grammarPopup, selected: selectedGrammar)
        fillPopup(writingPopup, selected: selectedWriting)

        if names.isEmpty {
            modelsHelpLabel.stringValue = "No Ollama models found. Open Ollama and pull a model, then Refresh."
        } else {
            modelsHelpLabel.stringValue = "\(names.count) model\(names.count == 1 ? "" : "s") on this Mac. Apply models to use your choices."
        }

        applyAiFields(from: result)
        applyFeatureFields(from: result)
        applyHardwareFields(from: result)
    }

    private func applyHardwareFields(from result: [String: Any]) {
        if let total = result["system_ram_gb"] as? Int, total >= 4 {
            systemRamGB = total
            ramSlider?.maxValue = Double(max(4, total - 2))
        }
        let ram = (result["hardware_ram_gb"] as? Int)
            ?? Int(ramSlider?.doubleValue ?? Double(max(4, systemRamGB / 2)))
        let gpu = (result["hardware_gpu_percent"] as? Int) ?? 75
        ramSlider?.doubleValue = Double(ram)
        gpuSlider?.doubleValue = Double(gpu)
        ramValueLabel?.stringValue = "\(ram) GB"
        gpuValueLabel?.stringValue = "\(gpu)%"
        if let recRam = result["recommended_ram_gb"] as? Int {
            recommendedRamGB = recRam
        }
        if let recGpu = result["recommended_gpu_percent"] as? Int {
            recommendedGpuPercent = recGpu
        }
        if let detail = result["recommend_detail"] as? String, !detail.isEmpty {
            hardwareRecommendLabel?.stringValue = detail
        } else {
            refreshHardwareRecommendation()
        }
        if let detail = result["tokens_detail"] as? String, !detail.isEmpty {
            tokensEstimateLabel?.stringValue = detail
            updateHardwareSummaryLabel(ram: ram, gpu: gpu)
        } else if let tps = result["tokens_per_sec"] as? Double {
            tokensEstimateLabel?.stringValue = String(format: "Estimated speed: ~%.0f tokens/sec", tps)
            updateHardwareSummaryLabel(ram: ram, gpu: gpu, tokens: tps)
        } else {
            updateHardwareEstimate()
        }
    }

    @objc private func hardwareSliderChanged(_ sender: NSSlider) {
        let ram = Int(ramSlider?.doubleValue.rounded() ?? 8)
        let gpu = Int(gpuSlider?.doubleValue.rounded() ?? 75)
        ramValueLabel?.stringValue = "\(ram) GB"
        gpuValueLabel?.stringValue = "\(gpu)%"
        updateHardwareEstimate()
    }

    private func refreshHardwareRecommendation() {
        let total = max(4, systemRamGB)
        let maxAlloc = max(4, total - 2)
        let model = selectedWriting.lowercased()
        let needed: Int
        if model.contains("0.5b") {
            needed = 2
        } else if model.contains("1.5b") || model.contains("1b") {
            needed = 3
        } else if model.contains("3b") {
            needed = 5
        } else if model.contains("8b") {
            needed = 10
        } else if model.contains("14b") || model.contains("13b") {
            needed = 16
        } else {
            needed = 9
        }
        let target = max(needed + 2, total / 2)
        let ram = min(maxAlloc, max(4, target))
        var gpu: Int
        if total <= 8 {
            gpu = 55
        } else if total <= 16 {
            gpu = 75
        } else if total <= 24 {
            gpu = 80
        } else if total <= 32 {
            gpu = 85
        } else {
            gpu = 90
        }
        if needed >= max(4, Int(Double(total) * 0.4)) {
            gpu = min(95, gpu + 5)
        }
        recommendedRamGB = ram
        recommendedGpuPercent = gpu
        hardwareRecommendLabel?.stringValue =
            "Recommended for this Mac (\(total) GB): \(ram) GB RAM · \(gpu)% GPU"
    }

    @objc private func applyHardwareRecommendation() {
        refreshHardwareRecommendation()
        let ram = recommendedRamGB
        let gpu = recommendedGpuPercent
        ramSlider?.doubleValue = Double(ram)
        gpuSlider?.doubleValue = Double(gpu)
        ramValueLabel?.stringValue = "\(ram) GB"
        gpuValueLabel?.stringValue = "\(gpu)%"
        updateHardwareEstimate()
        hardwareHelpLabel?.stringValue = "Recommendation applied — press Apply to save"
    }

    private func updateHardwareEstimate() {
        refreshHardwareRecommendation()
        let ram = Int(ramSlider?.doubleValue.rounded() ?? Double(max(4, systemRamGB / 2)))
        let gpu = Int(gpuSlider?.doubleValue.rounded() ?? 75)
        let model = selectedWriting.lowercased()
        let params: Double
        let base: Double
        if model.contains("0.5b") {
            params = 0.5; base = 95
        } else if model.contains("1.5b") || model.contains("1b") {
            params = 1.5; base = 70
        } else if model.contains("3b") {
            params = 3; base = 48
        } else if model.contains("8b") {
            params = 8; base = 28
        } else if model.contains("14b") || model.contains("13b") {
            params = 14; base = 16
        } else {
            params = 7; base = 32
        }
        let needed = max(2.0, params * 1.2)
        var ramFactor = min(1.15, Double(ram) / needed)
        if Double(ram) < needed {
            ramFactor = max(0.25, pow(Double(ram) / needed, 1.4))
        }
        let gpuFactor = 0.55 + (Double(gpu) / 100.0) * 0.55
        let tokens = max(4.0, base * ramFactor * gpuFactor)
        tokensEstimateLabel?.stringValue = String(
            format: "Estimated speed: ~%.0f tokens/sec with current RAM + GPU",
            tokens
        )
        updateHardwareSummaryLabel(ram: ram, gpu: gpu, tokens: tokens)
    }

    private func updateHardwareSummaryLabel(ram: Int? = nil, gpu: Int? = nil, tokens: Double? = nil) {
        let ramVal = ram ?? Int(ramSlider?.doubleValue.rounded() ?? Double(max(4, systemRamGB / 2)))
        let gpuVal = gpu ?? Int(gpuSlider?.doubleValue.rounded() ?? 75)
        if let tokens {
            hardwareSummaryLabel?.stringValue = String(
                format: "%d GB · %d%% · ~%.0f tok/s",
                ramVal, gpuVal, tokens
            )
        } else {
            hardwareSummaryLabel?.stringValue = "\(ramVal) GB · \(gpuVal)% · estimated speed"
        }
    }

    @objc private func applyHardwareSettings() {
        selectedGrammar = selectedModelName(from: grammarPopup) ?? selectedGrammar
        selectedWriting = selectedModelName(from: writingPopup) ?? selectedWriting
        let ram = Int(ramSlider?.doubleValue.rounded() ?? Double(max(4, systemRamGB / 2)))
        let gpu = Int(gpuSlider?.doubleValue.rounded() ?? 75)
        hardwareHelpLabel?.stringValue = "Saving and restarting server…"
        busy = true
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self else { return }
            let result = self.runService([
                "set-models",
                self.selectedGrammar,
                self.selectedWriting,
                String(ram),
                String(gpu),
            ])
            DispatchQueue.main.async {
                self.busy = false
                let ok = (result["ok"] as? Bool) ?? false
                let detail = (result["detail"] as? String) ?? ""
                self.hardwareHelpLabel?.stringValue = ok
                    ? "Hardware saved — local models will use this allocation"
                    : (detail.isEmpty ? "Saved, but the server may still be offline." : detail)
                self.applyHardwareFields(from: result)
                self.applyHealth(ok: ok, detail: ok ? "Server online" : "Server offline")
            }
        }
    }

    private func applyFeatureFields(from result: [String: Any]) {
        let grammar = (result["feature_grammar"] as? Bool) ?? true
        let rewrite = (result["feature_rewrite"] as? Bool) ?? true
        let generate = (result["feature_generate"] as? Bool) ?? true
        featureGrammarSwitch?.state = grammar ? .on : .off
        featureRewriteSwitch?.state = rewrite ? .on : .off
        featureGenerateSwitch?.state = generate ? .on : .off
        updateFeaturesSummaryLabel(grammar: grammar, rewrite: rewrite, generate: generate)
    }

    private func updateFeaturesSummaryLabel(
        grammar: Bool? = nil,
        rewrite: Bool? = nil,
        generate: Bool? = nil
    ) {
        let g = grammar ?? (featureGrammarSwitch?.state == .on)
        let r = rewrite ?? (featureRewriteSwitch?.state == .on)
        let gen = generate ?? (featureGenerateSwitch?.state == .on)
        var parts: [String] = []
        if g { parts.append("Grammar") }
        if r { parts.append("Rewrite") }
        if gen { parts.append("Generate") }
        featuresSummaryLabel?.stringValue = parts.isEmpty ? "All features off" : parts.joined(separator: ", ")
    }

    private func loadFeatureSettings() {
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let result = self?.runService(["get-ai"]) ?? [:]
            DispatchQueue.main.async {
                self?.applyFeatureFields(from: result)
            }
        }
    }

    @objc private func featureToggled(_ sender: NSSwitch) {
        let payload: [String: Any] = [
            "grammar": (featureGrammarSwitch?.state == .on),
            "rewrite": (featureRewriteSwitch?.state == .on),
            "generate": (featureGenerateSwitch?.state == .on),
        ]
        updateFeaturesSummaryLabel()
        featuresHelpLabel?.stringValue = "Saving…"
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let json = String(data: data, encoding: .utf8) else {
            return
        }
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let result = self?.runService(["set-features", json]) ?? [:]
            _ = self?.runService(["status"])
            DispatchQueue.main.async {
                let ok = (result["ok"] as? Bool) ?? false
                self?.featuresHelpLabel?.stringValue = ok
                    ? "Changes apply immediately"
                    : ((result["detail"] as? String) ?? "Could not save")
                self?.updateFeaturesSummaryLabel()
            }
        }
    }

    private func fillPopup(_ popup: NSPopUpButton, selected: String) {
        popup.removeAllItems()
        var items = availableModels
        if items.isEmpty {
            items = [selected]
        } else if !items.contains(selected) {
            items.insert(selected, at: 0)
        }
        for name in items {
            let title = displayLabel(for: name)
            popup.addItem(withTitle: title)
            popup.lastItem?.representedObject = name
            // Keep unique titles when two Ollama tags share a label.
            if popup.itemArray.filter({ $0.title == title }).count > 1 {
                popup.lastItem?.title = "\(title) (\(name))"
            }
        }
        if let match = popup.itemArray.first(where: { ($0.representedObject as? String) == selected }) {
            popup.select(match)
        } else {
            popup.selectItem(withTitle: displayLabel(for: selected))
        }
    }

    private func applyAiFields(from result: [String: Any]) {
        let provider = (result["ai_provider"] as? String)?.lowercased() ?? "local"
        let useApi = provider != "local" && provider != "ollama"
        let configured = (result["ai_configured"] as? Bool) ?? false
        aiConfiguredCached = configured
        aiProviderControl?.selectedSegment = useApi ? 1 : 0
        aiApiKeyField?.stringValue = (result["ai_api_key"] as? String) ?? ""
        aiBaseUrlField?.stringValue = (result["ai_base_url"] as? String) ?? ""
        updateSettingsModeUI()
        if useApi {
            setApiConnectedTag(visible: configured)
            aiHelpLabel?.stringValue = configured
                ? "Cloud API key saved — used for rewrite / generate"
                : "Paste your key, then Save API key"
        } else {
            setApiConnectedTag(visible: false)
            aiHelpLabel?.stringValue = "Using local models"
        }
    }

    private func setApiConnectedTag(visible: Bool) {
        aiConnectedTag?.isHidden = !visible
        if visible {
            aiConnectedTag?.layer?.backgroundColor = okColor.withAlphaComponent(0.22).cgColor
            aiConnectedTagLabel?.textColor = okColor
            aiConnectedTagLabel?.stringValue = "Connected"
        }
    }

    private func loadAiSettings() {
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let result = self?.runService(["get-ai"]) ?? [:]
            DispatchQueue.main.async {
                self?.applyAiFields(from: result)
            }
        }
    }

    private func updateSettingsModeUI() {
        let useApi = (aiProviderControl?.selectedSegment ?? 0) == 1
        settingsLocalCard?.isHidden = useApi
        settingsApiCard?.isHidden = !useApi
        settingsHardwareCard?.isHidden = useApi
        refreshModelsButton?.isHidden = useApi
        applyModelsButton?.isHidden = useApi
        saveApiButton?.isHidden = !useApi
        aiApiKeyField?.isEnabled = useApi
        aiBaseUrlField?.isEnabled = useApi
        // When Hardware is hidden (API mode), pull Features / Chrome up so there
        // isn’t an empty gap — keep action buttons pinned to the bottom.
        let featuresY: CGFloat = useApi ? 292 : 216
        let chromeY: CGFloat = useApi ? 216 : 140
        settingsFeaturesCard?.frame = NSRect(x: 28, y: featuresY, width: 424, height: 64)
        settingsChromeCard?.frame = NSRect(x: 28, y: chromeY, width: 424, height: 64)
        refreshModelsButton?.frame = NSRect(x: 28, y: 20, width: 130, height: 32)
        applyModelsButton?.frame = NSRect(x: 168, y: 20, width: 120, height: 32)
        // API: Save sits where Refresh was (left); Done stays bottom-right.
        saveApiButton?.frame = NSRect(x: 28, y: 20, width: 120, height: 32)
        settingsDoneButton?.frame = NSRect(x: 372, y: 20, width: 80, height: 32)
        if !useApi {
            setApiConnectedTag(visible: false)
        }
    }

    @objc private func aiProviderChanged(_ sender: NSSegmentedControl) {
        updateSettingsModeUI()
        if sender.selectedSegment == 1 {
            let hasKey = !(aiApiKeyField?.stringValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ?? true)
            setApiConnectedTag(visible: hasKey && aiConfiguredCached)
            aiHelpLabel?.stringValue = (hasKey && aiConfiguredCached)
                ? "Cloud API key saved — used for rewrite / generate"
                : "Paste your OpenAI / Groq / compatible key, then Save"
            DispatchQueue.main.async { [weak self] in
                self?.aiApiKeyField?.window?.makeFirstResponder(self?.aiApiKeyField)
            }
        } else {
            setApiConnectedTag(visible: false)
            aiHelpLabel?.stringValue = "Using local models"
            persistLocalProvider()
        }
    }

    private func persistLocalProvider() {
        let payload: [String: Any] = [
            "provider": "local",
            "apiKey": aiApiKeyField?.stringValue ?? "",
            "baseUrl": aiBaseUrlField?.stringValue ?? "",
            "model": "",
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let json = String(data: data, encoding: .utf8) else {
            return
        }
        DispatchQueue.global(qos: .utility).async { [weak self] in
            _ = self?.runService(["set-ai", json])
        }
    }

    @objc private func saveAiSettings() {
        let useApi = (aiProviderControl?.selectedSegment ?? 0) == 1
        let provider = useApi ? "api" : "local"
        let apiKey = aiApiKeyField?.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let baseUrl = aiBaseUrlField?.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if useApi && apiKey.isEmpty {
            aiHelpLabel?.stringValue = "Add an API key first"
            setApiConnectedTag(visible: false)
            return
        }
        setApiConnectedTag(visible: false)
        aiHelpLabel?.stringValue = useApi ? "Saving and testing key…" : "Switching to local models…"
        // Don't set global `busy` — that blocked Restart while Groq verify ran.
        saveApiButton?.isEnabled = false
        let payload: [String: Any] = [
            "provider": provider,
            "apiKey": apiKey,
            "baseUrl": baseUrl,
            "model": "",
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let json = String(data: data, encoding: .utf8) else {
            saveApiButton?.isEnabled = true
            aiHelpLabel?.stringValue = "Could not encode settings"
            return
        }
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let result = self?.runService(["set-ai", json]) ?? ["ok": false, "detail": "Save failed"]
            DispatchQueue.main.async {
                self?.saveApiButton?.isEnabled = true
                let ok = (result["ok"] as? Bool) ?? false
                let detail = (result["detail"] as? String) ?? ""
                if ok {
                    self?.aiConfiguredCached = useApi
                    self?.setApiConnectedTag(visible: useApi)
                    self?.aiHelpLabel?.stringValue = useApi
                        ? (detail.isEmpty ? "API key saved and verified" : detail)
                        : "Using local models"
                } else {
                    self?.aiConfiguredCached = false
                    self?.setApiConnectedTag(visible: false)
                    self?.aiHelpLabel?.stringValue = detail.isEmpty ? "Could not verify API key" : detail
                }
            }
        }
    }

    @objc private func applyModelSettings() {
        selectedGrammar = selectedModelName(from: grammarPopup) ?? selectedGrammar
        selectedWriting = selectedModelName(from: writingPopup) ?? selectedWriting
        let ram = Int(ramSlider?.doubleValue.rounded() ?? Double(max(4, systemRamGB / 2)))
        let gpu = Int(gpuSlider?.doubleValue.rounded() ?? 75)
        modelsHelpLabel.stringValue = "Saving and restarting server…"
        busy = true
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self else { return }
            let result = self.runService([
                "set-models",
                self.selectedGrammar,
                self.selectedWriting,
                String(ram),
                String(gpu),
            ])
            DispatchQueue.main.async {
                self.busy = false
                let ok = (result["ok"] as? Bool) ?? false
                let detail = (result["detail"] as? String) ?? ""
                let gLabel = self.displayLabel(for: self.selectedGrammar)
                let wLabel = self.displayLabel(for: self.selectedWriting)
                self.modelsHelpLabel.stringValue = ok
                    ? "Using grammar “\(gLabel)” and writing “\(wLabel)”."
                    : (detail.isEmpty ? "Saved, but the server may still be offline." : detail)
                self.applyHardwareFields(from: result)
                self.applyHealth(ok: ok, detail: ok ? "Server online" : "Server offline")
            }
        }
    }

    @objc private func powerToggled(_ sender: NSSwitch) {
        if busy || syncingPowerSwitch { return }
        busy = true
        let wantOn = sender.state == .on
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let result: [String: Any]
            if wantOn {
                result = self?.runService(["restart"]) ?? ["ok": false, "detail": "Server offline"]
            } else {
                result = self?.runService(["stop"]) ?? ["ok": true, "detail": "Server offline"]
            }
            DispatchQueue.main.async {
                self?.busy = false
                self?.applyHealth(ok: (result["ok"] as? Bool) ?? false,
                                  detail: (result["detail"] as? String) ?? "Server offline")
            }
        }
    }

    @objc private func restartServer() {
        if busy { return }
        busy = true
        // Reset to empty dark card, then charge green left → right.
        statusCard?.layer?.backgroundColor = surface.cgColor
        animateStatusFill(to: 0, color: okColor, animated: false)
        setRestartUI(active: true, progress: 0.1, title: "Restarting…", detail: "Stopping old server…")
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self else { return }

            // Single restart path (stop + start) so progress/UI stay consistent.
            DispatchQueue.main.async {
                self.setRestartUI(active: true, progress: 0.35, title: "Restarting…", detail: "Starting server…")
            }
            let result = self.runService(["restart"])
            let ok = (result["ok"] as? Bool) ?? false

            DispatchQueue.main.async {
                self.setRestartUI(
                    active: true,
                    progress: ok ? 1.0 : 0.9,
                    title: "Restarting…",
                    detail: ok ? "Server is back online" : "Checking…"
                )
            }

            // Brief follow-up status poll in case health was mid-boot.
            var finalOk = ok
            var detail = (result["detail"] as? String) ?? (ok ? "Server online" : "Server offline")
            if !finalOk {
                for _ in 0..<8 {
                    Thread.sleep(forTimeInterval: 0.4)
                    let status = self.runService(["status"])
                    if (status["ok"] as? Bool) == true {
                        finalOk = true
                        detail = (status["detail"] as? String) ?? "Server online"
                        break
                    }
                }
            }

            DispatchQueue.main.async {
                self.setRestartUI(
                    active: true,
                    progress: 1.0,
                    title: "Restarting…",
                    detail: finalOk ? "Done" : "Restart failed"
                )
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
                    self.busy = false
                    self.setRestartUI(active: false, progress: 0, title: nil, detail: nil)
                    self.applyHealth(ok: finalOk, detail: detail)
                }
            }
        }
    }

    private func setRestartUI(active: Bool, progress: Double, title: String?, detail: String?) {
        restartButton?.isEnabled = !active
        restartButton?.isHidden = active
        restartSpinner?.isHidden = !active
        if active {
            restartSpinner?.startAnimation(nil)
            if let title { statusTitle.stringValue = title }
            if let detail { statusDetail.stringValue = detail }
            statusTitle.textColor = textColor
            statusDetail.textColor = textColor.withAlphaComponent(0.85)
            statusDot.layer?.backgroundColor = NSColor.white.cgColor
            restartButton?.contentTintColor = textColor
            // Dark base with green charging fill left → right
            statusCard?.layer?.backgroundColor = surface.cgColor
            animateStatusFill(to: progress, color: okColor)
        } else {
            restartSpinner?.stopAnimation(nil)
        }
    }

    private func animateStatusFill(to fraction: Double, color: NSColor, animated: Bool = true) {
        guard let card = statusCard, let fill = statusFill else { return }
        let clamped = min(max(fraction, 0), 1)
        let targetWidth = card.bounds.width * CGFloat(clamped)
        fill.layer?.backgroundColor = color.cgColor
        let target = NSRect(x: 0, y: 0, width: targetWidth, height: card.bounds.height)
        if animated {
            NSAnimationContext.runAnimationGroup { ctx in
                ctx.duration = 0.35
                ctx.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
                fill.animator().frame = target
            }
        } else {
            fill.frame = target
        }
    }

    private func applyStatusCardStyle(online: Bool) {
        if online {
            statusCard?.layer?.backgroundColor = okColor.cgColor
            animateStatusFill(to: 1, color: okColor, animated: false)
            statusTitle.textColor = textColor
            statusDetail.textColor = textColor.withAlphaComponent(0.9)
            statusDot.layer?.backgroundColor = NSColor.white.cgColor
            restartButton?.contentTintColor = textColor
        } else {
            statusCard?.layer?.backgroundColor = offlineColor.cgColor
            animateStatusFill(to: 0, color: okColor, animated: false)
            statusTitle.textColor = textColor
            statusDetail.textColor = textColor.withAlphaComponent(0.9)
            statusDot.layer?.backgroundColor = NSColor.white.cgColor
            restartButton?.contentTintColor = textColor
        }
    }

    private func startServerAsync() {
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            _ = self?.runService(["start"])
            DispatchQueue.main.async { self?.refreshHealth() }
        }
    }

    private func refreshHealth() {
        if busy { return }
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let result = self?.runService(["status"]) ?? ["ok": false, "detail": "Server offline"]
            DispatchQueue.main.async {
                let linked = (result["extension_linked"] as? Bool) ?? false
                var detail = (result["detail"] as? String) ?? "Server offline"
                if (result["ok"] as? Bool) == true {
                    detail = linked ? "Chrome extension linked" : "Waiting for Chrome extension…"
                }
                self?.applyHealth(ok: (result["ok"] as? Bool) ?? false, detail: detail)
                if let g = result["grammar_model"] as? String { self?.selectedGrammar = g }
                if let w = result["writing_model"] as? String { self?.selectedWriting = w }
            }
        }
    }

    private func applyHealth(ok: Bool, detail: String) {
        online = ok
        statusTitle.stringValue = ok ? "Server online" : "Server offline"
        statusDetail.stringValue = detail
        statusDot.layer?.backgroundColor = NSColor.white.cgColor
        applyStatusCardStyle(online: ok)
        syncingPowerSwitch = true
        powerSwitch.state = ok ? .on : .off
        syncingPowerSwitch = false
        configureStatusButton(statusItem.button, online: ok)
        if let menuItem = statusItem.menu?.item(withTag: 100) {
            menuItem.title = "Status: \(detail)"
        }
        updateMenuBarBanner()
    }

    private func resourceURL() -> URL? {
        Bundle.main.resourceURL?.appendingPathComponent("ThothHome")
    }

    private func supportHome() -> URL {
        let base = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Thoth/Home")
        try? FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        return base
    }

    private func pythonExecutable() -> String {
        let candidates = [
            supportHome().appendingPathComponent(".venv/bin/python").path,
            "/usr/bin/python3",
            "/opt/homebrew/bin/python3",
        ]
        for path in candidates where FileManager.default.isExecutableFile(atPath: path) {
            return path
        }
        return "/usr/bin/python3"
    }

    @discardableResult
    private func runService(_ args: [String]) -> [String: Any] {
        guard let resources = resourceURL() else {
            return ["ok": false, "detail": "Missing app resources"]
        }
        let support = supportHome()
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: pythonExecutable())
        proc.arguments = ["-m", "macos.menubar.service"] + args
        proc.currentDirectoryURL = resources
        var env = ProcessInfo.processInfo.environment
        env["THOTH_BUNDLE_RESOURCES"] = Bundle.main.resourcePath ?? ""
        env["THOTH_APP_EXECUTABLE"] = Bundle.main.executablePath ?? ""
        env["PYTHONUNBUFFERED"] = "1"
        var pythonPath = [support.path, resources.path]
        let versions = ["3.9", "3.10", "3.11", "3.12", "3.13", "3.14"]
        for v in versions {
            let site = support.appendingPathComponent(".venv/lib/python\(v)/site-packages")
            if FileManager.default.fileExists(atPath: site.path) {
                pythonPath.insert(site.path, at: 0)
                break
            }
        }
        if let existing = env["PYTHONPATH"], !existing.isEmpty {
            pythonPath.append(existing)
        }
        env["PYTHONPATH"] = pythonPath.joined(separator: ":")
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + (env["PATH"] ?? "")
        proc.environment = env

        let out = Pipe()
        let err = Pipe()
        proc.standardOutput = out
        proc.standardError = err
        do {
            try proc.run()
            proc.waitUntilExit()
        } catch {
            return ["ok": false, "detail": "Could not run helper: \(error.localizedDescription)"]
        }
        let data = out.fileHandleForReading.readDataToEndOfFile()
        if let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            return obj
        }
        // Helpers sometimes print warnings before the JSON line — parse the last object.
        if let text = String(data: data, encoding: .utf8) {
            for line in text.split(whereSeparator: \.isNewline).reversed() {
                let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
                guard trimmed.hasPrefix("{"),
                      let lineData = trimmed.data(using: .utf8),
                      let obj = try? JSONSerialization.jsonObject(with: lineData) as? [String: Any]
                else { continue }
                return obj
            }
            return ["ok": proc.terminationStatus == 0, "detail": text.isEmpty ? "Server offline" : text]
        }
        return ["ok": proc.terminationStatus == 0, "detail": "Server offline"]
    }

    private func iconsDirectory() -> URL? {
        resourceURL()?.appendingPathComponent("macos/menubar/icons")
    }

    private func loadTemplateIcon(named name: String) -> NSImage? {
        guard let dir = iconsDirectory() else { return nil }
        let url = dir.appendingPathComponent("\(name).png")
        guard let image = NSImage(contentsOf: url) else { return nil }
        image.isTemplate = true
        image.size = NSSize(width: 24, height: 24)
        return image
    }

    private func loadBrandMark() -> NSImage? {
        guard let dir = iconsDirectory() else { return nil }
        return NSImage(contentsOf: dir.appendingPathComponent("thoth-mark.png"))
    }
}

enum ThothMain {
    /// CLI: `Thoth service <cmd…>` runs the Python helper and exits (no GUI).
    /// Prevents accidental menu-bar loss when a tool invokes the binary with args.
    static func runServiceCLI(arguments: [String]) -> Never {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let support = home.appendingPathComponent("Library/Application Support/Thoth/Home")
        let resources = Bundle.main.resourceURL?.appendingPathComponent("ThothHome")
        var python = "/usr/bin/python3"
        let venvPython = support.appendingPathComponent(".venv/bin/python")
        if FileManager.default.isExecutableFile(atPath: venvPython.path) {
            python = venvPython.path
        } else if FileManager.default.isExecutableFile(atPath: "/opt/homebrew/bin/python3") {
            python = "/opt/homebrew/bin/python3"
        }

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: python)
        proc.arguments = ["-m", "macos.menubar.service"] + Array(arguments.dropFirst())
        if let resources, FileManager.default.fileExists(atPath: resources.path) {
            proc.currentDirectoryURL = resources
        }
        var env = ProcessInfo.processInfo.environment
        env["THOTH_BUNDLE_RESOURCES"] = Bundle.main.resourcePath ?? ""
        env["THOTH_APP_EXECUTABLE"] = Bundle.main.executablePath ?? ""
        env["PYTHONUNBUFFERED"] = "1"
        var pythonPath = [support.path]
        if let resources { pythonPath.append(resources.path) }
        let versions = ["3.9", "3.10", "3.11", "3.12", "3.13", "3.14"]
        for v in versions {
            let site = support.appendingPathComponent(".venv/lib/python\(v)/site-packages")
            if FileManager.default.fileExists(atPath: site.path) {
                pythonPath.insert(site.path, at: 0)
                break
            }
        }
        if let existing = env["PYTHONPATH"], !existing.isEmpty {
            pythonPath.append(existing)
        }
        env["PYTHONPATH"] = pythonPath.joined(separator: ":")
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + (env["PATH"] ?? "")
        proc.environment = env
        proc.standardOutput = FileHandle.standardOutput
        proc.standardError = FileHandle.standardError
        do {
            try proc.run()
            proc.waitUntilExit()
            exit(proc.terminationStatus)
        } catch {
            fputs("Thoth: could not run service helper: \(error)\n", stderr)
            exit(1)
        }
    }

    static func main() {
        let args = CommandLine.arguments
        if args.count > 1, args[1] == "service" {
            runServiceCLI(arguments: Array(args.dropFirst()))
        }
        if args.count > 1, args[1] == "sm-status" {
            if #available(macOS 13.0, *) {
                func label(_ s: SMAppService.Status) -> String {
                    switch s {
                    case .enabled: return "enabled"
                    case .requiresApproval: return "requiresApproval"
                    case .notRegistered: return "notRegistered"
                    case .notFound: return "notFound"
                    @unknown default: return "unknown"
                    }
                }
                let main = label(SMAppService.mainApp.status)
                let login = label(SMAppService.loginItem(identifier: "com.thoth.macos.LaunchAtLogin").status)
                print("{\"mainApp\":\"\(main)\",\"loginItem\":\"\(login)\"}")
            } else {
                print("{\"error\":\"macOS 13+ required\"}")
            }
            exit(0)
        }

        // Single-instance: the LaunchAgent used to start a second GUI copy.
        if let bid = Bundle.main.bundleIdentifier {
            let others = NSRunningApplication.runningApplications(withBundleIdentifier: bid)
                .filter { $0.processIdentifier != ProcessInfo.processInfo.processIdentifier }
            if let existing = others.first {
                existing.activate(options: [.activateAllWindows, .activateIgnoringOtherApps])
                exit(0)
            }
        }

        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.run()
    }
}

ThothMain.main()
