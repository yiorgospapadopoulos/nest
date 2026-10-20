import Foundation

/// One entry of an engine's model list, as `GET /api/models` reports it: real models only
/// since B94, no entry that defers to the engine.
public struct ModelInfo: Decodable, Sendable, Hashable, Identifiable {
    /// What a session's `model` holds, such as `opus`, `claude-fable-5-1` or `gpt-5.5`.
    public var value: String
    public var displayName: String
    public var description: String
    /// Levels this daemon does not know are left out.
    public var effortLevels: [Effort]
    public var supportsEffort: Bool
    /// The model offers Claude Code's Auto permission mode.
    public var supportsAutoMode: Bool

    public var id: String { value }

    /// The thinking levels the menu offers, lowest first; empty when the model has none.
    public var thinkingLevels: [Effort] {
        supportsEffort ? Effort.selectable.filter(effortLevels.contains) : []
    }

    public init(
        value: String, displayName: String, description: String, effortLevels: [Effort],
        supportsEffort: Bool, supportsAutoMode: Bool = false
    ) {
        self.value = value
        self.displayName = displayName
        self.description = description
        self.effortLevels = effortLevels
        self.supportsEffort = supportsEffort
        self.supportsAutoMode = supportsAutoMode
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        value = try container.decode(String.self, forKey: .value)
        displayName = try container.decode(String.self, forKey: .displayName)
        description = try container.decode(String.self, forKey: .description)
        effortLevels = try container.decode([Effort].self, forKey: .effortLevels)
            .filter { $0 != .unknown }
        supportsEffort = try container.decode(Bool.self, forKey: .supportsEffort)
        // Older daemons do not send it.
        supportsAutoMode =
            try container.decodeIfPresent(Bool.self, forKey: .supportsAutoMode) ?? false
    }

    enum CodingKeys: String, CodingKey {
        case value, description
        case displayName = "display_name"
        case effortLevels = "effort_levels"
        case supportsEffort = "supports_effort"
        case supportsAutoMode = "supports_auto_mode"
    }
}

/// `GET /api/models`.
public struct ModelList: Decodable, Sendable, Hashable {
    public var models: [ModelInfo]
    public var updatedAt: Date?
    /// The model the engine runs when none is named, a value of `models` where one is it
    /// (B94); nil while the engine has not said, and from older daemons.
    public var defaultModel: String?

    public init(models: [ModelInfo], updatedAt: Date? = nil, defaultModel: String? = nil) {
        self.models = models
        self.updatedAt = updatedAt
        self.defaultModel = defaultModel
    }

    enum CodingKeys: String, CodingKey {
        case models
        case updatedAt = "updated_at"
        case defaultModel = "default_model"
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
/// Concrete since B94: the daemon never leaves a choice to the engine.
public struct AgentDefaults: Codable, Sendable, Hashable {
    /// The engine new chats run on; choosing the default model chooses it.
    public var provider: String
    /// Nil only while no engine has reported its models.
    public var model: String?
    /// Nil only for a model without thinking levels.
    public var effort: Effort?
    public var permissionMode: PermissionMode
    public var mode: SessionMode

    /// What applies before the daemon has answered: Claude, Medium and Ask.
    public static let standard = AgentDefaults(
        model: nil, effort: .medium, permissionMode: .default, mode: .inPlace)

    public init(
        provider: String = ProviderInfo.claude, model: String?, effort: Effort?,
        permissionMode: PermissionMode, mode: SessionMode
    ) {
        self.provider = provider
        self.model = model
        self.effort = effort
        self.permissionMode = permissionMode
        self.mode = mode
    }

    /// Values a newer daemon may add read as the standard ones, so they are never sent
    /// back; a daemon before B94 names no engine (Claude) and may name no mode (Ask).
    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        provider =
            try container.decodeIfPresent(String.self, forKey: .provider) ?? ProviderInfo.claude
        model = try container.decodeIfPresent(String.self, forKey: .model)
        effort = try container.decodeIfPresent(Effort.self, forKey: .effort)
            .flatMap { $0 == .unknown ? nil : $0 }
        let permission =
            try container.decodeIfPresent(PermissionMode.self, forKey: .permissionMode)
            ?? .default
        permissionMode = permission == .unknown ? .default : permission
        let mode = try container.decode(SessionMode.self, forKey: .mode)
        self.mode = mode == .unknown ? .inPlace : mode
    }

    /// The whole set: the daemon replaces it.
    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(provider, forKey: .provider)
        try container.encode(model, forKey: .model)
        try container.encode(effort, forKey: .effort)
        try container.encode(permissionMode, forKey: .permissionMode)
        try container.encode(mode, forKey: .mode)
    }

    enum CodingKeys: String, CodingKey {
        case provider, model, effort, mode
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

    /// The thinking a chat gets when none is chosen (B94): Medium, or the supported level
    /// nearest to it (the lower of two as near); nil for a model without levels.
    public static func standard(supported: [Effort]) -> Effort? {
        let middle = selectable.firstIndex(of: .medium)!
        return selectable.enumerated()
            .filter { supported.contains($0.element) }
            .min { abs($0.offset - middle) < abs($1.offset - middle) }?
            .element
    }
}
