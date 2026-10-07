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
    let transcripts: Transcripts
    let usage: UsageStore
    let connectors: ConnectorsStore
    let claudeChats: ClaudeChatsStore
    let agents: AgentsStore
    /// Called for each `notify` event, for notification delivery.
    public var onNotice: ((Notice) -> Void)?
    /// Called after each connect has reloaded the stores.
    public var onConnected: (() -> Void)?

    public init(
        source: any EventSource, app: AppStore, sessions: SessionsStore, approvals: ApprovalsStore,
        activity: ActivityStore, transcripts: Transcripts, usage: UsageStore,
        connectors: ConnectorsStore, claudeChats: ClaudeChatsStore, agents: AgentsStore
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
    }

    /// Runs until the task is cancelled or the daemon refuses the connection.
    public func run() async {
        app.connection = .connecting
        do {
            for try await update in source.updates() {
                switch update {
                case .connected:
                    app.connection = .connected
                    await refresh()
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

    /// Reloads repos, sessions, approvals, connectors, usage limits and Claude Code chats,
    /// then the models, agent defaults and account, which never fail the sync.
    public func refresh() async {
        do {
            try await app.loadRepos()
            try await approvals.load()
            try await sessions.load()
            try await connectors.load()
            try await usage.load()
            try await claudeChats.load()
            app.syncError = nil
        } catch {
            app.syncError = error as? APIError ?? .transport(String(describing: error))
        }
        await agents.load()
    }

    public func route(_ event: Event) {
        sessions.apply(event)
        approvals.apply(event)
        activity.apply(event)
        transcripts.receive(event)
        usage.apply(event)
        connectors.apply(event)
        claudeChats.apply(event)
        switch event.body {
        case .sessionDeleted(let id):
            app.forgetChat(id)
        case .notify(let notice):
            onNotice?(notice)
        case .repoUpdated:
            app.reloadRepos()
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
    public let api: any HarnessAPI
    public let app: AppStore
    public let sessions: SessionsStore
    public let approvals: ApprovalsStore
    public let activity: ActivityStore
    public let transcripts: Transcripts
    public let usage: UsageStore
    public let connectors: ConnectorsStore
    public let claudeChats: ClaudeChatsStore
    public let completions: CompletionStore
    public let settings: SettingsStore
    public let devices: DevicesStore
    public let visibility: VisibilityReporter
    public let search: MessageSearch
    public let stuck: StuckSettingsStore
    public let agents: AgentsStore
    public let live: LiveSync

    public init(
        api: any HarnessAPI, events: any EventSource,
        preferences: any KeyValueStore = UserDefaultsStore(), calendar: Calendar = .current,
        now: @escaping @Sendable () -> Date = { Date() }
    ) {
        self.api = api
        approvals = ApprovalsStore(api: api)
        app = AppStore(api: api, approvals: approvals, store: preferences)
        sessions = SessionsStore(api: api, approvals: approvals)
        activity = ActivityStore(api: api)
        transcripts = Transcripts(api: api)
        usage = UsageStore(api: api, calendar: calendar, now: now)
        connectors = ConnectorsStore(api: api)
        settings = SettingsStore(store: preferences)
        claudeChats = ClaudeChatsStore(api: api, settings: settings)
        completions = CompletionStore(api: api)
        devices = DevicesStore(api: api, now: now)
        visibility = VisibilityReporter(api: api, now: now)
        search = MessageSearch(api: api)
        stuck = StuckSettingsStore(api: api)
        agents = AgentsStore(api: api)
        live = LiveSync(
            source: events, app: app, sessions: sessions, approvals: approvals,
            activity: activity, transcripts: transcripts, usage: usage, connectors: connectors,
            claudeChats: claudeChats, agents: agents)
        // A restarted daemon has forgotten that this app is on screen.
        live.onConnected = { [visibility] in visibility.resend() }
    }

    /// The model for the daemon on this Mac, with the device token from the Keychain;
    /// nil when the daemon has not stored a token yet.
    public static func local(
        tokens: any TokenStore = KeychainTokenStore(), baseURL: URL = APIClient.defaultBaseURL
    ) throws -> AppModel? {
        guard let token = try tokens.deviceToken() else { return nil }
        return AppModel(
            api: APIClient(token: token, baseURL: baseURL),
            events: EventStream(token: token, baseURL: baseURL))
    }
}
