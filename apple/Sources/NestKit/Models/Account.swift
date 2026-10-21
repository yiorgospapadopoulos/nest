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

/// A span of the usage chart, as `GET /api/usage/period` takes it.
public enum UsageUnit: String, Codable, Sendable, CaseIterable {
    case day, week, month, year

    /// "Day", as the period switch shows it.
    public var title: String { rawValue.capitalized }
}

/// One bar of a period: an hour of a day, a day of a week or month, or a month of a year.
public struct PeriodBar: Decodable, Sendable, Hashable {
    /// The bar's local start, sent with its UTC offset.
    public var start: Date
    public var tokens: Int
    /// Distinct chats in it.
    public var sessions: Int
}

/// A repo's tokens in a period; every pixie chat counts as one "Pixies" entry.
public struct ProjectTokens: Decodable, Sendable, Hashable {
    public var name: String
    public var tokens: Int
    public var pixies: Bool
}

/// One engine's part of a period's tokens (B91).
public struct EngineTokens: Decodable, Sendable, Hashable {
    /// The engine's name, as `GET /api/providers` gives it.
    public var provider: String
    public var tokens: Int
    /// Distinct chats on it.
    public var sessions: Int

    public init(provider: String, tokens: Int, sessions: Int) {
        self.provider = provider
        self.tokens = tokens
        self.sessions = sessions
    }
}

/// `GET /api/usage/period`: the tokens of a day, week (from Monday), month or year, by the
/// daemon's local calendar. Every engine counts in the totals.
public struct UsagePeriod: Decodable, Sendable, Hashable {
    public var unit: UsageUnit
    public var start: CalendarDay
    public var end: CalendarDay
    /// The period contains today.
    public var current: Bool
    /// Distinct chats with tokens in the period.
    public var sessions: Int
    /// Everything, chats and their subagents.
    public var tokens: TokenTotals
    /// The subagents' part of `tokens`.
    public var subagents: TokenTotals
    public var bars: [PeriodBar]
    /// By tokens, most first; repos without tokens are left out.
    public var projects: [ProjectTokens]
    /// Nest's own usage checks, not part of the totals above.
    public var probes: ProbeTotals
    /// The totals by engine, Claude first; engines without tokens are left out, and a
    /// daemon before B91 sends none.
    public var engines: [EngineTokens]

    enum CodingKeys: String, CodingKey {
        case unit, start, end, current, sessions, tokens, subagents, bars, projects, probes
        case engines
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        unit = try container.decode(UsageUnit.self, forKey: .unit)
        start = try container.decode(CalendarDay.self, forKey: .start)
        end = try container.decode(CalendarDay.self, forKey: .end)
        current = try container.decode(Bool.self, forKey: .current)
        sessions = try container.decode(Int.self, forKey: .sessions)
        tokens = try container.decode(TokenTotals.self, forKey: .tokens)
        subagents = try container.decode(TokenTotals.self, forKey: .subagents)
        bars = try container.decode([PeriodBar].self, forKey: .bars)
        projects = try container.decode([ProjectTokens].self, forKey: .projects)
        probes = try container.decode(ProbeTotals.self, forKey: .probes)
        engines = try container.decodeIfPresent([EngineTokens].self, forKey: .engines) ?? []
    }
}

/// The period's usage checks: Nest overhead, kept apart from the user's sessions.
public struct ProbeTotals: Decodable, Sendable, Hashable {
    public var count: Int
    public var tokens: Int
}

/// `GET/PUT /api/usage/settings`: how often the daemon asks Claude for the limits while a
/// client is on screen; 0 turns it off.
public struct UsageSettings: Codable, Sendable, Hashable {
    public var refreshMinutes: Int
    /// Warns once per window period when a limit reaches this percent; nil is off (B81).
    public var warnPercent: Int?
    /// The warning also reaches the phone, and this Mac as a notification.
    public var warnNotify: Bool

    public init(refreshMinutes: Int, warnPercent: Int? = 80, warnNotify: Bool = true) {
        self.refreshMinutes = refreshMinutes
        self.warnPercent = warnPercent
        self.warnNotify = warnNotify
    }

    enum CodingKeys: String, CodingKey {
        case refreshMinutes = "refresh_minutes"
        case warnPercent = "warn_percent"
        case warnNotify = "warn_notify"
    }

    /// The warning keys are optional, since older daemons do not send them.
    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        refreshMinutes = try container.decode(Int.self, forKey: .refreshMinutes)
        warnNotify = try container.decodeIfPresent(Bool.self, forKey: .warnNotify) ?? true
        warnPercent =
            container.contains(.warnPercent)
            ? try container.decodeIfPresent(Int.self, forKey: .warnPercent) : 80
    }

    /// The whole section, with an off warning as null.
    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(refreshMinutes, forKey: .refreshMinutes)
        try container.encode(warnPercent, forKey: .warnPercent)
        try container.encode(warnNotify, forKey: .warnNotify)
    }
}

/// A subscription limit window; `utilization` is a fraction from 0 to 1.
public struct LimitWindow: Codable, Sendable, Hashable {
    public var utilization: Double
    public var resetsAt: Date?
    /// When the engine last reported it; absent in `usage.updated` events.
    public var updatedAt: Date?
    /// Another engine's window (B91): its length, nil when the engine left it out.
    public var minutes: Int?
    /// Another engine's window (B91): its name from its length, "30 day".
    public var label: String?
    /// An account's window past its reset time (B98); never sent by the daemon here.
    public var reset = false

    public init(
        utilization: Double, resetsAt: Date? = nil, updatedAt: Date? = nil, minutes: Int? = nil,
        label: String? = nil, reset: Bool = false
    ) {
        self.utilization = utilization
        self.resetsAt = resetsAt
        self.updatedAt = updatedAt
        self.minutes = minutes
        self.label = label
        self.reset = reset
    }

    enum CodingKeys: String, CodingKey {
        case utilization
        case resetsAt = "resets_at"
        case updatedAt = "updated_at"
        case minutes
        case label
    }
}

/// An engine's usage windows: Claude's five-hour and weekly ones, or another engine's
/// (B91: Codex's) whichever its plan has, by length in `windows`.
public struct UsageLimits: Codable, Sendable, Hashable {
    public var fiveHour: LimitWindow?
    public var sevenDay: LimitWindow?
    /// Another engine's windows, shortest first; nil for Claude's.
    public var windows: [LimitWindow]?

    public init(
        fiveHour: LimitWindow? = nil, sevenDay: LimitWindow? = nil, windows: [LimitWindow]? = nil
    ) {
        self.fiveHour = fiveHour
        self.sevenDay = sevenDay
        self.windows = windows
    }

    enum CodingKeys: String, CodingKey {
        case fiveHour = "five_hour"
        case sevenDay = "seven_day"
        case windows
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
