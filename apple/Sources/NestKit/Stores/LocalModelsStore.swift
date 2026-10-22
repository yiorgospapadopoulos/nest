import Foundation
import Observation

/// The local models (B106): the ones added, the engine local chats run on, today's tokens,
/// the first-run welcome, the weak-at-tools warnings this device dismissed, and the chats
/// whose server did not answer.
@MainActor @Observable
public final class LocalModelsStore {
    /// Where the dismissed warnings are kept, as model ids joined by commas.
    public static let dismissedKey = "local.weakDismissed"

    public private(set) var models: [LocalModel] = []
    /// "claude" or "codex".
    public private(set) var engine = ProviderInfo.claude
    public private(set) var localOnly = false
    public private(set) var usage: LocalUsage?
    /// Nil until read.
    public private(set) var setup: SetupState?
    /// Chats whose server did not answer, by session id.
    public private(set) var serverDown: [String: LocalServerDown] = [:]
    /// Apps whose server is being started.
    public private(set) var starting: Set<LocalApp> = []
    /// The reload an event started last.
    public private(set) var reload: Task<Void, Never>?
    private var dismissed: Set<String>

    let api: any NestAPI
    let preferences: (any KeyValueStore)?

    public init(api: any NestAPI, preferences: (any KeyValueStore)? = nil) {
        self.api = api
        self.preferences = preferences
        dismissed = Set(
            (preferences?.string(forKey: Self.dismissedKey) ?? "").split(separator: ",")
                .map(String.init))
    }

    /// Reads the list, the setup and today's tokens; a part the daemon cannot answer keeps
    /// its last value.
    public func load() async {
        if let list = try? await api.localModels() {
            models = list.models
            engine = list.engine
            localOnly = list.localOnly
        }
        if let setup = try? await api.setup() {
            self.setup = setup
        }
        await loadUsage()
    }

    public func loadUsage() async {
        if let usage = try? await api.localUsage() {
            self.usage = usage
        }
    }

    public var hasModels: Bool { !models.isEmpty }

    /// Chats run without an engine sign-in: local models exist or the user chose them only.
    public var signInOptional: Bool { localOnly || hasModels }

    public var isFirstRun: Bool { setup?.firstRun == true }

    /// The local model a chat's model value names.
    public func model(_ value: String?) -> LocalModel? {
        guard let value, LocalModel.isLocal(value) else { return nil }
        let id = value.dropFirst(LocalModel.prefix.count)
        return models.first { $0.id == id }
    }

    /// The models as the menus list them; thinking where the model has it, never Auto.
    public var infos: [ModelInfo] {
        models.map { model in
            ModelInfo(
                value: model.value, displayName: model.name,
                description: LocalModelText.menuDetail(model),
                effortLevels: model.thinking ? [.low, .medium, .high] : [],
                supportsEffort: model.thinking)
        }
    }

    /// Adds the server's models; answers them, and they replace any listed with their id.
    @discardableResult
    public func add(address: String, key: String?, models ids: [String]) async throws
        -> [LocalModel]
    {
        let added = try await api.addLocalModels(address: address, key: key, models: ids)
        let addedIDs = Set(added.map(\.id))
        models = models.filter { !addedIDs.contains($0.id) } + added
        return added
    }

    public func remove(_ id: String) async throws {
        try await api.removeLocalModel(id)
        models.removeAll { $0.id == id }
    }

    /// Shows the engine at once and goes back when the daemon refuses it.
    public func setEngine(_ engine: String) async throws {
        let previous = self.engine
        self.engine = engine
        do {
            try await api.setLocalEngine(engine)
        } catch {
            self.engine = previous
            throw error
        }
    }

    /// Starts the app's server, then reads who answers now.
    public func start(_ app: LocalApp) async throws {
        starting.insert(app)
        defer { starting.remove(app) }
        try await api.startLocalServer(app)
        await load()
    }

    public func useLocalOnly() async throws {
        try await api.useLocalOnly()
        setup = SetupState(firstRun: false, localOnly: true)
        localOnly = true
    }

    public func finishSetup() async throws {
        try await api.finishSetup()
        setup = SetupState(firstRun: false, localOnly: setup?.localOnly ?? false)
    }

    // MARK: Weak at tools

    /// The chat's model when it is weak at tools and its warning was not dismissed here.
    public func weakWarning(for value: String?) -> LocalModel? {
        guard let model = model(value), model.isWeak, !dismissed.contains(model.id) else {
            return nil
        }
        return model
    }

    /// Don't show again, for this model on this device.
    public func dismissWarning(_ id: String) {
        dismissed.insert(id)
        preferences?.set(dismissed.sorted().joined(separator: ","), forKey: Self.dismissedKey)
    }

    // MARK: Server down

    public func markDown(_ chat: String, _ down: LocalServerDown) {
        serverDown[chat] = down
    }

    public func clearDown(_ chat: String) {
        serverDown[chat] = nil
    }

    // MARK: Events

    /// The list changed; a turn ended (today's tokens grew); a turn ended on a down server,
    /// or a new one started.
    public func apply(_ event: Event) {
        switch event.body {
        case .localModelsChanged:
            reload = Task { await load() }
        case .sessionState(let state, _):
            guard let chat = event.sessionID else { return }
            if event.payload["code"]?.stringValue == LocalServerDown.code {
                markDown(chat, LocalServerDown(event.payload))
            } else if state == .running || state == .starting {
                clearDown(chat)
            }
        default:
            if event.type == EventType.sessionResult, hasModels {
                reload = Task { await loadUsage() }
            }
        }
    }

    // MARK: Top bar

    /// "Local · 49k tokens today" while no account is signed in to show limits for.
    public func chip(accounts: [EngineAccount]) -> String? {
        guard signInOptional, !accounts.contains(where: { $0.signedIn == true }) else {
            return nil
        }
        return LocalModelText.chip(tokens: usage?.todayTokens ?? 0)
    }
}
