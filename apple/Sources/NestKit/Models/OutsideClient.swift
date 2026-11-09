import Foundation

/// An app or command outside Nest that may work with its chats (B151).
public enum OutsideClientKind: String, UnknownSafeEnum {
    case claudeCode = "claude_code"
    case codex, other, shell
    case unknown
}

/// How far a client may go; each level includes the ones before it.
public enum OutsideAccess: String, UnknownSafeEnum, CaseIterable {
    case read, message, full
    case unknown

    public static var choices: [OutsideAccess] { [.read, .message, .full] }

    public var title: String {
        switch self {
        case .read: "Read only"
        case .message: "Read and message"
        case .full: "Full"
        case .unknown: "Unknown"
        }
    }
}

/// `GET /api/outside-clients`: one client as Settings > Terminal agents shows it.
public struct OutsideClient: Decodable, Sendable, Hashable, Identifiable {
    public var kind: OutsideClientKind
    public var label: String
    public var on: Bool
    public var access: OutsideAccess?
    public var turnedOnAt: Date?
    public var lastSeenAt: Date?
    /// What an app runs to reach Nest, or the `nest` command itself; nil when not installed.
    public var command: [String]?

    public var id: String { kind.rawValue }

    public init(
        kind: OutsideClientKind, label: String, on: Bool = false, access: OutsideAccess? = nil,
        command: [String]? = nil
    ) {
        self.kind = kind
        self.label = label
        self.on = on
        self.access = access
        self.command = command
    }

    /// The line to give an app Nest does not set up, or the command's own path; nil for
    /// Claude Code and Codex, whose config Nest writes.
    public var commandLine: String? {
        guard let command, kind == .other || kind == .shell else { return nil }
        return command.map { $0.contains(" ") ? "\"\($0)\"" : $0 }.joined(separator: " ")
    }

    enum CodingKeys: String, CodingKey {
        case kind, label, on, access, command
        case turnedOnAt = "turned_on_at"
        case lastSeenAt = "last_seen_at"
    }
}

/// `PUT /api/outside-clients/{kind}`.
struct OutsideTurnOn: Encodable {
    var access: OutsideAccess
}
