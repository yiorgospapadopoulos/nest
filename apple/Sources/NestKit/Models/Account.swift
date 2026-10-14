import Foundation

public enum ConnectorGroup: String, UnknownSafeEnum {
    case claudeAI = "claude.ai"
    case plugin
    case local
    case unknown
}

public enum ManageHint: String, UnknownSafeEnum {
    case claudeAI = "claude.ai"
    case claudeCode = "claude_code"
    case unknown
}

/// An MCP server or claude.ai connector with the status Claude Code last reported.
public struct Connector: Codable, Sendable, Hashable, Identifiable {
    public var name: String
    public var displayName: String
    public var group: ConnectorGroup
    /// connected, needs-auth, failed, pending, or whatever else Claude Code reports.
    public var status: String
    public var error: String?
    public var manageHint: ManageHint
    /// The session whose agent last reported it.
    public var source: String
    public var lastSeenAt: Date

    public var id: String { name }

    enum CodingKeys: String, CodingKey {
        case name, group, status, error, source
        case displayName = "display_name"
        case manageHint = "manage_hint"
        case lastSeenAt = "last_seen_at"
    }
}

public struct TokenTotals: Decodable, Sendable, Hashable {
    public var inputTokens: Int
    public var outputTokens: Int
    public var cacheCreationInputTokens: Int
    public var cacheReadInputTokens: Int
    /// All four components together.
    public var total: Int

    enum CodingKeys: String, CodingKey {
        case total
        case inputTokens = "input_tokens"
        case outputTokens = "output_tokens"
        case cacheCreationInputTokens = "cache_creation_input_tokens"
        case cacheReadInputTokens = "cache_read_input_tokens"
    }
}

public struct DayUsage: Decodable, Sendable, Hashable {
    public var date: CalendarDay
    public var tokens: Int
    public var sessions: Int
}

/// Token totals of a month and of each of its days, by the daemon's local calendar.
public struct UsageMonth: Decodable, Sendable, Hashable {
    public var year: Int
    public var month: Int
    /// Distinct sessions with a turn this month.
    public var sessions: Int
    public var tokens: TokenTotals
    /// Every day of the month, in order.
    public var days: [DayUsage]
    /// Nest's own usage checks, not part of the totals above; absent from older daemons.
    public var probes: ProbeTotals?
}

/// The month's usage checks: Nest overhead, kept apart from the user's sessions.
public struct ProbeTotals: Decodable, Sendable, Hashable {
    public var count: Int
    public var tokens: Int
}

/// `GET/PUT /api/usage/settings`: how often the daemon asks Claude for the limits while a
/// client is on screen; 0 turns it off.
public struct UsageSettings: Codable, Sendable, Hashable {
    public var refreshMinutes: Int

    public init(refreshMinutes: Int) {
        self.refreshMinutes = refreshMinutes
    }

    enum CodingKeys: String, CodingKey {
        case refreshMinutes = "refresh_minutes"
    }
}

/// A subscription limit window; `utilization` is a fraction from 0 to 1.
public struct LimitWindow: Codable, Sendable, Hashable {
    public var utilization: Double
    public var resetsAt: Date?
    /// When the engine last reported it; absent in `usage.updated` events.
    public var updatedAt: Date?

    enum CodingKeys: String, CodingKey {
        case utilization
        case resetsAt = "resets_at"
        case updatedAt = "updated_at"
    }
}

public struct UsageLimits: Codable, Sendable, Hashable {
    public var fiveHour: LimitWindow?
    public var sevenDay: LimitWindow?

    enum CodingKeys: String, CodingKey {
        case fiveHour = "five_hour"
        case sevenDay = "seven_day"
    }
}

public struct Device: Decodable, Sendable, Hashable, Identifiable {
    public var id: String
    public var name: String
    public var isLocal: Bool
    public var createdAt: Date
    public var lastSeenAt: Date?
    public var revokedAt: Date?

    enum CodingKeys: String, CodingKey {
        case id, name
        case isLocal = "is_local"
        case createdAt = "created_at"
        case lastSeenAt = "last_seen_at"
        case revokedAt = "revoked_at"
    }
}

/// A one-time code a new device redeems to pair.
public struct PairingCode: Decodable, Sendable, Hashable {
    public var code: String
    public var expiresAt: Date

    enum CodingKeys: String, CodingKey {
        case code
        case expiresAt = "expires_at"
    }
}

public struct Attachment: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var filename: String
    public var mediaType: String
    public var size: Int
    /// Present in upload responses; absent in message summaries.
    public var createdAt: Date?

    enum CodingKeys: String, CodingKey {
        case id, filename, size
        case mediaType = "media_type"
        case createdAt = "created_at"
    }
}

/// The result of continuing a session in Claude Code.
public struct ClaudeCodeLaunch: Decodable, Sendable, Hashable {
    public var launcher: String
    /// Set while Nest still runs the session too.
    public var warning: String?
}
