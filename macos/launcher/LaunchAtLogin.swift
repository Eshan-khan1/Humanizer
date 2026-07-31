import AppKit
import Foundation

/// Tiny login-item helper living in Contents/Library/LoginItems.
/// Opens the parent Humanizer.app, then exits.
enum LaunchAtLoginMain {
    static func main() {
        let helperURL = Bundle.main.bundleURL
        // …/Humanizer.app/Contents/Library/LoginItems/LaunchAtLogin.app
        let parentApp = helperURL
            .deletingLastPathComponent() // LoginItems
            .deletingLastPathComponent() // Library
            .deletingLastPathComponent() // Contents
            .deletingLastPathComponent() // Humanizer.app
        NSWorkspace.shared.open(parentApp)
        // Give LaunchServices a moment; no need to keep this process alive.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
            exit(0)
        }
        RunLoop.main.run(until: Date().addingTimeInterval(1.0))
        exit(0)
    }
}

LaunchAtLoginMain.main()
