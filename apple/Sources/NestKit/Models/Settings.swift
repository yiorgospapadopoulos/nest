import Foundation

/// `GET /api/storage`: what Nest keeps in its data folder, in bytes (B81).
public struct StorageUsage: Codable, Sendable, Hashable {
    public var totalBytes: Int
    /// The database with its write-ahead files.
    public var chatsBytes: Int
    public var attachmentsBytes: Int
    public var artifactsBytes: Int
    public var otherBytes: Int

    public init(
        totalBytes: Int, chatsBytes: Int, attachmentsBytes: Int, artifactsBytes: Int,
        otherBytes: Int
    ) {
        self.totalBytes = totalBytes
        self.chatsBytes = chatsBytes
        self.attachmentsBytes = attachmentsBytes
        self.artifactsBytes = artifactsBytes
        self.otherBytes = otherBytes
    }

    enum CodingKeys: String, CodingKey {
        case totalBytes = "total_bytes"
        case chatsBytes = "chats_bytes"
        case attachmentsBytes = "attachments_bytes"
        case artifactsBytes = "artifacts_bytes"
        case otherBytes = "other_bytes"
    }
}

/// The `[storage]` section: chats idle this many days are archived; nil never.
public struct StorageSettings: Codable, Sendable, Hashable {
    public var archiveAfterDays: Int?

    public init(archiveAfterDays: Int? = nil) {
        self.archiveAfterDays = archiveAfterDays
    }

    enum CodingKeys: String, CodingKey {
        case archiveAfterDays = "archive_after_days"
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        archiveAfterDays = try container.decodeIfPresent(Int.self, forKey: .archiveAfterDays)
    }

    /// Never is sent as null.
    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(archiveAfterDays, forKey: .archiveAfterDays)
    }
}

/// One of the largest attachments, for Review large attachments.
public struct LargeAttachment: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var name: String
    public var bytes: Int
    public var mediaType: String
    public var sessionID: String?
    public var sessionTitle: String?
    public var createdAt: Date

    public init(
        id: String, name: String, bytes: Int, mediaType: String, sessionID: String?,
        sessionTitle: String?, createdAt: Date
    ) {
        self.id = id
        self.name = name
        self.bytes = bytes
        self.mediaType = mediaType
        self.sessionID = sessionID
        self.sessionTitle = sessionTitle
        self.createdAt = createdAt
    }

    enum CodingKeys: String, CodingKey {
        case id, name, bytes
        case mediaType = "media_type"
        case sessionID = "session_id"
        case sessionTitle = "session_title"
        case createdAt = "created_at"
    }
}

/// `GET/PUT /api/pixie-settings`: what new pixies start with, and the habits' switches.
public struct PixieSettings: Codable, Sendable, Hashable {
    /// The Claude model new Claude pixies start on; nil only before the daemon resolved
    /// it (B94).
    public var model: String?
    public var autonomy: Autonomy
    public var projectAccess: ProjectAccess
    public var maxRunning: Int
    public var maxPerDay: Int
    public var habitsPaused: Bool
    /// Habit runs are skipped while the 5 hour limit is above this percent.
    public var habitUsagePercent: Int

    public init(
        model: String? = nil, autonomy: Autonomy = .observe, projectAccess: ProjectAccess = .edit,
        maxRunning: Int = 2, maxPerDay: Int = 5, habitsPaused: Bool = false,
        habitUsagePercent: Int = 80
    ) {
        self.model = model
        self.autonomy = autonomy
        self.projectAccess = projectAccess
        self.maxRunning = maxRunning
        self.maxPerDay = maxPerDay
        self.habitsPaused = habitsPaused
        self.habitUsagePercent = habitUsagePercent
    }

    enum CodingKeys: String, CodingKey {
        case model, autonomy
        case projectAccess = "project_access"
        case maxRunning = "max_running"
        case maxPerDay = "max_per_day"
        case habitsPaused = "habits_paused"
        case habitUsagePercent = "habit_usage_percent"
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        model = try container.decodeIfPresent(String.self, forKey: .model)
        autonomy = try container.decode(Autonomy.self, forKey: .autonomy)
        projectAccess = try container.decode(ProjectAccess.self, forKey: .projectAccess)
        maxRunning = try container.decode(Int.self, forKey: .maxRunning)
        maxPerDay = try container.decode(Int.self, forKey: .maxPerDay)
        habitsPaused = try container.decode(Bool.self, forKey: .habitsPaused)
        habitUsagePercent = try container.decode(Int.self, forKey: .habitUsagePercent)
    }

    /// The whole section.
    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(model, forKey: .model)
        try container.encode(autonomy, forKey: .autonomy)
        try container.encode(projectAccess, forKey: .projectAccess)
        try container.encode(maxRunning, forKey: .maxRunning)
        try container.encode(maxPerDay, forKey: .maxPerDay)
        try container.encode(habitsPaused, forKey: .habitsPaused)
        try container.encode(habitUsagePercent, forKey: .habitUsagePercent)
    }

}

/// `GET/PUT /api/notifications/settings`: the daemon's rules for what reaches the phone.
/// The Mac changes only the pixie report level (B85); the rest of the section is sent back
/// as it was read, since a save replaces the whole section.
public struct NotificationRules: Codable, Sendable, Hashable {
    /// The section as the daemon sent it.
    public var fields: [String: JSONValue]

    public init(fields: [String: JSONValue] = [:]) {
        self.fields = fields
    }

    public init(from decoder: any Decoder) throws {
        fields = try decoder.singleValueContainer().decode([String: JSONValue].self)
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(fields)
    }

    /// The least severe pixie report that reaches the phone, for every pixie; a daemon
    /// that names none uses Needs action.
    public var pixieReportLevel: ReportSeverity {
        get {
            fields[Self.levelKey]?.stringValue.map { ReportSeverity(rawValue: $0) ?? .unknown }
                ?? .action
        }
        set { fields[Self.levelKey] = .string(newValue.rawValue) }
    }

    private static let levelKey = "pixie_report_level"
}

public enum GitHubLoginState: String, UnknownSafeEnum {
    case signedIn = "signed_in"
    case signedOut = "signed_out"
    /// `gh` is not installed.
    case unavailable
    case unknown
}

/// `GET /api/accounts/github`: the user's `gh` login; never a token.
public struct GitHubAccount: Codable, Sendable, Hashable {
    public var state: GitHubLoginState
    public var login: String?
    public var checkedAt: Date

    public init(state: GitHubLoginState, login: String?, checkedAt: Date) {
        self.state = state
        self.login = login
        self.checkedAt = checkedAt
    }

    enum CodingKeys: String, CodingKey {
        case state, login
        case checkedAt = "checked_at"
    }
}

/// `GET /api/accounts/claude`: the Claude Code login as `claude auth status` reports it;
/// an `account.claude` event carries the same, with `error` when signing in failed.
public struct ClaudeLogin: Codable, Sendable, Hashable {
    public var signedIn: Bool
    public var email: String?
    public var organization: String?
    public var plan: String?
    public var method: String?
    public var checkedAt: Date
    public var error: String?

    public init(
        signedIn: Bool, email: String? = nil, organization: String? = nil, plan: String? = nil,
        method: String? = nil, checkedAt: Date, error: String? = nil
    ) {
        self.signedIn = signedIn
        self.email = email
        self.organization = organization
        self.plan = plan
        self.method = method
        self.checkedAt = checkedAt
        self.error = error
    }

    enum CodingKeys: String, CodingKey {
        case email, organization, plan, method, error
        case signedIn = "signed_in"
        case checkedAt = "checked_at"
    }
}

/// `GET /api/accounts/codex`: the Codex login as Codex's app-server reports it (B94); an
/// `account.codex` event carries the same, with `error` when signing in failed.
public struct CodexLogin: Codable, Sendable, Hashable {
    /// Nil while Codex could not be asked.
    public var signedIn: Bool?
    public var email: String?
    /// Such as "ChatGPT Plus".
    public var plan: String?
    public var checkedAt: Date
    public var error: String?

    public init(
        signedIn: Bool?, email: String? = nil, plan: String? = nil, checkedAt: Date,
        error: String? = nil
    ) {
        self.signedIn = signedIn
        self.email = email
        self.plan = plan
        self.checkedAt = checkedAt
        self.error = error
    }

    enum CodingKeys: String, CodingKey {
        case email, plan, error
        case signedIn = "signed_in"
        case checkedAt = "checked_at"
    }
}

/// `POST /api/accounts/codex/login`: the page to sign in on, opened in the browser.
public struct CodexSignIn: Codable, Sendable, Hashable {
    public var authURL: URL

    public init(authURL: URL) {
        self.authURL = authURL
    }

    enum CodingKeys: String, CodingKey {
        case authURL = "auth_url"
    }
}

/// `GET /api/push/status`: how many devices get push notifications.
public struct PushStatus: Codable, Sendable, Hashable {
    public var devices: Int

    public init(devices: Int) {
        self.devices = devices
    }
}

/// `usage.warning`: a limit window reached the warning level in this period.
public struct UsageWarning: Codable, Sendable, Hashable {
    public var window: LimitPauseWindow
    /// A fraction from 0 to 1.
    public var utilization: Double
    public var resetsAt: Date?

    public init(window: LimitPauseWindow, utilization: Double, resetsAt: Date?) {
        self.window = window
        self.utilization = utilization
        self.resetsAt = resetsAt
    }

    enum CodingKeys: String, CodingKey {
        case window, utilization
        case resetsAt = "resets_at"
    }
}

/// `GET /api/repos/{name}/branches`.
struct BranchList: Decodable {
    var branches: [String]
}

/// `GET /api/claude-code`: the standalone Claude Code found on this Mac, if any, and the
/// version Nest's agents run (the SDK's own).
public struct ClaudeCodeStatus: Codable, Sendable, Hashable {
    public var installed: Bool
    public var path: String?
    public var version: String?
    public var bundledVersion: String

    public init(installed: Bool, path: String?, version: String?, bundledVersion: String) {
        self.installed = installed
        self.path = path
        self.version = version
        self.bundledVersion = bundledVersion
    }

    enum CodingKeys: String, CodingKey {
        case installed, path, version
        case bundledVersion = "bundled_version"
    }
}

public enum InstallState: String, UnknownSafeEnum {
    case running, done, failed
    case unknown
}

/// `claude_code.install`: how installing Claude Code goes.
public struct ClaudeCodeInstallProgress: Codable, Sendable, Hashable {
    public var state: InstallState
    public var message: String?

    public init(state: InstallState, message: String?) {
        self.state = state
        self.message = message
    }
}
