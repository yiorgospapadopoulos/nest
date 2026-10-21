import Foundation

/// Feeds the daemon's live events into the stores, and reloads them on each connect so
/// nothing missed while disconnected is lost; open transcripts catch up too.
@MainActor
public final class LiveSync {
    let source: any EventSource
    let app: AppStore
    let sessions: SessionsStore
    let approvals: ApprovalsStore
    let activity: ActivityStore
    let transcripts: Transcripts
    let usage: UsageStore
    let connectors: ConnectorsStore
    let claudeChats: ClaudeChatsStore
    let agents: AgentsStore
    let providers: ProvidersStore
    let pixies: PixiesStore
    let reports: PixieReportsStore
    let habits: HabitsStore
    let chatPixies: ChatPixiesStore
    let accounts: AccountsStore
    let extensions: ExtensionsStore
    let configuration: ConfigurationStore
    /// Called for each `usage.warning` event, for a notification (B81).
    public var onUsageWarning: ((UsageWarning) -> Void)?
    let artifacts: ArtifactsStore
    /// Called for each `notify` event, for notification delivery.
    public var onNotice: ((Notice) -> Void)?
    /// Called after each connect has reloaded the stores.
    public var onConnected: (() -> Void)?
    /// The reload of the engines and agent defaults an account change started.
    public private(set) var engineReload: Task<Void, Never>?

    public init(
        source: any EventSource, app: AppStore, sessions: SessionsStore, approvals: ApprovalsStore,
        activity: ActivityStore, transcripts: Transcripts, usage: UsageStore,
        connectors: ConnectorsStore, claudeChats: ClaudeChatsStore, agents: AgentsStore,
        providers: ProvidersStore, pixies: PixiesStore, reports: PixieReportsStore,
        habits: HabitsStore,
        chatPixies: ChatPixiesStore, accounts: AccountsStore, extensions: ExtensionsStore,
        configuration: ConfigurationStore, artifacts: ArtifactsStore
    ) {
        self.source = source
        self.app = app
        self.sessions = sessions
        self.approvals = approvals
        self.activity = activity
        self.transcripts = transcripts
        self.usage = usage
        self.connectors = connectors
        self.claudeChats = claudeChats
        self.agents = agents
        self.providers = providers
        self.pixies = pixies
        self.reports = reports
        self.habits = habits
        self.chatPixies = chatPixies
        self.accounts = accounts
        self.extensions = extensions
        self.configuration = configuration
        self.artifacts = artifacts
    }

    /// Runs until the task is cancelled or the daemon refuses the connection.
    public func run() async {
        app.connection = .connecting
        do {
            for try await update in source.updates() {
                switch update {
                case .connected(let resumed):
                    app.connection = .connected
                    await refresh()
                    await transcripts.catchUp(missed: !resumed)
                    onConnected?()
                case .reconnecting(let attempt, let delay):
                    app.connection = .reconnecting(attempt: attempt, delay: delay)
                case .event(let event):
                    route(event)
                }
            }
            app.connection = .disconnected
        } catch EventStreamError.unauthorized {
            app.connection = .unauthorized
        } catch EventStreamError.forbiddenOrigin {
            app.connection = .forbiddenOrigin
        } catch {
            app.connection = .disconnected
        }
    }

    /// Reloads repos, sessions, approvals, connectors, the usage chart, Claude Code chats,
    /// pixies and their reports, and the artifacts, then the models, agent defaults and
    /// account, the engines, their accounts with their limits (B98) and each chat's pixies,
    /// which never fail the sync.
    public func refresh() async {
        do {
            try await app.loadRepos()
            try await approvals.load()
            try await sessions.load()
            try await connectors.load()
            try await usage.loadPeriod()
            try await claudeChats.load()
            try await pixies.load()
            try await reports.load()
            try await artifacts.reload()
            app.syncError = nil
        } catch {
            app.syncError = error as? APIError ?? .transport(String(describing: error))
        }
        await agents.load()
        await providers.load()
        try? await accounts.load()
        await chatPixies.load()
    }

    /// The engines' logins and models, and the defaults the daemon may now resolve.
    private func reloadEngines() {
        engineReload = Task {
            await providers.load()
            await agents.load()
        }
    }

    public func route(_ event: Event) {
        sessions.apply(event)
        approvals.apply(event)
        activity.apply(event)
        transcripts.receive(event)
        usage.apply(event)
        connectors.apply(event)
        claudeChats.apply(event)
        pixies.apply(event)
        reports.apply(event)
        habits.apply(event)
        chatPixies.apply(event)
        accounts.apply(event)
        extensions.apply(event)
        configuration.apply(event)
        artifacts.apply(event)
        switch event.body {
        case .usageWarning(let warning):
            onUsageWarning?(warning)
        case .sessionDeleted(let id):
            app.forgetChat(id)
        case .notify(let notice):
            onNotice?(notice)
        case .reposChanged:
            app.reloadRepos()
        case .codexAccount:
            // Signed in or out: the engines' lists and the defaults may change (B94).
            reloadEngines()
        case .result:
            // A turn in a plain folder may have run git init; the repo update event, when
            // the daemon sends one, makes this redundant but harmless.
            if let id = event.sessionID, let repo = sessions.session(id)?.repo,
                app.repo(repo)?.git == false
            {
                app.reloadRepos()
            }
        default:
            break
        }
    }
}

/// Every store of the Mac app, wired to one daemon.
@MainActor
public final class AppModel {
    public let api: any NestAPI
    public let app: AppStore
    public let sessions: SessionsStore
    public let approvals: ApprovalsStore
    public let activity: ActivityStore
    public let transcripts: Transcripts
    public let usage: UsageStore
    public let connectors: ConnectorsStore
    public let claudeChats: ClaudeChatsStore
    public let completions: CompletionStore
    /// `!` commands run since each chat's last message (B59).
    public let bash: BashStore
    /// Tool result images, read once each.
    public let images: AttachmentImages
    public let settings: SettingsStore
    public let devices: DevicesStore
    public let visibility: VisibilityReporter
    public let search: MessageSearch
    public let stuck: StuckSettingsStore
    public let agents: AgentsStore
    /// The engines chats run on, and their models apart from Claude's (B91).
    public let providers: ProvidersStore
    public let pixies: PixiesStore
    public let reports: PixieReportsStore
    public let habits: HabitsStore
    /// Each chat's pixies and the open work page (B46).
    public let chatPixies: ChatPixiesStore
    /// Settings (B81): storage, pixie defaults, accounts, extensions and the shortcuts.
    public let storage: StorageStore
    public let pixieSettings: PixieSettingsStore
    public let notificationRules: NotificationRulesStore
    public let accounts: AccountsStore
    public let extensions: ExtensionsStore
    /// Settings > Configuration (B97).
    public let configuration: ConfigurationStore
    public let shortcuts: ShortcutsStore
    /// Artifacts the chats saved and the Artifacts view (B79).
    public let artifacts: ArtifactsStore
    public let live: LiveSync
    /// Where `local()` got the device token, to ask again.
    var tokens: (store: any TokenStore, token: DeviceToken)?
    /// The live sync `connect()` started last.
    private var liveTask: Task<Void, Never>?

    public init(
        api: any NestAPI, events: any EventSource,
        preferences: any KeyValueStore = UserDefaultsStore(), calendar: Calendar = .current,
        now: @escaping @Sendable () -> Date = { Date() }
    ) {
        self.api = api
        approvals = ApprovalsStore(api: api)
        app = AppStore(api: api, store: preferences)
        sessions = SessionsStore(api: api, approvals: approvals)
        activity = ActivityStore(api: api)
        transcripts = Transcripts(api: api)
        usage = UsageStore(api: api, calendar: calendar, now: now)
        connectors = ConnectorsStore(api: api)
        settings = SettingsStore(store: preferences)
        claudeChats = ClaudeChatsStore(api: api, settings: settings)
        completions = CompletionStore(api: api)
        bash = BashStore(api: api)
        images = AttachmentImages(api: api)
        devices = DevicesStore(api: api, now: now)
        visibility = VisibilityReporter(api: api, now: now)
        search = MessageSearch(api: api)
        stuck = StuckSettingsStore(api: api)
        agents = AgentsStore(api: api)
        providers = ProvidersStore(api: api)
        pixies = PixiesStore(api: api)
        reports = PixieReportsStore(api: api, now: now)
        habits = HabitsStore(api: api)
        chatPixies = ChatPixiesStore(api: api)
        storage = StorageStore(api: api)
        pixieSettings = PixieSettingsStore(api: api)
        notificationRules = NotificationRulesStore(api: api)
        accounts = AccountsStore(api: api)
        extensions = ExtensionsStore(api: api)
        configuration = ConfigurationStore(api: api)
        shortcuts = ShortcutsStore(store: preferences)
        artifacts = ArtifactsStore(api: api)
        live = LiveSync(
            source: events, app: app, sessions: sessions, approvals: approvals,
            activity: activity, transcripts: transcripts, usage: usage, connectors: connectors,
            claudeChats: claudeChats, agents: agents, providers: providers, pixies: pixies,
            reports: reports,
            habits: habits, chatPixies: chatPixies, accounts: accounts, extensions: extensions,
            configuration: configuration, artifacts: artifacts)
        // A restarted daemon has forgotten that this app is on screen.
        live.onConnected = { [visibility] in visibility.resend() }
    }

    /// Whether a device token is in use; false while the daemon was not running to give one.
    public var hasDeviceToken: Bool { tokens.map { !$0.token.current.isEmpty } ?? true }

    /// Asks the daemon for the device token again when it refused the one in use or none
    /// was given yet (the daemon may have started since, or made a new token). True when
    /// the token changed. Models not built by `local()` keep theirs.
    @discardableResult
    public func rereadToken() async throws -> Bool {
        guard let tokens, app.connection == .unauthorized || !hasDeviceToken,
            let token = try await Self.read(tokens.store), token != tokens.token.current
        else { return false }
        tokens.token.replace(with: token)
        return true
    }

    /// Drops the current connection and connects again at once, asking the daemon for its
    /// token first when needed (`rereadToken()`). A failed request is returned, and the
    /// connection runs with the token it has.
    @discardableResult
    public func connect() async -> (any Error)? {
        var failure: (any Error)?
        do {
            try await rereadToken()
        } catch {
            failure = error
        }
        liveTask?.cancel()
        liveTask = Task { await runLive() }
        return failure
    }

    /// Runs the live sync. When the daemon refuses the token, it is asked for again once,
    /// and a different one connects at once: the daemon started after the app, or made a
    /// new token. Otherwise the refusal stays for the user's Retry.
    func runLive() async {
        await live.run()
        while app.connection == .unauthorized, !Task.isCancelled,
            (try? await rereadToken()) == true
        {
            await live.run()
        }
    }

    /// The socket read blocks, so it runs away from the main actor.
    @concurrent
    private static func read(_ tokens: any TokenStore) async throws -> String? {
        try tokens.deviceToken()
    }

    /// The model for the daemon on this Mac, with the device token the daemon gives over its
    /// socket. Without a running daemon the model starts without a token, so the app shows
    /// the daemon as unreachable (with the offer to start it), and asks again on connect.
    public static func local(
        tokens: any TokenStore = SocketTokenStore(), baseURL: URL = APIClient.defaultBaseURL
    ) async throws -> AppModel {
        let token = DeviceToken(try await read(tokens) ?? "")
        let model = AppModel(
            api: APIClient(token: token, baseURL: baseURL),
            events: EventStream(token: token, baseURL: baseURL))
        model.tokens = (tokens, token)
        return model
    }
}
