import Foundation
import Observation

/// The app's keyboard shortcuts: each command's default, or the keys the user chose in
/// Settings, kept between launches (B81).
@MainActor @Observable
public final class ShortcutsStore {
    static let prefix = "shortcuts."

    /// Shortcuts macOS or every Mac app uses, never given to a command.
    static let reserved: [Shortcut] = [
        Shortcut("q"), Shortcut("h"), Shortcut("h", [.command, .option]), Shortcut("m"),
        Shortcut("c"), Shortcut("v"), Shortcut("x"), Shortcut("a"), Shortcut("z"),
        Shortcut("z", [.command, .shift]), Shortcut("`"), Shortcut("tab"), Shortcut("space"),
        Shortcut("f", [.command, .control]),
    ]

    /// The user's choices; commands left out have their default.
    public private(set) var overrides: [ShortcutAction: Shortcut]

    @ObservationIgnored let store: any KeyValueStore

    /// Unreadable stored values are ignored.
    public init(store: any KeyValueStore = UserDefaultsStore()) {
        self.store = store
        var overrides: [ShortcutAction: Shortcut] = [:]
        for action in ShortcutAction.allCases {
            if let shortcut = store.string(forKey: Self.prefix + action.rawValue)
                .flatMap(Shortcut.init(stored:))
            {
                overrides[action] = shortcut
            }
        }
        self.overrides = overrides
    }

    public func shortcut(for action: ShortcutAction) -> Shortcut {
        overrides[action] ?? action.defaultShortcut
    }

    public func isDefault(_ action: ShortcutAction) -> Bool {
        overrides[action] == nil
    }

    public var hasChanges: Bool { !overrides.isEmpty }

    /// Gives the command these keys unless they are refused; a recorded Escape alone cancels.
    @discardableResult
    public func set(_ shortcut: Shortcut, for action: ShortcutAction) -> ShortcutChange {
        let change = check(shortcut, for: action)
        guard change == .saved else { return change }
        if shortcut == action.defaultShortcut {
            overrides[action] = nil
            store.set(nil, forKey: Self.prefix + action.rawValue)
        } else {
            overrides[action] = shortcut
            store.set(shortcut.stored, forKey: Self.prefix + action.rawValue)
        }
        return .saved
    }

    /// Whether the keys can be the command's shortcut, and why not.
    public func check(_ shortcut: Shortcut, for action: ShortcutAction) -> ShortcutChange {
        if shortcut.key == "escape", shortcut.modifiers.isEmpty {
            return .cancelled
        }
        if action == .project, shortcut.key != Shortcut.digits {
            return .needsDigit
        }
        if shortcut.modifiers.isDisjoint(with: [.command, .control, .option]) {
            return .needsModifier
        }
        if Self.reserved.contains(where: { $0.overlaps(shortcut) }) {
            return .reserved
        }
        if let other = ShortcutAction.allCases.first(where: {
            $0 != action && self.shortcut(for: $0).overlaps(shortcut)
        }) {
            return .conflict(other)
        }
        return .saved
    }

    /// A key press while recording the command's shortcut: Project 1 to 9 takes a digit's
    /// modifiers.
    public func record(
        keyCode: UInt16, characters: String?, modifiers: KeyModifiers,
        for action: ShortcutAction
    ) -> (shortcut: Shortcut, change: ShortcutChange)? {
        guard var key = Shortcut.key(keyCode: keyCode, characters: characters) else { return nil }
        if action == .project, "123456789".contains(key), key.count == 1 {
            key = Shortcut.digits
        }
        let shortcut = Shortcut(key, modifiers)
        return (shortcut, set(shortcut, for: action))
    }

    public func restoreDefaults() {
        for action in overrides.keys {
            store.set(nil, forKey: Self.prefix + action.rawValue)
        }
        overrides = [:]
    }
}
