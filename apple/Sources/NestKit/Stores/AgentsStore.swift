import Foundation
import Observation

/// Claude Code's models, the defaults for new chats (shared with the iPhone through the
/// daemon) and the Claude account the agents run on.
@MainActor @Observable
public final class AgentsStore {
    /// The value Claude Code's list uses for its default model.
    public static let defaultModel = "default"

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

    /// The list entry for a session's model; nil stands for Claude Code's default.
    public func info(for model: String?) -> ModelInfo? {
        let value = model ?? Self.defaultModel
        return models.first { $0.value == value }
    }

    /// The menu title: the model's display name, or its raw value when the list does not
    /// have it (an older session, or a list not loaded yet).
    public func label(for model: String?) -> String {
        info(for: model)?.displayName ?? model ?? "Default"
    }

    public func isSelected(_ info: ModelInfo, current model: String?) -> Bool {
        info.value == (model ?? Self.defaultModel)
    }

    /// The thinking levels to offer: the model's own, or every level for a model the
    /// list does not describe.
    public func thinkingLevels(for model: String?) -> [Effort] {
        info(for: model)?.thinkingLevels ?? Effort.selectable
    }

    /// The effort a chat keeps after switching to this model.
    public func effort(_ current: Effort?, afterSwitchingTo model: String?) -> Effort? {
        Effort.fallback(current, supported: thinkingLevels(for: model))
    }

    /// Thinking left to the model: what Claude Code's settings give it, when they say,
    /// such as "Model default (High, from Claude Code)".
    public func defaultEffortLabel(for model: String?) -> String {
        guard let effort = info(for: model)?.claudeCodeEffort else { return "Model default" }
        return "Model default (\(effort.label), from Claude Code)"
    }

    /// The model offers Claude Code's Auto mode; unknown models do not.
    public func supportsAuto(_ model: String?) -> Bool {
        info(for: model)?.supportsAutoMode == true
    }

    /// The permission modes to offer with this model.
    public func permissionModes(for model: String?) -> [PermissionMode] {
        PermissionMode.options(supportsAuto: supportsAuto(model))
    }

    /// How a chat on this model can go on after its plan is approved.
    public func planChoices(for model: String?) -> [PermissionMode] {
        PermissionMode.planChoices(supportsAuto: supportsAuto(model))
    }

    /// The mode a new chat keeps after switching to this model: Auto only where the model
    /// offers it, else the agent default when it names another mode, else Ask before edits.
    /// Never Claude Code's own setting (nil): the daemon starts a chat without a mode with
    /// the agent default (audit BUG-87).
    public func newChatPermission(_ current: PermissionMode?, afterSwitchingTo model: String?)
        -> PermissionMode?
    {
        guard current == .auto, !supportsAuto(model) else { return current }
        let fallback = self.current.permissionMode
        return fallback == nil || fallback == .auto ? .default : fallback
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
