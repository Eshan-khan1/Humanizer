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
    private var featureGrammarSwitch: NSSwitch!
    private var featureRewriteSwitch: NSSwitch!
    private var featureGenerateSwitch: NSSwitch!
    private var featuresHelpLabel: NSTextField!
    private var featuresSummaryLabel: NSTextField!
    private var settingsRootView: NSView!
    private var settingsFeaturesView: NSView!
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
    private var availableModels: [String] = []
    private var modelLabels: [String: String] = [:]
    private var selectedGrammar = "humanizer-grammar"
    private var selectedWriting = "humanizer-writing"
    private var menuBarPromptPresented = false
    private var lastStatusRecreate = Date.distantPast
    private var didAutoResetControlCenter = false
    private var menuBarAutoConnectRunning = false

    private let defaults = UserDefaults.standard
    private let menuBarAckKey = "humanizer.menuBar.acknowledged"

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        ProcessInfo.processInfo.processName = "Humanizer"
        setupStatusItem()
        setupWindow()
        setupSettingsWindow()
        setupMenuBarConnectSheet()
        setupChromeConnectSheet()
        // Keep the window available, but prioritize attaching the menu bar icon first.
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        // Register with macOS Login Items & Background Activity (SMAppService).
        let regKey = "humanizer.background.reregistered.v3"
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
        menu.addItem(NSMenuItem(title: "Open Humanizer", action: #selector(showWindow), keyEquivalent: "o"))
        menu.addItem(NSMenuItem(title: "Settings…", action: #selector(showSettings), keyEquivalent: ","))
        menu.addItem(NSMenuItem(title: "Add to Menu Bar…", action: #selector(openMenuBarSettings), keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "Restart server", action: #selector(restartServer), keyEquivalent: "r"))
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Quit Humanizer", action: #selector(quitApp), keyEquivalent: "q"))
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
        button.toolTip = "Humanizer — local writing server"
        button.appearsDisabled = false
        button.setAccessibilityTitle("Humanizer")
    }

    private func setupWindow() {
        let rect = NSRect(x: 0, y: 0, width: 420, height: 330)
        let style: NSWindow.StyleMask = [.titled, .closable, .miniaturizable]
        let win = NSWindow(contentRect: rect, styleMask: style, backing: .buffered, defer: false)
        win.title = "Humanizer"
        win.backgroundColor = bg
        win.isReleasedWhenClosed = false
        win.center()
        win.delegate = self

        guard let content = win.contentView else { return }

        let mark = NSImageView(frame: NSRect(x: 28, y: 238, width: 56, height: 56))
        mark.image = loadBrandMark()
        mark.imageScaling = .scaleProportionallyUpOrDown
        content.addSubview(mark)

        let title = NSTextField(labelWithString: "Humanizer")
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

        let title = NSTextField(labelWithString: "Allow Humanizer in Background?")
        title.font = .systemFont(ofSize: 20, weight: .bold)
        title.textColor = textColor
        title.alignment = .center
        title.frame = NSRect(x: 28, y: 272, width: 404, height: 28)
        content.addSubview(title)

        let body = NSTextField(wrappingLabelWithString: "macOS requires two permissions for menu bar apps: Background Activity (so Humanizer can stay running) and Menu Bar (so the H icon can appear near the clock).")
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

        let steps = NSTextField(wrappingLabelWithString: "macOS parked this icon off-screen (StatusKit bug).\n1. Click Fix Menu Bar Icon\n2. In Menu Bar settings turn Humanizer OFF, then ON\n3. Look for the H near the clock")
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

    /// Registers Humanizer with System Settings → Login Items & Background Activity.
    @discardableResult
    private func registerBackgroundActivity(forceReregister: Bool = false) -> String {
        // Drop the old silent LaunchAgent — confuses Background Task Management.
        let legacy = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents/com.humanizer.app.plist")
        let legacy2 = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents/com.humanizer.macos.plist")
        for path in [legacy, legacy2] where FileManager.default.fileExists(atPath: path.path) {
            try? FileManager.default.removeItem(at: path)
        }
        let uid = getuid()
        for label in [
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

        let loginItem = SMAppService.loginItem(identifier: "com.humanizer.macos.LaunchAtLogin")
        let main = SMAppService.mainApp
        // Do NOT register the LaunchAgent that runs Contents/MacOS/Humanizer —
        // that starts a second GUI process and a second menu bar icon.
        let staleAgents = [
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
            try? SMAppService.loginItem(identifier: "com.humanizer.app.LaunchAtLogin").unregister()
            // Also drop the old mainApp registration for the previous bundle id if present —
            // SMAppService.mainApp only covers this process's bundle.
        }

        // Only open the helper when first registering — avoids a second Humanizer launch.
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
        let login = statusLabel(SMAppService.loginItem(identifier: "com.humanizer.macos.LaunchAtLogin").status)
        return "main=\(main) loginItem=\(login)"
    }

    private func writeBackgroundStatusLog(_ line: String) {
        let dir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/Humanizer")
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
        let rect = NSRect(x: 0, y: 0, width: 480, height: 700)
        let style: NSWindow.StyleMask = [.titled, .closable]
        let win = NSWindow(contentRect: rect, styleMask: style, backing: .buffered, defer: false)
        win.title = "Humanizer Settings"
        win.backgroundColor = bg
        win.isReleasedWhenClosed = false
        win.center()
        win.delegate = self

        guard let content = win.contentView else { return }

        let root = NSView(frame: content.bounds)
        root.autoresizingMask = [.width, .height]
        content.addSubview(root)
        settingsRootView = root

        let heading = NSTextField(labelWithString: "Settings")
        heading.font = .systemFont(ofSize: 24, weight: .bold)
        heading.textColor = textColor
        heading.frame = NSRect(x: 28, y: 642, width: 300, height: 32)
        root.addSubview(heading)

        // Local LLM section card
        let card = NSView(frame: NSRect(x: 28, y: 428, width: 424, height: 200))
        card.wantsLayer = true
        card.layer?.backgroundColor = surface.cgColor
        card.layer?.cornerRadius = 14
        root.addSubview(card)

        let section = NSTextField(labelWithString: "Local LLM")
        section.font = .systemFont(ofSize: 15, weight: .semibold)
        section.textColor = textColor
        section.frame = NSRect(x: 20, y: 158, width: 280, height: 22)
        card.addSubview(section)

        let blurb = NSTextField(wrappingLabelWithString: "Models installed on this Mac via Ollama. Pick which one Humanizer should use for grammar checks and for rewrite / generate.")
        blurb.font = .systemFont(ofSize: 12)
        blurb.textColor = muted
        blurb.frame = NSRect(x: 20, y: 118, width: 384, height: 40)
        card.addSubview(blurb)

        let grammarLabel = NSTextField(labelWithString: "Grammar model")
        grammarLabel.font = .systemFont(ofSize: 12)
        grammarLabel.textColor = muted
        grammarLabel.frame = NSRect(x: 20, y: 88, width: 120, height: 18)
        card.addSubview(grammarLabel)

        let grammar = NSPopUpButton(frame: NSRect(x: 150, y: 82, width: 250, height: 28), pullsDown: false)
        grammar.target = self
        grammar.action = #selector(modelSelectionChanged(_:))
        card.addSubview(grammar)
        grammarPopup = grammar

        let writingLabel = NSTextField(labelWithString: "Writing model")
        writingLabel.font = .systemFont(ofSize: 12)
        writingLabel.textColor = muted
        writingLabel.frame = NSRect(x: 20, y: 50, width: 120, height: 18)
        card.addSubview(writingLabel)

        let writing = NSPopUpButton(frame: NSRect(x: 150, y: 44, width: 250, height: 28), pullsDown: false)
        writing.target = self
        writing.action = #selector(modelSelectionChanged(_:))
        card.addSubview(writing)
        writingPopup = writing

        let help = NSTextField(labelWithString: "Loading models from Ollama…")
        help.font = .systemFont(ofSize: 11)
        help.textColor = muted
        help.frame = NSRect(x: 20, y: 14, width: 384, height: 18)
        card.addSubview(help)
        modelsHelpLabel = help

        // Features nav row → opens Features page
        let featuresCard = NSView(frame: NSRect(x: 28, y: 328, width: 424, height: 84))
        featuresCard.wantsLayer = true
        featuresCard.layer?.backgroundColor = surface.cgColor
        featuresCard.layer?.cornerRadius = 14
        root.addSubview(featuresCard)

        let featuresSection = NSTextField(labelWithString: "Features")
        featuresSection.font = .systemFont(ofSize: 15, weight: .semibold)
        featuresSection.textColor = textColor
        featuresSection.frame = NSRect(x: 20, y: 46, width: 280, height: 22)
        featuresCard.addSubview(featuresSection)

        let featuresSummary = NSTextField(labelWithString: "Grammar, Rewrite, Generate")
        featuresSummary.font = .systemFont(ofSize: 12)
        featuresSummary.textColor = muted
        featuresSummary.frame = NSRect(x: 20, y: 18, width: 320, height: 20)
        featuresCard.addSubview(featuresSummary)
        featuresSummaryLabel = featuresSummary

        let featuresChevron = NSTextField(labelWithString: "›")
        featuresChevron.font = .systemFont(ofSize: 22, weight: .regular)
        featuresChevron.textColor = muted
        featuresChevron.alignment = .right
        featuresChevron.frame = NSRect(x: 370, y: 26, width: 30, height: 28)
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

        // API key section card
        let aiCard = NSView(frame: NSRect(x: 28, y: 148, width: 424, height: 164))
        aiCard.wantsLayer = true
        aiCard.layer?.backgroundColor = surface.cgColor
        aiCard.layer?.cornerRadius = 14
        root.addSubview(aiCard)

        let aiSection = NSTextField(labelWithString: "API key")
        aiSection.font = .systemFont(ofSize: 15, weight: .semibold)
        aiSection.textColor = textColor
        aiSection.frame = NSRect(x: 20, y: 126, width: 200, height: 22)
        aiCard.addSubview(aiSection)

        let aiBlurb = NSTextField(wrappingLabelWithString: "Use your own OpenAI, Groq, or compatible key for rewrite / generate. Leave on Local to stay fully offline.")
        aiBlurb.font = .systemFont(ofSize: 12)
        aiBlurb.textColor = muted
        aiBlurb.frame = NSRect(x: 20, y: 96, width: 384, height: 30)
        aiCard.addSubview(aiBlurb)

        let provider = NSSegmentedControl(labels: ["Local", "API"], trackingMode: .selectOne, target: self, action: #selector(aiProviderChanged(_:)))
        provider.frame = NSRect(x: 20, y: 66, width: 160, height: 24)
        provider.selectedSegment = 0
        aiCard.addSubview(provider)
        aiProviderControl = provider

        let keyField = NSSecureTextField(frame: NSRect(x: 190, y: 64, width: 214, height: 28))
        keyField.placeholderString = "API key"
        keyField.isEnabled = false
        keyField.font = .systemFont(ofSize: 12)
        aiCard.addSubview(keyField)
        aiApiKeyField = keyField

        let baseField = NSTextField(frame: NSRect(x: 20, y: 30, width: 384, height: 28))
        baseField.placeholderString = "Base URL (optional)"
        baseField.isEnabled = false
        baseField.font = .systemFont(ofSize: 12)
        aiCard.addSubview(baseField)
        aiBaseUrlField = baseField

        let aiHelp = NSTextField(labelWithString: "Using local models")
        aiHelp.font = .systemFont(ofSize: 11)
        aiHelp.textColor = muted
        aiHelp.frame = NSRect(x: 20, y: 8, width: 384, height: 16)
        aiCard.addSubview(aiHelp)
        aiHelpLabel = aiHelp

        // Chrome extension section
        let chromeCard = NSView(frame: NSRect(x: 28, y: 48, width: 424, height: 84))
        chromeCard.wantsLayer = true
        chromeCard.layer?.backgroundColor = surface.cgColor
        chromeCard.layer?.cornerRadius = 14
        root.addSubview(chromeCard)

        let chromeSection = NSTextField(labelWithString: "Chrome extension")
        chromeSection.font = .systemFont(ofSize: 15, weight: .semibold)
        chromeSection.textColor = textColor
        chromeSection.frame = NSRect(x: 20, y: 48, width: 220, height: 22)
        chromeCard.addSubview(chromeSection)

        let chromeBlurb = NSTextField(wrappingLabelWithString: "Load the bundled extension so Chrome can talk to this app automatically.")
        chromeBlurb.font = .systemFont(ofSize: 12)
        chromeBlurb.textColor = muted
        chromeBlurb.frame = NSRect(x: 20, y: 14, width: 240, height: 36)
        chromeCard.addSubview(chromeBlurb)

        let chrome = NSButton(title: "Connect…", target: self, action: #selector(showChromeConnect))
        chrome.bezelStyle = .rounded
        chrome.frame = NSRect(x: 300, y: 26, width: 104, height: 32)
        chrome.toolTip = "Connect Chrome Extension"
        chromeCard.addSubview(chrome)
        chromeConnectButton = chrome

        let refresh = NSButton(title: "Refresh models", target: self, action: #selector(refreshModels))
        refresh.bezelStyle = .rounded
        refresh.frame = NSRect(x: 28, y: 8, width: 120, height: 28)
        root.addSubview(refresh)

        let apply = NSButton(title: "Apply models", target: self, action: #selector(applyModelSettings))
        apply.bezelStyle = .rounded
        apply.frame = NSRect(x: 156, y: 8, width: 110, height: 28)
        root.addSubview(apply)

        let saveAi = NSButton(title: "Save API key", target: self, action: #selector(saveAiSettings))
        saveAi.bezelStyle = .rounded
        saveAi.frame = NSRect(x: 274, y: 8, width: 110, height: 28)
        root.addSubview(saveAi)

        let done = NSButton(title: "Done", target: self, action: #selector(closeSettings))
        done.bezelStyle = .rounded
        done.frame = NSRect(x: 392, y: 8, width: 60, height: 28)
        root.addSubview(done)

        setupFeaturesPage(in: content)
        settingsWindow = win
        showSettingsRoot()
    }

    private func setupFeaturesPage(in content: NSView) {
        let page = NSView(frame: content.bounds)
        page.autoresizingMask = [.width, .height]
        page.isHidden = true
        content.addSubview(page)
        settingsFeaturesView = page

        let back = NSButton(title: "‹ Settings", target: self, action: #selector(showSettingsRoot))
        back.bezelStyle = .inline
        back.isBordered = false
        back.font = .systemFont(ofSize: 18, weight: .semibold)
        back.contentTintColor = muted
        back.frame = NSRect(x: 20, y: 638, width: 130, height: 34)
        back.setAccessibilityLabel("Back to Settings")
        page.addSubview(back)

        let heading = NSTextField(labelWithString: "Features")
        heading.font = .systemFont(ofSize: 24, weight: .bold)
        heading.textColor = textColor
        heading.frame = NSRect(x: 28, y: 600, width: 300, height: 32)
        page.addSubview(heading)

        let blurb = NSTextField(wrappingLabelWithString: "Turn features on or off for the Chrome extension and local server.")
        blurb.font = .systemFont(ofSize: 13)
        blurb.textColor = muted
        blurb.frame = NSRect(x: 28, y: 560, width: 424, height: 36)
        page.addSubview(blurb)

        let card = NSView(frame: NSRect(x: 28, y: 380, width: 424, height: 164))
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
        featuresHelp.frame = NSRect(x: 28, y: 340, width: 424, height: 18)
        page.addSubview(featuresHelp)
        featuresHelpLabel = featuresHelp

        let done = NSButton(title: "Done", target: self, action: #selector(closeSettings))
        done.bezelStyle = .rounded
        done.frame = NSRect(x: 372, y: 28, width: 80, height: 32)
        page.addSubview(done)
    }

    @objc private func showSettingsRoot() {
        settingsRootView?.isHidden = false
        settingsFeaturesView?.isHidden = true
        settingsWindow?.title = "Humanizer Settings"
        updateFeaturesSummaryLabel()
    }

    @objc private func showFeaturesPage() {
        loadFeatureSettings()
        settingsRootView?.isHidden = true
        settingsFeaturesView?.isHidden = false
        settingsWindow?.title = "Features"
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

        let title = NSTextField(labelWithString: "Link Chrome to Humanizer")
        title.font = .systemFont(ofSize: 20, weight: .bold)
        title.textColor = textColor
        title.alignment = .center
        title.frame = NSRect(x: 28, y: 300, width: 404, height: 28)
        content.addSubview(title)

        let body = NSTextField(wrappingLabelWithString: "One-time setup: load the bundled extension from Application Support. After that, the extension reconnects to this app automatically whenever Humanizer is running.")
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
                    .appendingPathComponent("Library/Application Support/Humanizer/ChromeExtension").path)
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
                    .appendingPathComponent("Library/Application Support/Humanizer/ChromeExtension").path)
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
                alert.informativeText = "Look for the Humanizer H near the clock."
                alert.addButton(withTitle: "OK")
                alert.runModal()
            } else {
                let alert = NSAlert()
                alert.messageText = "Still waiting for Menu Bar access"
                alert.informativeText = """
                In System Settings → Menu Bar, find Humanizer and turn it ON.

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
            alert.messageText = "Allow Humanizer in the Menu Bar"
            alert.informativeText = """
            Turn Humanizer ON in System Settings → Menu Bar.
            Humanizer will reconnect automatically the next time it opens.
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
            .appendingPathComponent("Library/Logs/Humanizer")
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
        case "humanizer-writing", "qwen-7b-trained":
            return "Qwen 7B / trained"
        case "humanizer-grammar":
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
        aiProviderControl?.selectedSegment = useApi ? 1 : 0
        aiApiKeyField?.stringValue = (result["ai_api_key"] as? String) ?? ""
        aiBaseUrlField?.stringValue = (result["ai_base_url"] as? String) ?? ""
        updateAiFieldsEnabled()
        if useApi {
            let configured = (result["ai_configured"] as? Bool) ?? false
            aiHelpLabel?.stringValue = configured
                ? "Cloud API key saved — used for rewrite / generate"
                : "Choose API and paste your key, then Save API key"
        } else {
            aiHelpLabel?.stringValue = "Using local models"
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

    private func updateAiFieldsEnabled() {
        let useApi = (aiProviderControl?.selectedSegment ?? 0) == 1
        aiApiKeyField?.isEnabled = useApi
        aiBaseUrlField?.isEnabled = useApi
        if !useApi {
            aiHelpLabel?.stringValue = "Using local models"
        }
    }

    @objc private func aiProviderChanged(_ sender: NSSegmentedControl) {
        updateAiFieldsEnabled()
        if sender.selectedSegment == 1 {
            aiHelpLabel?.stringValue = "Paste your OpenAI / Groq / compatible key, then Save"
            aiApiKeyField?.window?.makeFirstResponder(aiApiKeyField)
        }
    }

    @objc private func saveAiSettings() {
        let useApi = (aiProviderControl?.selectedSegment ?? 0) == 1
        let provider = useApi ? "api" : "local"
        let apiKey = aiApiKeyField?.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let baseUrl = aiBaseUrlField?.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if useApi && apiKey.isEmpty {
            aiHelpLabel?.stringValue = "Add an API key first"
            return
        }
        aiHelpLabel?.stringValue = useApi ? "Saving and testing key…" : "Switching to local models…"
        busy = true
        let payload: [String: Any] = [
            "provider": provider,
            "apiKey": apiKey,
            "baseUrl": baseUrl,
            "model": "",
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let json = String(data: data, encoding: .utf8) else {
            busy = false
            aiHelpLabel?.stringValue = "Could not encode settings"
            return
        }
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let result = self?.runService(["set-ai", json]) ?? ["ok": false, "detail": "Save failed"]
            DispatchQueue.main.async {
                self?.busy = false
                let ok = (result["ok"] as? Bool) ?? false
                let detail = (result["detail"] as? String) ?? ""
                if ok {
                    self?.aiHelpLabel?.stringValue = useApi
                        ? (detail.isEmpty ? "API key saved and verified" : detail)
                        : "Using local models"
                } else {
                    self?.aiHelpLabel?.stringValue = detail.isEmpty ? "Could not verify API key" : detail
                }
            }
        }
    }

    @objc private func applyModelSettings() {
        selectedGrammar = selectedModelName(from: grammarPopup) ?? selectedGrammar
        selectedWriting = selectedModelName(from: writingPopup) ?? selectedWriting
        modelsHelpLabel.stringValue = "Saving and restarting server…"
        busy = true
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self else { return }
            let result = self.runService([
                "set-models",
                self.selectedGrammar,
                self.selectedWriting,
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
        Bundle.main.resourceURL?.appendingPathComponent("HumanizerHome")
    }

    private func supportHome() -> URL {
        let base = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Humanizer/Home")
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
        env["HUMANIZER_BUNDLE_RESOURCES"] = Bundle.main.resourcePath ?? ""
        env["HUMANIZER_APP_EXECUTABLE"] = Bundle.main.executablePath ?? ""
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
        let text = String(data: data, encoding: .utf8) ?? ""
        return ["ok": proc.terminationStatus == 0, "detail": text.isEmpty ? "Server offline" : text]
    }

    private func iconsDirectory() -> URL? {
        resourceURL()?.appendingPathComponent("macos/menubar/icons")
    }

    private func loadTemplateIcon(named name: String) -> NSImage? {
        guard let dir = iconsDirectory() else { return nil }
        let url = dir.appendingPathComponent("\(name).png")
        guard let image = NSImage(contentsOf: url) else { return nil }
        image.isTemplate = true
        image.size = NSSize(width: 22, height: 22)
        return image
    }

    private func loadBrandMark() -> NSImage? {
        guard let dir = iconsDirectory() else { return nil }
        return NSImage(contentsOf: dir.appendingPathComponent("humanizer-mark.png"))
    }
}

enum HumanizerMain {
    /// CLI: `Humanizer service <cmd…>` runs the Python helper and exits (no GUI).
    /// Prevents accidental menu-bar loss when a tool invokes the binary with args.
    static func runServiceCLI(arguments: [String]) -> Never {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let support = home.appendingPathComponent("Library/Application Support/Humanizer/Home")
        let resources = Bundle.main.resourceURL?.appendingPathComponent("HumanizerHome")
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
        env["HUMANIZER_BUNDLE_RESOURCES"] = Bundle.main.resourcePath ?? ""
        env["HUMANIZER_APP_EXECUTABLE"] = Bundle.main.executablePath ?? ""
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
            fputs("Humanizer: could not run service helper: \(error)\n", stderr)
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
                let login = label(SMAppService.loginItem(identifier: "com.humanizer.macos.LaunchAtLogin").status)
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

HumanizerMain.main()
