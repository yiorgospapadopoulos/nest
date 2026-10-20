import Foundation

/// One engine's model list and what its menus offer from it: Claude Code's, or another
/// engine's such as Codex's (B91), which keeps its own models and thinking levels.
public struct ModelCatalog: Sendable, Hashable {
    /// The value both engines' lists use for their default model.
    public static let defaultModel = "default"

    /// Empty until loaded, or when the daemon has no list.
    public var models: [ModelInfo]

    public init(models: [ModelInfo]) {
        self.models = models
    }

    /// The list entry for a model; nil stands for the engine's default.
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

    /// The model offers the Auto mode; unknown models do not.
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
    /// offers it, else `fallback` (the agent default) when it names another mode, else
    /// Ask before edits. Never the engine's own setting (nil): the daemon starts a chat
    /// without a mode with the agent default (audit BUG-87).
    public func newChatPermission(
        _ current: PermissionMode?, afterSwitchingTo model: String?, fallback: PermissionMode?
    ) -> PermissionMode? {
        guard current == .auto, !supportsAuto(model) else { return current }
        return fallback == nil || fallback == .auto ? .default : fallback
    }
}

/// One engine's part of the model menu (B91).
public struct ModelSection: Sendable, Hashable, Identifiable {
    /// The engine's name; Claude's for the one Model section without a choice of engines.
    public let provider: String
    /// The engine's name, or "Model" when there is no choice of engines.
    public let title: String
    /// The plan, or "Not signed in"; empty for none.
    public let detail: String
    public let catalog: ModelCatalog

    public var id: String { provider }

    /// Whether the chat on `provider` (nil: Claude) with `model` is on this entry.
    public func isSelected(_ info: ModelInfo, provider chat: String?, model: String?) -> Bool {
        (chat ?? ProviderInfo.claude) == provider && catalog.isSelected(info, current: model)
    }
}

/// A new chat's engine, model, thinking and mode, sent with its first message (B91).
public struct NewChatChoices: Sendable, Hashable {
    /// Nil runs on Claude, the default engine.
    public var provider: String?
    public var model: String?
    public var effort: Effort?
    public var permission: PermissionMode?

    public init(
        provider: String?, model: String?, effort: Effort?, permission: PermissionMode?
    ) {
        self.provider = provider
        self.model = model
        self.effort = effort
        self.permission = permission
    }

    /// The choices on another engine, whose `catalog` is given: Claude takes the agent
    /// defaults' model and thinking again, which are Claude's (D113); any other engine
    /// starts on its own default model and thinking. The mode stays where the new model
    /// allows it; on another engine, where Claude Code's own setting (nil) means nothing,
    /// it is the agent default's, else Ask.
    public func switching(
        to provider: String?, catalog: ModelCatalog, defaults: AgentDefaults
    ) -> NewChatChoices {
        let target = provider == ProviderInfo.claude ? nil : provider
        guard target != self.provider else { return self }
        let model = target == nil ? defaults.model : nil
        let kept = catalog.newChatPermission(
            permission, afterSwitchingTo: model, fallback: defaults.permissionMode)
        return NewChatChoices(
            provider: target, model: model, effort: target == nil ? defaults.effort : nil,
            permission: target == nil ? kept : kept ?? defaults.permissionMode ?? .default)
    }

    /// A model chosen from the menu, of `provider`'s list (`catalog`): the engine follows
    /// first, then the thinking and mode as far as the model allows them.
    public func choosing(
        _ model: String, on provider: String?, catalog: ModelCatalog, defaults: AgentDefaults
    ) -> NewChatChoices {
        var next = switching(to: provider, catalog: catalog, defaults: defaults)
        next.model = model
        next.effort = catalog.effort(next.effort, afterSwitchingTo: model)
        next.permission = catalog.newChatPermission(
            next.permission, afterSwitchingTo: model, fallback: defaults.permissionMode)
        return next
    }
}
