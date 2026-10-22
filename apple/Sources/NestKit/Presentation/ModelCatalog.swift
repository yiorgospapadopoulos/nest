import Foundation

/// One engine's model list and what its menus offer from it: Claude Code's, or another
/// engine's such as Codex's (B91), which keeps its own models and thinking levels. Since
/// B94 the menus list real models only and the engine's default model is named.
public struct ModelCatalog: Sendable, Hashable {
    /// Empty until loaded, or when the daemon has no list. Real models only (B94).
    public var models: [ModelInfo]
    /// The model the engine runs when none is named; nil while unknown.
    public var defaultModel: String?
    /// The local models (B106), which run on any engine: looked up, never listed.
    public var local: [ModelInfo]

    public init(models: [ModelInfo], defaultModel: String? = nil, local: [ModelInfo] = []) {
        self.models = models
        self.defaultModel = defaultModel
        self.local = local
    }

    /// The list entry for a model; nil (a chat from before B94) is the engine's default.
    public func info(for model: String?) -> ModelInfo? {
        let value = model ?? defaultModel
        return models.first { $0.value == value } ?? local.first { $0.value == value }
    }

    /// The menu title: the model's display name, or its raw value when the list does not
    /// have it (an older session, or a list not loaded yet).
    public func label(for model: String?) -> String {
        info(for: model)?.displayName ?? model ?? defaultModel ?? "Model"
    }

    public func isSelected(_ info: ModelInfo, current model: String?) -> Bool {
        info.value == (model ?? defaultModel)
    }

    /// The thinking levels to offer: the model's own, or every level for a model the
    /// list does not describe.
    public func thinkingLevels(for model: String?) -> [Effort] {
        info(for: model)?.thinkingLevels ?? Effort.selectable
    }

    /// The effort a chat keeps after switching to this model: the current one as far as
    /// the model takes it, else Medium or the level nearest it (B94).
    public func effort(_ current: Effort?, afterSwitchingTo model: String?) -> Effort? {
        let levels = thinkingLevels(for: model)
        return Effort.fallback(current, supported: levels) ?? Effort.standard(supported: levels)
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
    /// offers it, else `fallback` (the agent default) when it names another mode, else Ask.
    /// None yet takes the fallback, as far as the model allows it.
    public func newChatPermission(
        _ current: PermissionMode?, afterSwitchingTo model: String?, fallback: PermissionMode
    ) -> PermissionMode {
        let mode = current ?? fallback
        guard mode == .auto, !supportsAuto(model) else { return mode }
        return fallback == .auto ? .default : fallback
    }
}

/// One engine's part of the model menu (B91), or the local models' (B106).
public struct ModelSection: Sendable, Hashable, Identifiable {
    /// The engine's name; Claude's for the one Model section without a choice of engines.
    /// For the local models, the engine choosing one runs the chat on.
    public let provider: String
    /// The engine's name, "Model" when there is no choice of engines, or "Local".
    public let title: String
    /// The plan, or "Not signed in"; empty for none.
    public let detail: String
    public let catalog: ModelCatalog
    /// The local models' section, which any engine's chat may choose from.
    public var local = false
    /// Models greyed out: their server does not answer.
    public var unavailable: Set<String> = []
    /// Models whose line is a warning: weak at tools.
    public var weak: Set<String> = []

    public var id: String { local ? "local" : provider }

    /// Whether the chat on `provider` (nil: Claude) with `model` is on this entry; a local
    /// model whatever the engine.
    public func isSelected(_ info: ModelInfo, provider chat: String?, model: String?) -> Bool {
        (local || (chat ?? ProviderInfo.claude) == provider)
            && catalog.isSelected(info, current: model)
    }

    public func isDisabled(_ info: ModelInfo) -> Bool {
        unavailable.contains(info.value)
    }

    public func warns(_ info: ModelInfo) -> Bool {
        weak.contains(info.value)
    }
}

/// A new chat's engine, model, thinking and mode, sent with its first message (B91).
public struct NewChatChoices: Sendable, Hashable {
    /// Nil runs on Claude.
    public var provider: String?
    public var model: String?
    public var effort: Effort?
    public var permission: PermissionMode

    public init(
        provider: String?, model: String?, effort: Effort?, permission: PermissionMode
    ) {
        self.provider = provider
        self.model = model
        self.effort = effort
        self.permission = permission
    }

    /// The choices on another engine, whose `catalog` is given: the agent defaults' engine
    /// takes their model and thinking again; any other engine starts on its own default
    /// model with Medium thinking or the level nearest it (B94). The mode stays where the
    /// new model allows it.
    public func switching(
        to provider: String?, catalog: ModelCatalog, defaults: AgentDefaults
    ) -> NewChatChoices {
        let target = Self.draftEngine(provider)
        guard target != self.provider else { return self }
        let own = target == Self.draftEngine(defaults.provider)
        let model = own ? defaults.model ?? catalog.defaultModel : catalog.defaultModel
        return NewChatChoices(
            provider: target, model: model,
            effort: catalog.effort(own ? defaults.effort : nil, afterSwitchingTo: model),
            permission: catalog.newChatPermission(
                permission, afterSwitchingTo: model, fallback: defaults.permissionMode))
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

    /// The new chat's choices from the agent defaults (`catalog` is their engine's).
    public static func from(_ defaults: AgentDefaults, catalog: ModelCatalog) -> NewChatChoices {
        let model = defaults.model ?? catalog.defaultModel
        let levels = catalog.thinkingLevels(for: model)
        return NewChatChoices(
            provider: draftEngine(defaults.provider), model: model,
            effort: defaults.effort ?? Effort.standard(supported: levels),
            permission: catalog.newChatPermission(
                nil, afterSwitchingTo: model, fallback: defaults.permissionMode))
    }

    /// How a draft names an engine: nil for Claude.
    public static func draftEngine(_ provider: String?) -> String? {
        provider == ProviderInfo.claude ? nil : provider
    }
}
