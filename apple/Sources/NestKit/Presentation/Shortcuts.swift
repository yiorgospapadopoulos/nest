import Foundation

/// The modifier keys of a shortcut.
public struct KeyModifiers: OptionSet, Sendable, Hashable {
    public let rawValue: Int

    public init(rawValue: Int) {
        self.rawValue = rawValue
    }

    public static let command = KeyModifiers(rawValue: 1)
    public static let shift = KeyModifiers(rawValue: 2)
    public static let option = KeyModifiers(rawValue: 4)
    public static let control = KeyModifiers(rawValue: 8)

    /// In the order macOS menus show them, with their stored names.
    static let ordered: [(KeyModifiers, symbol: String, name: String)] = [
        (.control, "⌃", "ctrl"), (.option, "⌥", "opt"), (.shift, "⇧", "shift"),
        (.command, "⌘", "cmd"),
    ]

    var symbols: String {
        Self.ordered.filter { contains($0.0) }.map(\.symbol).joined()
    }
}

/// A key and its modifiers, such as ⇧⌘T. `key` is a lowercased character or a named key
/// (`return`, `escape`, `tab`, `delete`, `space`, `up`, `down`, `left`, `right`), or
/// `digits` for Project 1 to 9, whose shortcuts are the modifiers with each digit.
public struct Shortcut: Sendable, Hashable {
    public var key: String
    public var modifiers: KeyModifiers

    public static let digits = "digits"
    static let named: [String: String] = [
        "return": "↩", "escape": "⎋", "tab": "⇥", "delete": "⌫", "space": "Space",
        "up": "↑", "down": "↓", "left": "←", "right": "→",
    ]

    public init(_ key: String, _ modifiers: KeyModifiers = .command) {
        self.key = key
        self.modifiers = modifiers
    }

    /// "⇧⌘T", "⌘↩", "⌘1 … ⌘9".
    public var display: String {
        let mods = modifiers.symbols
        if key == Self.digits {
            return "\(mods)1 … \(mods)9"
        }
        return mods + (Self.named[key] ?? key.uppercased())
    }

    /// "shift+cmd+t", as stored.
    var stored: String {
        (KeyModifiers.ordered.filter { modifiers.contains($0.0) }.map(\.name) + [key])
            .joined(separator: "+")
    }

    /// Reads a stored shortcut; nil for text that is not one.
    init?(stored text: String) {
        var parts = text.split(separator: "+", omittingEmptySubsequences: false).map(String.init)
        guard let key = parts.popLast(), !key.isEmpty else { return nil }
        var modifiers = KeyModifiers()
        for part in parts {
            guard let modifier = KeyModifiers.ordered.first(where: { $0.name == part }) else {
                return nil
            }
            modifiers.insert(modifier.0)
        }
        self.init(key, modifiers)
    }

    /// Whether both would answer the same keys.
    public func overlaps(_ other: Shortcut) -> Bool {
        guard modifiers == other.modifiers else { return false }
        if key == other.key {
            return true
        }
        let digits = Set("123456789".map(String.init))
        return (key == Self.digits && digits.contains(other.key))
            || (other.key == Self.digits && digits.contains(key))
    }

    /// The key a key press names, from its key code for keys without a character, else
    /// from its characters ignoring modifiers; nil for a modifier key alone.
    public static func key(keyCode: UInt16, characters: String?) -> String? {
        let codes: [UInt16: String] = [
            36: "return", 76: "return", 53: "escape", 48: "tab", 51: "delete", 49: "space",
            126: "up", 125: "down", 123: "left", 124: "right",
        ]
        if let named = codes[keyCode] {
            return named
        }
        guard let first = characters?.lowercased().first, !first.isWhitespace else { return nil }
        return String(first)
    }
}

/// The groups of Settings > Keyboard shortcuts.
public enum ShortcutGroup: String, Sendable, CaseIterable {
    case window = "Window"
    case chats = "Chats"
    case projects = "Projects"

    public var actions: [ShortcutAction] {
        ShortcutAction.allCases.filter { $0.group == self }
    }
}

/// Every command with a keyboard shortcut; the defaults are the app's own (B81).
public enum ShortcutAction: String, Sendable, CaseIterable {
    case settings, palette, toggleSidebar, toggleActivity, workspace, board, artifacts
    case newChat, sendMessage, closePane, newTerminal, newBrowser, openInVSCode
    case previousProject, nextProject, project, pixies

    public var title: String {
        switch self {
        case .settings: "Settings"
        case .palette: "Search chats and commands"
        case .toggleSidebar: "Toggle sidebar"
        case .toggleActivity: "Toggle activity panel"
        case .workspace: "Workspace"
        case .board: "Board"
        case .artifacts: "Artifacts"
        case .newChat: "New chat"
        case .sendMessage: "Send message"
        case .closePane: "Close pane"
        case .newTerminal: "New terminal"
        case .newBrowser: "New browser"
        case .openInVSCode: "Open project in VS Code"
        case .previousProject: "Previous project"
        case .nextProject: "Next project"
        case .project: "Project 1 to 9"
        case .pixies: "Pixies"
        }
    }

    public var group: ShortcutGroup {
        switch self {
        case .settings, .palette, .toggleSidebar, .toggleActivity, .workspace, .board,
            .artifacts:
            .window
        case .newChat, .sendMessage, .closePane, .newTerminal, .newBrowser, .openInVSCode:
            .chats
        case .previousProject, .nextProject, .project, .pixies: .projects
        }
    }

    public var defaultShortcut: Shortcut {
        switch self {
        case .settings: Shortcut(",")
        case .palette: Shortcut("k")
        case .toggleSidebar: Shortcut("s", [.command, .control])
        case .toggleActivity: Shortcut("a", [.command, .control])
        case .workspace: Shortcut("1", [.command, .option])
        case .board: Shortcut("2", [.command, .option])
        case .artifacts: Shortcut("3", [.command, .option])
        case .newChat: Shortcut("n")
        case .sendMessage: Shortcut("return")
        case .closePane: Shortcut("w")
        case .newTerminal: Shortcut("t", [.command, .shift])
        case .newBrowser: Shortcut("b", [.command, .shift])
        case .openInVSCode: Shortcut("o", [.command, .shift])
        case .previousProject: Shortcut("[", [.command, .shift])
        case .nextProject: Shortcut("]", [.command, .shift])
        case .project: Shortcut(Shortcut.digits)
        case .pixies: Shortcut("0")
        }
    }
}

/// What recording a new shortcut came to.
public enum ShortcutChange: Sendable, Hashable {
    case saved
    /// Escape alone: the old shortcut stays.
    case cancelled
    /// Another command has it.
    case conflict(ShortcutAction)
    /// macOS or every Mac app uses it.
    case reserved
    /// Without ⌘, ⌃ or ⌥ it would be plain typing.
    case needsModifier
    /// Project 1 to 9 is recorded with a digit.
    case needsDigit

    /// What the recorder says when the keys were refused; nil when they were not.
    public func message(for shortcut: Shortcut) -> String? {
        switch self {
        case .saved, .cancelled: nil
        case .conflict(let other): "\(shortcut.display) is already \(other.title)"
        case .reserved: "\(shortcut.display) is used by macOS"
        case .needsModifier: "Use ⌘, ⌃ or ⌥ with the key"
        case .needsDigit: "Press the modifiers with a digit, such as ⌘1"
        }
    }
}
