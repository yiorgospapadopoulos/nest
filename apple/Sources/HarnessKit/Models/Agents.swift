import Foundation

/// One entry of Claude Code's own /model list, as `GET /api/models` reports it.
public struct ModelInfo: Decodable, Sendable, Hashable, Identifiable {
    /// What a session's `model` holds, such as `default`, `opus` or `claude-fable-5-1`.
    public var value: String
    public var displayName: String
    public var description: String
    /// Levels this daemon does not know are left out.
    public var effortLevels: [Effort]
    public var supportsEffort: Bool

    public var id: String { value }

    /// The thinking levels the menu offers, lowest first; empty when the model has none.
    public var thinkingLevels: [Effort] {
        supportsEffort ? Effort.selectable.filter(effortLevels.contains) : []
    }

    public init(
        value: String, displayName: String, description: String, effortLevels: [Effort],
        supportsEffort: Bool
    ) {
        self.value = value
        self.displayName = displayName
        self.description = description
        self.effortLevels = effortLevels
        self.supportsEffort = supportsEffort
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        value = try container.decode(String.self, forKey: .value)
        displayName = try container.decode(String.self, forKey: .displayName)
        description = try container.decode(String.self, forKey: .description)
        effortLevels = try container.decode([Effort].self, forKey: .effortLevels)
            .filter { $0 != .unknown }
        supportsEffort = try container.decode(Bool.self, forKey: .supportsEffort)
    }

    enum CodingKeys: String, CodingKey {
        case value, description
        case displayName = "display_name"
        case effortLevels = "effort_levels"
        case supportsEffort = "supports_effort"
    }
}

/// `GET /api/models`.
public struct ModelList: Decodable, Sendable, Hashable {
    public var models: [ModelInfo]
    public var updatedAt: Date?

    enum CodingKeys: String, CodingKey {
        case models
        case updatedAt = "updated_at"
    }
}

/// `GET /api/account`: the Claude login Claude Code uses; any field may be unknown.
public struct ClaudeAccount: Decodable, Sendable, Hashable {
    public var displayName: String?
    public var email: String?
    public var plan: String?
    public var organization: String?

    public init(
        displayName: String? = nil, email: String? = nil, plan: String? = nil,
        organization: String? = nil
    ) {
        self.displayName = displayName
        self.email = email
        self.plan = plan
        self.organization = organization
    }

    enum CodingKeys: String, CodingKey {
        case email, plan, organization
        case displayName = "display_name"
    }
}

/// `GET/PUT /api/agents/defaults`: what new chats start with, shared by every client.
public struct AgentDefaults: Codable, Sendable, Hashable {
    /// Nil leaves the choice to Claude Code.
    public var model: String?
    public var effort: Effort?
    public var permissionMode: PermissionMode
    public var mode: SessionMode

    /// What applies before the daemon has answered.
    public static let standard = AgentDefaults(
        model: nil, effort: nil, permissionMode: .default, mode: .inPlace)

    public init(model: String?, effort: Effort?, permissionMode: PermissionMode, mode: SessionMode)
    {
        self.model = model
        self.effort = effort
        self.permissionMode = permissionMode
        self.mode = mode
    }

    /// Values a newer daemon may add read as the standard ones, so they are never sent back.
    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        model = try container.decodeIfPresent(String.self, forKey: .model)
        effort = try container.decodeIfPresent(Effort.self, forKey: .effort)
            .flatMap { $0 == .unknown ? nil : $0 }
        let permission = try container.decode(PermissionMode.self, forKey: .permissionMode)
        permissionMode = permission == .unknown ? .default : permission
        let mode = try container.decode(SessionMode.self, forKey: .mode)
        self.mode = mode == .unknown ? .inPlace : mode
    }

    /// Sends nulls too: the daemon replaces the whole set.
    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(model, forKey: .model)
        try container.encode(effort, forKey: .effort)
        try container.encode(permissionMode, forKey: .permissionMode)
        try container.encode(mode, forKey: .mode)
    }

    enum CodingKeys: String, CodingKey {
        case model, effort, mode
        case permissionMode = "permission_mode"
    }
}

extension Effort {
    /// The effort to keep after switching to a model with these levels: the current one
    /// when supported, else the highest supported level below it, else none.
    public static func fallback(_ current: Effort?, supported: [Effort]) -> Effort? {
        guard let current, let rank = selectable.firstIndex(of: current) else { return nil }
        return selectable[...rank].last(where: supported.contains)
    }
}
