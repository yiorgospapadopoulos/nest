import Foundation
import Observation

/// Claude Code's models, the defaults for new chats (shared with the iPhone through the
/// daemon) and the Claude account the agents run on.
@MainActor @Observable
public final class AgentsStore {
    /// The value Claude Code's list uses for its default model.
    public static let defaultModel = ModelCatalog.defaultModel

    /// Empty until loaded, or when the daemon has no list.
    public private(set) var models: [ModelInfo] = []
    /// Nil until loaded.
    public private(set) var defaults: AgentDefaults?
    public private(set) var account: ClaudeAccount?

    let api: any NestAPI

    public init(api: any NestAPI) {
        self.api = api
    }

    /// Loads the three independently; one the daemon cannot answer keeps its last value.
    public func load() async {
        if let list = try? await api.models() {
            models = list.models
        }
        if let defaults = try? await api.agentDefaults() {
            self.defaults = defaults
        }
        if let account = try? await api.account() {
            self.account = account
        }
    }

    // MARK: Models

    /// Claude Code's models with what the menus offer from them.
    public var catalog: ModelCatalog { ModelCatalog(models: models) }

    /// The list entry for a session's model; nil stands for Claude Code's default.
    public func info(for model: String?) -> ModelInfo? {
        catalog.info(for: model)
    }

    public func label(for model: String?) -> String {
        catalog.label(for: model)
    }

    public func isSelected(_ info: ModelInfo, current model: String?) -> Bool {
        catalog.isSelected(info, current: model)
    }

    public func thinkingLevels(for model: String?) -> [Effort] {
        catalog.thinkingLevels(for: model)
    }

    public func effort(_ current: Effort?, afterSwitchingTo model: String?) -> Effort? {
        catalog.effort(current, afterSwitchingTo: model)
    }

    public func defaultEffortLabel(for model: String?) -> String {
        catalog.defaultEffortLabel(for: model)
    }

    public func supportsAuto(_ model: String?) -> Bool {
        catalog.supportsAuto(model)
    }

    public func permissionModes(for model: String?) -> [PermissionMode] {
        catalog.permissionModes(for: model)
    }

    public func planChoices(for model: String?) -> [PermissionMode] {
        catalog.planChoices(for: model)
    }

    /// The mode a new chat keeps after switching to this model, falling back to the agent
    /// default's (`ModelCatalog.newChatPermission`).
    public func newChatPermission(_ current: PermissionMode?, afterSwitchingTo model: String?)
        -> PermissionMode?
    {
        catalog.newChatPermission(
            current, afterSwitchingTo: model, fallback: self.current.permissionMode)
    }

    /// The agent default's mode after switching the default model: Auto only where the
    /// model offers it, else Claude Code's own setting.
    public func permission(_ current: PermissionMode?, afterSwitchingTo model: String?)
        -> PermissionMode?
    {
        current == .auto && !supportsAuto(model) ? nil : current
    }

    // MARK: Defaults

    /// The defaults new chats start from, before and after loading.
    public var current: AgentDefaults { defaults ?? .standard }

    /// Switches the default model and keeps the default effort and permission mode only
    /// as far as it allows.
    public func setDefaultModel(_ model: String) async throws {
        try await change {
            $0.model = model
            $0.effort = effort($0.effort, afterSwitchingTo: model)
            $0.permissionMode = permission($0.permissionMode, afterSwitchingTo: model)
        }
    }

    public func setDefaultEffort(_ effort: Effort?) async throws {
        try await change { $0.effort = effort }
    }

    /// Nil leaves the mode to Claude Code's own setting.
    public func setDefaultPermissionMode(_ mode: PermissionMode?) async throws {
        try await change { $0.permissionMode = mode }
    }

    public func setDefaultMode(_ mode: SessionMode) async throws {
        try await change { $0.mode = mode }
    }

    /// Shows the change at once and restores the old defaults if the daemon refuses.
    private func change(_ edit: (inout AgentDefaults) -> Void) async throws {
        let previous = defaults
        var changed = current
        edit(&changed)
        defaults = changed
        do {
            defaults = try await api.updateAgentDefaults(changed)
        } catch {
            defaults = previous
            throw error
        }
    }

    // MARK: Account

    /// The account's name, else the given one (the Mac user's full name).
    public func accountName(fallback: String) -> String {
        account?.displayName.flatMap { $0.isEmpty ? nil : $0 } ?? fallback
    }

    /// The subscription, such as "Claude Max"; "Claude" while unknown.
    public var plan: String {
        account?.plan.flatMap { $0.isEmpty ? nil : $0 } ?? "Claude"
    }

    public var email: String? {
        account?.email.flatMap { $0.isEmpty ? nil : $0 }
    }
}
