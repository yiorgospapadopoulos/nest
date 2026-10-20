import Foundation

/// The pixie's pixel-art mascot, a fairy since B89; `MascotSprites` draws it (D072).
public enum Mascot: String, Codable, Sendable, CaseIterable, UnknownSafeEnum {
    case bluebell, dragonfly, moth, firefly, rose, frost, sprig, nightshade, brook, star
    case unknown

    /// The mascots before B89, read as the fairies that took their place.
    static let renamed: [String: Mascot] = [
        "invader": .frost, "ghost": .brook, "cat": .bluebell, "owl": .moth, "robot": .star,
        "frog": .dragonfly, "mushroom": .rose, "bunny": .nightshade, "crab": .firefly,
        "sprout": .sprig,
    ]

    /// A name this app does not know reads as `unknown`, an old one as its fairy.
    public init(from decoder: any Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = Self(rawValue: raw) ?? Self.renamed[raw] ?? .unknown
    }
}

/// What a pixie may do in Nest with its tools; each level includes the ones before (B41).
public enum Autonomy: String, Codable, Sendable, CaseIterable, UnknownSafeEnum {
    case observe, message, start, answer
    case unknown
}

/// How far a pixie's chat reaches into the user's projects.
public enum ProjectAccess: String, Codable, Sendable, CaseIterable, UnknownSafeEnum {
    case edit, read
    /// Wire value "none"; named apart so `.none` never reads as `Optional.none`.
    case noAccess = "none"
    case unknown
}

/// A long-lived assistant with its own soul, memory and chat (D072).
public struct Pixie: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var slug: String
    public var name: String
    public var mascot: Mascot
    /// `#RRGGBB`.
    public var color: String
    /// The engine it runs on (B91); nil from a daemon before it, which runs every pixie on
    /// Claude. `engine` reads it.
    public var provider: String?
    public var model: String?
    public var effort: Effort?
    public var permissionMode: PermissionMode
    public var autonomy: Autonomy
    public var projectAccess: ProjectAccess
    public var skills: [String]
    public var canCall: [String]
    public var hidden: Bool
    public var position: Int
    public var chatSessionID: String?
    /// The team it is in, if any (B40).
    public var teamID: String?
    /// How many chats it started may run or wait at once (`PixieLimits.running`, B41).
    public var maxRunning: Int
    /// How many chats it may start per local day (`PixieLimits.perDay`).
    public var maxPerDay: Int
    /// Its unread reports that need action, as the daemon counts them.
    public var unreadActionReports: Int
    public var createdAt: Date
    public var updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case id, slug, name, mascot, color, provider, model, effort, autonomy, skills
        case hidden, position
        case permissionMode = "permission_mode"
        case projectAccess = "project_access"
        case canCall = "can_call"
        case chatSessionID = "chat_session_id"
        case teamID = "team_id"
        case maxRunning = "max_running"
        case maxPerDay = "max_per_day"
        case unreadActionReports = "unread_action_reports"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

extension Pixie {
    /// The engine it runs on; Claude unless set otherwise.
    public var engine: String { provider ?? ProviderInfo.claude }
}

/// Pixies called together with one `@handle`: the leader plans who does what (B40).
/// Members are the pixies whose `teamID` is its id, in pixie order.
public struct PixieTeam: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var name: String
    /// Unique across pixie slugs and team handles.
    public var handle: String
    /// One of its members; nil only while it has none.
    public var leaderID: String?
    public var position: Int
    public var createdAt: Date
    public var updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case id, name, handle, position
        case leaderID = "leader_id"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

extension Pixie {
    /// The pixie with the change made, as the daemon makes it; the app shows it while the
    /// change saves. The daemon's answer has the last word, such as Auto dropping to Ask
    /// before edits on a model without it.
    public func applying(_ change: UpdatePixieRequest) -> Pixie {
        var pixie = self
        pixie.name = change.name ?? name
        pixie.slug = change.slug ?? slug
        pixie.mascot = change.mascot ?? mascot
        pixie.color = change.color ?? color
        // Another engine starts from its own default model and thinking (B91).
        let moved = change.provider.map { $0 != engine } ?? false
        pixie.provider = change.provider ?? provider
        pixie.model = change.model ?? (change.clearsModel || moved ? nil : model)
        pixie.effort = change.effort ?? (change.clearsEffort || moved ? nil : effort)
        pixie.permissionMode = change.permissionMode ?? permissionMode
        pixie.autonomy = change.autonomy ?? autonomy
        pixie.projectAccess = change.projectAccess ?? projectAccess
        pixie.skills = change.skills ?? skills
        pixie.hidden = change.hidden ?? hidden
        pixie.teamID = change.teamID ?? (change.leavesTeam ? nil : teamID)
        pixie.maxRunning = change.maxRunning ?? maxRunning
        pixie.maxPerDay = change.maxPerDay ?? maxPerDay
        return pixie
    }
}

/// A skill a pixie may be given, from `GET /api/pixies/skills` (B85): standalone or from a
/// plugin. `name` is what goes into the pixie's `skills`; a plugin's is `plugin:skill`.
public struct PixieSkillChoice: Codable, Sendable, Hashable, Identifiable {
    public var name: String
    public var description: String?
    public var plugin: String?

    public init(name: String, description: String?, plugin: String?) {
        self.name = name
        self.description = description
        self.plugin = plugin
    }

    public var id: String { name }

    /// The name inside its plugin's group: without the `plugin:` prefix.
    public var shortName: String {
        guard let plugin, name.hasPrefix("\(plugin):") else { return name }
        return String(name.dropFirst(plugin.count + 1))
    }
}

/// A pixie file's text and the hash a later write must name.
public struct PixieFile: Codable, Sendable, Hashable {
    public var text: String
    public var hash: String

    public init(text: String, hash: String) {
        self.text = text
        self.hash = hash
    }
}

/// A line of a pixie's memory that matched a search.
public struct PixieSearchHit: Codable, Sendable, Hashable {
    public var file: String
    public var line: String

    public init(file: String, line: String) {
        self.file = file
        self.line = line
    }
}

/// One change a pixie made with its Nest tools, from `GET /api/pixies/{id}/activity`
/// (B41).
public struct PixieActivityEntry: Codable, Sendable, Hashable, Identifiable {
    public var id: Int
    public var ts: Date
    /// The tool's name, such as `start_session`.
    public var tool: String
    /// The chat it acted on, if any.
    public var sessionID: String?
    public var summary: String

    enum CodingKeys: String, CodingKey {
        case id, ts, tool, summary
        case sessionID = "session_id"
    }
}

public enum PixieCardKind: String, UnknownSafeEnum {
    /// A chat the pixie started, with its live state.
    case session
    /// A chat's pull request.
    case pr
    /// A report it made (B42).
    case report
    /// Up to four replies the user can send with one click (B42).
    case choices
    /// A habit it proposes; Start creates and enables it (B42).
    case habitSuggestion = "habit_suggestion"
    case unknown
}

/// A card in a pixie's chat, from a `pixie.card` event (B41, B42): a chat or its pull
/// request by session id, a report by id, reply choices or a suggested habit.
public struct PixieCard: Codable, Sendable, Hashable {
    public var kind: PixieCardKind
    public var sessionID: String?
    public var reportID: String?
    public var options: [String]?
    public var habit: HabitSuggestion?

    public init(
        kind: PixieCardKind, sessionID: String? = nil, reportID: String? = nil,
        options: [String]? = nil, habit: HabitSuggestion? = nil
    ) {
        self.kind = kind
        self.sessionID = sessionID
        self.reportID = reportID
        self.options = options
        self.habit = habit
    }

    enum CodingKeys: String, CodingKey {
        case kind, options, habit
        case sessionID = "session_id"
        case reportID = "report_id"
    }
}
