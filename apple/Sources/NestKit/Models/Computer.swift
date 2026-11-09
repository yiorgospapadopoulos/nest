import Foundation

/// What kind of thing a chat uses (B150).
public enum ComputerKind: String, UnknownSafeEnum {
    case mac, ios, android, browser
    case unknown

    /// Its Settings row's name.
    public var title: String {
        switch self {
        case .mac: "Mac apps"
        case .ios: "iOS Simulator"
        case .android: "Android Emulator"
        case .browser: "Shared browser"
        case .unknown: "Unknown"
        }
    }
}

/// `GET/PUT /api/computer/settings`, `[computer_use]`.
public struct ComputerUseSettings: Codable, Sendable, Hashable {
    /// Whether any chat may ask to use an app.
    public var enabled: Bool
    /// Whether pixie chats, habit runs and called pixies may use it.
    public var pixies: Bool

    public init(enabled: Bool = false, pixies: Bool = false) {
        self.enabled = enabled
        self.pixies = pixies
    }
}

/// Whether a kind can be used on this computer, and if not, why and where to get it.
public struct ComputerAvailability: Decodable, Sendable, Hashable {
    public var kind: ComputerKind
    public var ready: Bool
    public var reason: String?
    public var link: String?

    public init(kind: ComputerKind, ready: Bool, reason: String? = nil, link: String? = nil) {
        self.kind = kind
        self.ready = ready
        self.reason = reason
        self.link = link
    }
}

/// `GET /api/computer/status`.
public struct ComputerStatus: Decodable, Sendable, Hashable {
    public var enabled: Bool
    public var kinds: [ComputerAvailability]
    /// Whether the helper holds each permission; nil when it could not ask, or off a Mac.
    public var accessibility: Bool?
    public var screenRecording: Bool?

    public init(
        enabled: Bool, kinds: [ComputerAvailability], accessibility: Bool? = nil,
        screenRecording: Bool? = nil
    ) {
        self.enabled = enabled
        self.kinds = kinds
        self.accessibility = accessibility
        self.screenRecording = screenRecording
    }

    public func kind(_ kind: ComputerKind) -> ComputerAvailability? {
        kinds.first { $0.kind == kind }
    }

    enum CodingKeys: String, CodingKey {
        case enabled, kinds, accessibility
        case screenRecording = "screen_recording"
    }
}

/// A permission the helper asks macOS for, by its path in the API.
public enum ComputerPermission: String, Sendable, Hashable, CaseIterable {
    case accessibility
    case screenRecording = "screen_recording"

    public var title: String {
        switch self {
        case .accessibility: "Accessibility"
        case .screenRecording: "Screen Recording"
        }
    }

    public func granted(in status: ComputerStatus) -> Bool? {
        switch self {
        case .accessibility: status.accessibility
        case .screenRecording: status.screenRecording
        }
    }
}

/// `POST /api/computer/permissions/{name}`.
public struct PermissionAnswer: Decodable, Sendable, Hashable {
    public var granted: Bool
}

/// A target a chat holds now, from `computer.state`.
public struct ComputerTarget: Codable, Sendable, Hashable {
    public var key: String
    public var name: String
    /// Where its window is, in points from the main screen's top left; nil until the chat
    /// looked at it, and for devices.
    public var frame: WindowFrame?

    public init(key: String, name: String, frame: WindowFrame? = nil) {
        self.key = key
        self.name = name
        self.frame = frame
    }

    /// A window's place as macOS accessibility gives it: y grows downward.
    public struct WindowFrame: Codable, Sendable, Hashable {
        public var x: Double
        public var y: Double
        public var width: Double
        public var height: Double

        public init(x: Double, y: Double, width: Double, height: Double) {
            self.x = x
            self.y = y
            self.width = width
            self.height = height
        }
    }

    /// A name for a key alone, as the daemon makes one: what follows the kind.
    public static func name(of key: String) -> String {
        guard let colon = key.firstIndex(of: ":") else { return key }
        let rest = key[key.index(after: colon)...]
        return rest.isEmpty ? key : String(rest)
    }

    /// The key's kind, from what comes before its colon ("browser" has none).
    public static func kind(of key: String) -> ComputerKind {
        ComputerKind(rawValue: String(key.prefix { $0 != ":" })) ?? .unknown
    }

}

/// `computer.frame`: a new screenshot of what the chat uses; the PNG is at
/// `GET /api/sessions/{id}/computer/frame`.
public struct ComputerFrame: Decodable, Sendable, Hashable {
    public var target: String
    /// Such as "TextEdit: Release notes.rtf".
    public var label: String
    public var seq: Int

    public init(target: String, label: String, seq: Int) {
        self.target = target
        self.label = label
        self.seq = seq
    }
}

/// The `computer` object of a computer use approval: a chat asks to use a target; Allow
/// covers its chat (D178).
public struct ComputerAsk: Decodable, Sendable, Hashable {
    public var target: String
    public var name: String
}
