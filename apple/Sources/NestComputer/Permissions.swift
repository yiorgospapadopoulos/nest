import AppKit
import ApplicationServices
import NestComputerCore

/// The two permissions the helper needs. macOS grants them to the helper itself, as its
/// own app, not to Nest or the daemon.
enum Permissions {
    static var accessibility: Bool { AXIsProcessTrusted() }
    static var screenRecording: Bool { CGPreflightScreenCaptureAccess() }

    /// Asks macOS (which shows its prompt once) and opens the matching System Settings pane,
    /// where the user switches the helper on. Returns whether it is granted now.
    @MainActor
    static func ask(_ permission: Permission) -> Bool {
        let granted: Bool
        let pane: String
        switch permission {
        case .accessibility:
            // The value of kAXTrustedCheckOptionPrompt, a global Swift 6 will not read.
            let options = ["AXTrustedCheckOptionPrompt": true]
            granted = AXIsProcessTrustedWithOptions(options as CFDictionary)
            pane = "Privacy_Accessibility"
        case .screenRecording:
            granted = CGPreflightScreenCaptureAccess() || CGRequestScreenCaptureAccess()
            pane = "Privacy_ScreenCapture"
        }
        if !granted,
            let url = URL(
                string: "x-apple.systempreferences:com.apple.preference.security?\(pane)")
        {
            NSWorkspace.shared.open(url)
        }
        return granted
    }

    static func requireAccessibility() throws(HelperError) {
        guard accessibility else {
            throw HelperError(.noPermission, "Nest Computer has no Accessibility permission")
        }
    }
}
