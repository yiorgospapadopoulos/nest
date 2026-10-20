import Foundation

/// A pixie's Model row (B91): one picker for its engine and model, a section per engine
/// as in a new chat's model menu, so choosing a model chooses the engine. Claude's section
/// starts with Default, the agent default; another engine's lists its own default entry,
/// which leaves the pixie without a model of its own. The row names the engine only for a
/// pixie off Claude.
@MainActor
public struct PixieModelPicker {
    /// One engine's part of the picker.
    public struct Section: Identifiable {
        public let provider: String
        /// The engine's name, or "Model" when there is no choice of engines.
        public let title: String
        /// Its plan, or "Not signed in"; empty for none.
        public let detail: String
        public let entries: [Entry]
        /// The engine's list is not loaded: the picker says models are unavailable.
        public var unavailable: Bool { entries.isEmpty }

        public var id: String { provider }
    }

    public struct Entry: Identifiable {
        public let id: String
        public let title: String
        public let detail: String
        public let checked: Bool
        /// The change choosing it saves.
        public let request: UpdatePixieRequest
    }

    public let sections: [Section]
    /// The row's value: the model, after its engine's name off Claude.
    public let value: String
    /// The pixie's engine's models, for its Thinking and Permissions rows.
    public let catalog: ModelCatalog
    /// The model its runs ask for: its own, else on Claude the agent default; nil leaves
    /// it to its engine.
    public let runningModel: String?

    /// `claude` is Claude Code's list, `agentDefault` the agent defaults' model.
    public init(
        pixie: Pixie, providers: ProvidersStore, claude: ModelCatalog, agentDefault: String?
    ) {
        let engine = pixie.engine
        let onClaude = engine == ProviderInfo.claude
        catalog = providers.catalog(for: engine, claude: claude)
        runningModel = pixie.model ?? (onClaude ? agentDefault : nil)
        let sections = providers.modelSections(claude: claude, provider: engine, isDraft: true)
        self.sections = sections.map { section in
            Section(
                provider: section.provider, title: section.title, detail: section.detail,
                entries: Self.entries(of: section, pixie: pixie, claude: claude, agentDefault))
        }
        let model =
            pixie.model == nil && onClaude ? "Default" : catalog.label(for: pixie.model)
        value = onClaude ? model : "\(providers.displayName(engine)) · \(model)"
    }

    private static func entries(
        of section: ModelSection, pixie: Pixie, claude: ModelCatalog, _ agentDefault: String?
    ) -> [Entry] {
        let own = section.provider == pixie.engine
        // Choosing another engine's model names that engine too.
        let provider = own ? nil : section.provider
        let models = section.catalog.models
        guard section.provider == ProviderInfo.claude else {
            return models.map { info in
                let isDefault = info.value == ModelCatalog.defaultModel
                return Entry(
                    id: info.value, title: info.displayName, detail: info.description,
                    checked: own && (pixie.model ?? ModelCatalog.defaultModel) == info.value,
                    request: isDefault
                        ? UpdatePixieRequest(provider: provider, clearsModel: true)
                        : UpdatePixieRequest(provider: provider, model: info.value))
            }
        }
        let fallback = Entry(
            id: "", title: "Default",
            detail: "The agent default, now \(claude.label(for: agentDefault))",
            checked: own && pixie.model == nil,
            request: UpdatePixieRequest(provider: provider, clearsModel: true))
        return [fallback]
            + models.map { info in
                Entry(
                    id: info.value, title: info.displayName, detail: info.description,
                    checked: own && pixie.model != nil
                        && claude.isSelected(info, current: pixie.model),
                    request: UpdatePixieRequest(provider: provider, model: info.value))
            }
    }
}
