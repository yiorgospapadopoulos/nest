/// What the helper reads from an element's role and its app's bundle.
public enum Roles {
    public static let secureTextField = "AXSecureTextField"

    /// A password-style field: its value is never read, set or typed into.
    public static func isSecure(role: String, subrole: String?) -> Bool {
        role == secureTextField || subrole == secureTextField
    }

    /// A single-line text field, where Return usually submits.
    public static func isSingleLineField(role: String, subrole: String?) -> Bool {
        role == "AXTextField" || role == "AXComboBox" || isSecure(role: role, subrole: subrole)
    }

    /// Whether an app is Chromium or Electron, from the frameworks inside its bundle. Those
    /// apps build their accessibility tree only when asked (`AXManualAccessibility`). Their
    /// frameworks are "Electron Framework", "Chromium Embedded Framework" or named after the
    /// product ("Google Chrome Framework"); other apps' frameworks seldom end in " Framework".
    public static func isChromium(frameworks: [String]) -> Bool {
        frameworks.contains { name in
            let base = name.hasSuffix(".framework") ? String(name.dropLast(10)) : name
            return base.hasSuffix(" Framework")
        }
    }
}
