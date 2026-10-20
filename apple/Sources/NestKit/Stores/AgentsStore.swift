import Foundation
import Observation

/// Claude Code's models, the defaults for new chats (shared with the iPhone through the
/// daemon, concrete since B94) and the Claude account the agents run on.
@MainActor @Observable
public final class AgentsStore {
    /// Empty until loaded, or when the daemon has no list.
    public private(set) var models: [ModelInfo] = []
    /// The model Claude Code runs when none is named; nil until it reported one.
    public private(set) var defaultModel: String?
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
            defaultModel = list.defaultModel
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
    public var catalog: ModelCatalog { ModelCatalog(models: models, defaultModel: defaultModel) }

    /// The list entry for a session's model; nil (before B94) is Claude Code's default.
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
        -> PermissionMode
    {
        catalog.newChatPermission(
            current, afterSwitchingTo: model, fallback: self.current.permissionMode)
    }

    // MARK: Defaults

    /// The defaults new chats start from, before and after loading.
    public var current: AgentDefaults { defaults ?? .standard }

    /// Switches the default model of `provider`'s list (`catalog`), which also makes that
    /// engine the one new chats run on (B94), and keeps the default effort and permission
    /// mode as far as the model allows: thinking falls to the nearest level it takes, or
    /// Medium; Auto on a model without it to Ask.
    public func setDefaultModel(
        _ model: String, provider: String = ProviderInfo.claude, catalog: ModelCatalog? = nil
    ) async throws {
        let catalog = catalog ?? self.catalog
        try await change {
            $0.provider = provider
            $0.model = model
            $0.effort = catalog.effort($0.effort, afterSwitchingTo: model)
            if $0.permissionMode == .auto && !catalog.supportsAuto(model) {
                $0.permissionMode = .default
            }
        }
    }

    public func setDefaultEffort(_ effort: Effort) async throws {
        try await change { $0.effort = effort }
    }

    public func setDefaultPermissionMode(_ mode: PermissionMode) async throws {
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
