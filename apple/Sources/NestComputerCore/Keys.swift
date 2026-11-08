/// The keys the `key` op knows, as macOS virtual key codes (ANSI layout).
public enum KeyCodes {
    public static let table: [String: UInt16] = [
        "return": 36, "tab": 48, "space": 49, "delete": 51, "escape": 53,
        "left": 123, "right": 124, "down": 125, "up": 126,
        "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
        "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "o": 31, "u": 32,
        "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
        "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "9": 25, "7": 26, "8": 28,
        "0": 29,
    ]

    /// The code for a key name, any case.
    public static func code(for name: String) -> UInt16? {
        table[name.lowercased()]
    }
}

/// A modifier of the `key` op, with its `CGEventFlags` bit.
public enum Modifier: String, Sendable, CaseIterable {
    case cmd
    case shift
    case option
    case control

    public var flag: UInt64 {
        switch self {
        case .shift: 0x0002_0000
        case .control: 0x0004_0000
        case .option: 0x0008_0000
        case .cmd: 0x0010_0000
        }
    }

    /// All the flags of a set of modifiers.
    public static func flags(_ modifiers: Set<Modifier>) -> UInt64 {
        modifiers.reduce(0) { $0 | $1.flag }
    }
}
