import Foundation

/// A pixie's Model row (B91): one picker for its engine and model, a section per engine
/// as in a new chat's model menu, so choosing a model chooses the engine. Only real models,
/// no Default entry (B94). The row names the engine only for a pixie off Claude.
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
        /// Greyed: a local model whose server does not answer (B106).
        public let disabled: Bool
        /// Its line is a warning: weak at tools.
        public let warns: Bool
        /// The change choosing it saves.
        public let request: UpdatePixieRequest
    }

    public let sections: [Section]
    /// The row's value: the model, after its engine's name off Claude.
    public let value: String
    /// The pixie's engine's models, for its Thinking and Permissions rows.
    public let catalog: ModelCatalog
    /// The model its runs ask for: its own, or its engine's default until the daemon gave
    /// it one (B94).
    public let runningModel: String?

    /// `claude` is Claude Code's list.
    public init(pixie: Pixie, providers: ProvidersStore, claude: ModelCatalog) {
        let engine = pixie.engine
        catalog = providers.catalog(for: engine, claude: claude)
        runningModel = pixie.model ?? catalog.defaultModel
        let sections = providers.modelSections(claude: claude, provider: engine, isDraft: true)
        self.sections = sections.map { section in
            Section(
                provider: section.provider, title: section.title, detail: section.detail,
                entries: Self.entries(of: section, pixie: pixie))
        }
        value = providers.modelTitle(pixie.model, on: engine, claude: claude)
    }

    /// Real models only (B94): choosing another engine's model names that engine too.
    private static func entries(of section: ModelSection, pixie: Pixie) -> [Entry] {
        let provider = section.provider == pixie.engine ? nil : section.provider
        return section.catalog.models.map { info in
            Entry(
                id: info.value, title: info.displayName, detail: info.description,
                checked: section.isSelected(info, provider: pixie.engine, model: pixie.model),
                disabled: section.isDisabled(info), warns: section.warns(info),
                request: UpdatePixieRequest(provider: provider, model: info.value))
        }
    }
}
