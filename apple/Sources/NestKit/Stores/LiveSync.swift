import Foundation

/// Feeds the daemon's live events into the stores, and reloads them on each connect so
/// nothing missed while disconnected is lost.
@MainActor
public final class LiveSync {
    let source: any EventSource
    let app: AppStore
    let sessions: SessionsStore
    let approvals: ApprovalsStore
    let activity: ActivityStore
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
    let branchMaps: BranchMapStore
    let runs: RunStore
    let updates: UpdatesStore
    /// The island around the notch (B114), set by the app model.
    var island: IslandStore?
    /// Settings > Performance (B115), set by the app model.
    var performance: PerformanceStore?
    /// Computer use (B150), set by the app model.
    var computer: ComputerStore?
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
        activity: ActivityStore, usage: UsageStore,
        connectors: ConnectorsStore, claudeChats: ClaudeChatsStore, agents: AgentsStore,
        providers: ProvidersStore, pixies: PixiesStore, reports: PixieReportsStore,
        habits: HabitsStore,
        chatPixies: ChatPixiesStore, accounts: AccountsStore, extensions: ExtensionsStore,
        configuration: ConfigurationStore, artifacts: ArtifactsStore, branchMaps: BranchMapStore,
        runs: RunStore, updates: UpdatesStore
    ) {
        self.source = source
        self.app = app
        self.sessions = sessions
        self.approvals = approvals
        self.activity = activity
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
        self.branchMaps = branchMaps
        self.runs = runs
        self.updates = updates
    }

    /// Runs until the task is cancelled or the daemon refuses the connection. A cancelled
    /// run, replaced by a new connect, says nothing more about the connection: ending after
    /// the new one connected, it marked the window as not connected (B130).
    public func run() async {
        app.connection = .connecting
        let ended: ConnectionState
        do {
            for try await update in source.updates() {
                guard !Task.isCancelled else { return }
                switch update {
                case .connected:
                    app.connection = .connected
                    await refresh()
                    await updates.connected()
                    onConnected?()
                case .reconnecting(let attempt, let delay):
                    app.connection = .reconnecting(attempt: attempt, delay: delay)
                case .event(let event):
                    route(event)
                }
            }
            ended = .disconnected
        } catch EventStreamError.unauthorized {
            ended = .unauthorized
        } catch EventStreamError.forbiddenOrigin {
            ended = .forbiddenOrigin
        } catch {
            ended = .disconnected
        }
        if !Task.isCancelled {
            app.connection = ended
        }
    }

    /// Reloads repos, sessions, approvals, connectors, the usage chart, Claude Code chats,
    /// pixies and their reports, and the artifacts, then the models, agent defaults and
    /// account, the engines, their accounts with their limits (B98), each chat's pixies, the
    /// branch maps and the runs (B108), which never fail the sync.
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
        await providers.local.load()
        try? await accounts.load()
        await chatPixies.load()
        await branchMaps.reload()
        await runs.reload()
        await island?.refresh()
        computer?.reset()
        try? await computer?.loadSettings()
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
        usage.apply(event)
        connectors.apply(event)
        claudeChats.apply(event)
        pixies.apply(event)
        reports.apply(event)
        habits.apply(event)
        chatPixies.apply(event)
        accounts.apply(event)
        providers.local.apply(event)
        extensions.apply(event)
        configuration.apply(event)
        artifacts.apply(event)
        branchMaps.apply(event)
        runs.apply(event)
        updates.apply(event)
        island?.apply(event)
        performance?.apply(event)
        computer?.apply(event)
        switch event.body {
        case .usageWarning(let warning):
            onUsageWarning?(warning)
        case .sessionDeleted(let id):
            app.forgetChat(id)
        case .notify(let notice):
            onNotice?(notice)
        case .reposChanged, .branchesChanged:
            // A branch change may be the project folder's own, which its label shows.
            app.reloadRepos()
        case .codexAccount, .engineState:
            // Signed in or out, or installed: the engines' lists and the defaults may
            // change (B94, B107).
            reloadEngines()
        case .accountsChanged(let accounts):
            // An engine Nest checks itself signed in or out, such as from Terminal (B107).
            if providers.signInChanged(accounts) {
                reloadEngines()
            }
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
    /// The local models (B106), which the engines' menus offer too.
    public let local: LocalModelsStore
    public let pixies: PixiesStore
    public let reports: PixieReportsStore
    public let habits: HabitsStore
    /// Each chat's pixies and the open work page (B46).
    public let chatPixies: ChatPixiesStore
    /// Settings (B81): storage, pixie defaults, accounts, extensions and the shortcuts.
    public let storage: StorageStore
    public let pixieSettings: PixieSettingsStore
    public let limitSettings: LimitSettingsStore
    public let worktreeSettings: WorktreeSettingsStore
    public let notificationRules: NotificationRulesStore
    /// The setup checks and the bug report (B130).
    public let setup: SetupChecksStore
    public let accounts: AccountsStore
    public let extensions: ExtensionsStore
    /// Settings > Configuration (B97).
    public let configuration: ConfigurationStore
    /// Settings > Features (B103).
    public let features: FeaturesStore
    /// Settings > Performance (B115).
    public let performance: PerformanceStore
    /// Computer use (B150).
    public let computer: ComputerStore
    public let terminalAgents: TerminalAgentsStore
    public let shortcuts: ShortcutsStore
    /// Artifacts the chats saved and the Artifacts view (B79).
    public let artifacts: ArtifactsStore
    /// The projects' branch maps (B96).
    public let branchMaps: BranchMapStore
    /// The projects' open GitHub issues (B101).
    public let issues: IssuesStore
    /// The chats' folders' runs (B108).
    public let runs: RunStore
    /// The engine updates (B121).
    public let updates: UpdatesStore
    /// The island around the notch (B114).
    public let island: IslandStore
    public let live: LiveSync
    /// Where `local()` got the device token, to ask again.
    var tokens: (store: any TokenStore, token: DeviceToken)?
    /// The daemon's address and this device's token, for a page the app hosts (D151); nil
    /// for a model without a real daemon, as in samples and snapshots.
    public var pageConnection: (baseURL: URL, token: String)? {
        guard let client = api as? APIClient, let tokens else { return nil }
        return (client.baseURL, tokens.token.current)
    }
    /// The live sync `connect()` started last.
    private var liveTask: Task<Void, Never>?

    /// The daemon this model talks to (B105).
    public let link: DaemonLink
    let now: @Sendable () -> Date

    /// `daemonPreferences` keeps what belongs to this daemon, its tabs and panes, apart
    /// from the app's own look and shortcuts in `preferences`.
    public init(
        api: any NestAPI, events: any EventSource,
        preferences: any KeyValueStore = UserDefaultsStore(),
        daemonPreferences: (any KeyValueStore)? = nil, calendar: Calendar = .current,
        now: @escaping @Sendable () -> Date = { Date() }, link: DaemonLink = DaemonLink()
    ) {
        self.api = api
        self.link = link
        self.now = now
        approvals = ApprovalsStore(api: api)
        app = AppStore(api: api, store: daemonPreferences ?? preferences)
        sessions = SessionsStore(api: api, approvals: approvals)
        activity = ActivityStore(api: api)
        usage = UsageStore(api: api, calendar: calendar, now: now)
        connectors = ConnectorsStore(api: api)
        settings = SettingsStore(store: preferences)
        claudeChats = ClaudeChatsStore(api: api, settings: settings)
        completions = CompletionStore(api: api)
        bash = BashStore(api: api)
        images = AttachmentImages(api: api)
        devices = DevicesStore(api: api, now: now, link: link)
        visibility = VisibilityReporter(api: api, now: now)
        search = MessageSearch(api: api)
        stuck = StuckSettingsStore(api: api)
        agents = AgentsStore(api: api)
        local = LocalModelsStore(api: api, preferences: preferences)
        providers = ProvidersStore(api: api, local: local)
        pixies = PixiesStore(api: api)
        reports = PixieReportsStore(api: api, now: now)
        habits = HabitsStore(api: api)
        chatPixies = ChatPixiesStore(api: api)
        storage = StorageStore(api: api)
        pixieSettings = PixieSettingsStore(api: api)
        limitSettings = LimitSettingsStore(api: api)
        worktreeSettings = WorktreeSettingsStore(api: api)
        notificationRules = NotificationRulesStore(api: api)
        setup = SetupChecksStore(api: api)
        accounts = AccountsStore(api: api)
        extensions = ExtensionsStore(api: api)
        configuration = ConfigurationStore(api: api)
        features = FeaturesStore(api: api, store: preferences)
        performance = PerformanceStore(api: api)
        computer = ComputerStore(api: api)
        terminalAgents = TerminalAgentsStore(api: api)
        shortcuts = ShortcutsStore(store: preferences)
        artifacts = ArtifactsStore(api: api)
        branchMaps = BranchMapStore(api: api, store: daemonPreferences ?? preferences)
        issues = IssuesStore(api: api, store: daemonPreferences ?? preferences)
        runs = RunStore(api: api)
        updates = UpdatesStore(api: api)
        live = LiveSync(
            source: events, app: app, sessions: sessions, approvals: approvals,
            activity: activity, usage: usage, connectors: connectors,
            claudeChats: claudeChats, agents: agents, providers: providers, pixies: pixies,
            reports: reports,
            habits: habits, chatPixies: chatPixies, accounts: accounts, extensions: extensions,
            configuration: configuration, artifacts: artifacts, branchMaps: branchMaps,
            runs: runs, updates: updates)
        island = IslandStore(
            api: api, store: preferences, sessions: sessions, approvals: approvals,
            activity: activity, chatPixies: chatPixies, pixies: pixies, now: now)
        live.island = island
        live.performance = performance
        live.computer = computer
        // A restarted daemon has forgotten that this app is on screen.
        live.onConnected = { [weak self, visibility] in
            visibility.resend()
            Task { await self?.noteConnected() }
        }
    }

    public var isRemote: Bool { link.isRemote }
    /// The remote's machine name, or "This Mac".
    public var machineName: String { link.machineName }
    /// The remote's machine name, nil on This Mac: what a run's port chips say instead of
    /// opening localhost, which is the other machine's (B108).
    public var remoteMachine: String? { link.isRemote ? link.machineName : nil }

    /// A connect to a remote reads its machine name again; This Mac asks nothing.
    func noteConnected() async {
        guard link.isRemote else { return }
        let machine = try? await api.health().machine
        link.seen(machine: machine, at: now())
    }

    /// Restarts the daemon over its API, as the PWA does: for a remote, whose service
    /// this Mac cannot start.
    public func restartDaemon() async throws {
        try await api.restartService()
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

    /// Stops the live sync and tells the daemon the app is no longer on screen, as when the
    /// window switches to another daemon.
    /// A cancelled run says nothing more about the connection (`LiveSync.run`), so closing
    /// says it is over itself.
    public func close() {
        liveTask?.cancel()
        liveTask = nil
        app.connection = .disconnected
        visibility.update(visible: false)
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

    /// The model for a paired daemon on another machine, with the token from its Keychain
    /// item; without one it starts without a token, which the daemon refuses. Its tabs
    /// and panes are kept under its own prefix in the preferences.
    public static func remote(
        _ daemon: RemoteDaemon, tokens: any TokenStore,
        preferences: any KeyValueStore = UserDefaultsStore()
    ) async throws -> AppModel {
        let token = DeviceToken(try await read(tokens) ?? "")
        let model = AppModel(
            api: APIClient(token: token, baseURL: daemon.baseURL),
            events: EventStream(token: token, baseURL: daemon.baseURL), preferences: preferences,
            daemonPreferences: PrefixedStore(preferences, prefix: daemon.preferencesPrefix),
            link: DaemonLink(remote: daemon))
        model.tokens = (tokens, token)
        return model
    }
}
