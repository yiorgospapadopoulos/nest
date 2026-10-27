import Foundation
import Observation

/// The engines chats run on (B91): whether each is signed in, its model list apart from
/// Claude's (which `AgentsStore` keeps), and what its chats cannot do, which the views
/// hide. Gating reads the daemon's lists, never an engine's name: an engine not loaded or
/// not listed offers everything, and the daemon still refuses what it cannot do.
@MainActor @Observable
public final class ProvidersStore {
    /// The default engine first; empty until loaded, and from a daemon before B91.
    public private(set) var providers: [ProviderInfo] = []
    /// The other engines' models, by engine name.
    public private(set) var models: [String: [ModelInfo]] = [:]
    /// The other engines' default models, by engine name (B94).
    public private(set) var defaultModels: [String: String] = [:]

    /// The local models (B106), which every engine's menus offer.
    public let local: LocalModelsStore

    let api: any NestAPI

    public init(api: any NestAPI, local: LocalModelsStore? = nil) {
        self.api = api
        self.local = local ?? LocalModelsStore(api: api)
    }

    /// Loads the engines, then each other engine's models; `refresh` asks the engines for
    /// their login now. A part the daemon cannot answer keeps its last value.
    public func load(refresh: Bool = false) async {
        if let list = try? await api.providers(refresh: refresh) {
            providers = list.providers
        }
        // An engine not ready has no models to list yet (B107).
        for provider in providers
        where provider.name != ProviderInfo.claude && provider.state == .ready {
            if let list = try? await api.models(provider: provider.name) {
                models[provider.name] = list.models
                defaultModels[provider.name] = list.defaultModel
            }
        }
    }

    /// Starts installing the engine; `engine.state` reloads the engines as it goes (B107).
    public func install(_ name: String) async throws {
        try await api.installEngine(name)
        await load()
    }

    /// Whether the accounts say an engine Nest checks itself (not through the browser) is
    /// signed in otherwise than the engines' list does, so the list is stale (B107).
    public func signInChanged(_ accounts: [EngineAccount]) -> Bool {
        providers.contains { provider in
            guard provider.signIn != .browser,
                let active = accounts.first(where: { $0.provider == provider.name && $0.active })
            else { return false }
            return active.signedIn != provider.signedIn
        }
    }

    /// A new chat can run on more than one engine, so the composer offers the choice.
    public var offersChoice: Bool {
        providers.count > 1
    }

    /// Nil is Claude.
    public func provider(_ name: String?) -> ProviderInfo? {
        let name = name ?? ProviderInfo.claude
        return providers.first { $0.name == name }
    }

    /// Nil is Claude; an engine not listed is named after itself.
    public func displayName(_ name: String?) -> String {
        provider(name)?.displayName ?? (name ?? ProviderInfo.claude).capitalized
    }

    /// The running agent's name in a chat's words, such as "Codex reads this at its next
    /// step": its engine's name; Claude for a chat on Claude or none.
    public func agentName(in session: Session?) -> String {
        displayName(session?.provider)
    }

    /// The grey line under an engine in the menu: not ready (B107), not signed in, else its
    /// plan.
    public func detail(for provider: ProviderInfo) -> String {
        switch provider.state {
        case .ready: break
        case .installing: return "Installing"
        case .notInstalled: return "Not installed"
        case .installFailed: return "Install failed"
        case .unknown: return "Not ready"
        }
        if provider.signedIn == false {
            return "Not signed in"
        }
        return provider.account?.plan ?? ""
    }

    /// Whether chats on the engine (nil: Claude) can do it.
    public func supports(_ feature: ProviderFeature, on name: String?) -> Bool {
        provider(name)?.unsupported.contains(feature) != true
    }

    /// Whether the chat can do it; nil (no chat yet) is a Claude chat's draft.
    public func supports(_ feature: ProviderFeature, in session: Session?) -> Bool {
        supports(feature, on: session?.provider)
    }

    /// Whether a pending message can still be edited or removed: one written into the
    /// running turn only on an engine that can take it back.
    public func canTakeBack(_ message: QueuedMessage, in session: Session?) -> Bool {
        !message.sent || supports(.withdraw, in: session)
    }

    /// What to tell the user before sending on an engine that said it is not signed in.
    /// None once local models make signing in optional (B106).
    public func signInHint(for name: String?) -> String? {
        guard !local.signInOptional, let provider = provider(name), provider.signedIn == false
        else { return nil }
        return provider.signInHint ?? "\(provider.displayName) isn't signed in."
    }

    /// The engine's name for a chat off Claude, the default, where the chat shows it; a
    /// local chat's header says it in its own words (B106).
    public func label(for session: Session?) -> String? {
        guard let name = session?.provider, name != ProviderInfo.claude,
            localModel(in: session) == nil
        else { return nil }
        return displayName(name)
    }

    /// The local model the chat runs on, if any (B106).
    public func localModel(in session: Session?) -> LocalModel? {
        local.model(session?.model)
    }

    /// The model menu's sections (B91): a new chat's every engine, each under its name with
    /// its plan or that it is not signed in, so choosing a model chooses the engine; a chat
    /// that exists only its own engine's. With one engine, one Model section as before. A
    /// new chat cannot choose an engine not ready or signed out where Nest checks it: its
    /// models are greyed under what it waits on (B107).
    public func modelSections(claude: ModelCatalog, provider: String?, isDraft: Bool)
        -> [ModelSection]
    {
        let own = provider ?? ProviderInfo.claude
        let listed = providers.filter { isDraft || $0.name == own }
        let engines =
            offersChoice
            ? listed.map { info in
                var section = ModelSection(
                    provider: info.name, title: info.displayName, detail: detail(for: info),
                    catalog: catalog(for: info.name, claude: claude))
                if isDraft && !info.offeredForNewChats {
                    section.unavailable = Set(section.catalog.models.map(\.value))
                }
                return section
            }
            : [
                ModelSection(
                    provider: ProviderInfo.claude, title: "Model", detail: "", catalog: claude)
            ]
        return engines + localSection(engine: isDraft ? local.engine : own)
    }

    /// The local models under "Local" (B106), chosen on `engine`; none without any.
    private func localSection(engine: String) -> [ModelSection] {
        guard local.hasModels else { return [] }
        let values = { (models: [LocalModel]) in Set(models.map(\.value)) }
        return [
            ModelSection(
                provider: engine, title: LocalModelText.menuTitle,
                detail: LocalModelText.menuDetail, catalog: ModelCatalog(models: local.infos),
                local: true, unavailable: values(local.models.filter { !$0.running }),
                weak: values(local.models.filter(\.isWeak)))
        ]
    }

    /// A model's name, after its engine's off Claude, such as "Codex · GPT-5.5" (B94).
    public func modelTitle(_ model: String?, on provider: String?, claude: ModelCatalog)
        -> String
    {
        if let local = local.model(model) {
            return local.name
        }
        let name = catalog(for: provider, claude: claude).label(for: model)
        guard let provider, provider != ProviderInfo.claude else { return name }
        return "\(displayName(provider)) · \(name)"
    }

    /// The engine's models (nil: Claude's, which `AgentsStore` keeps), knowing the local
    /// models too (B106).
    public func catalog(for name: String?, claude: ModelCatalog) -> ModelCatalog {
        var catalog =
            if let name, name != ProviderInfo.claude {
                ModelCatalog(models: models[name] ?? [], defaultModel: defaultModels[name])
            } else {
                claude
            }
        catalog.local = local.infos
        return catalog
    }
}
