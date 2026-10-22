import Foundation
import Synchronization

@testable import NestKit

/// An in-memory daemon: answers from its state, records each call, and fails calls named
/// in `failures`.
final class FakeAPI: NestAPI {
    struct State {
        var calls: [String] = []
        var failures: [String: any Error] = [:]
        /// Fails only the next call of that name.
        var failNext: [String: any Error] = [:]
        var repos = Fixture.repos
        var sessions: [Session] = []
        var details: [String: Session] = [:]
        var events: [String: [Event]] = [:]
        var approvals: [Approval] = []
        var diff = Fixture.diff
        var connectors = Fixture.connectors
        var limits = Fixture.usageLimits
        var usageSettings = UsageSettings(refreshMinutes: 3)
        /// The period answer's split by engine.
        var periodEngines: [EngineTokens] = []
        var devices = Fixture.decode([Device].self, "devices")
        var health = DaemonHealth(status: "ok", version: "0.1.0", machine: "Mac mini")
        var claudeChats = Fixture.claudeChats
        var claudeChatEvents: [String: [Event]] = [:]
        /// Calls named here wait until their stream finishes.
        var gates: [String: AsyncStream<Void>] = [:]
        /// Slash commands by "session:<id>" or "repo:<name>".
        var commands: [String: CommandList] = [:]
        /// File search answers by query.
        var files: [String: [String]] = [:]
        /// What the next send answers as queued, as while a turn runs.
        var queueSends = false
        /// What GitHub answers when a session's pull request is read, by session id.
        var githubPRs: [String: PullRequest] = [:]
        /// Each repo's open issues (B101); a repo without any lists none. Mine answers
        /// `mineIssues`, else none assigned.
        var issues: [String: IssueList] = [:]
        var mineIssues: [String: IssueList] = [:]
        /// Search answers by query.
        var searches: [String: SearchResults] = [:]
        var stuckSettings = StuckSettings(
            waitingMinutes: 15, silentMinutes: 10, repeatedCalls: 4, turnMinutes: 60)
        var models = Fixture.models
        var defaultModel: String? = "opus"
        /// `GET /api/providers`; none, as from a daemon before B91, until set.
        var providers: [ProviderInfo] = []
        /// The other engines' model lists, by engine name.
        var providerModels: [String: [ModelInfo]] = [:]
        /// The other engines' default models, by engine name.
        var providerDefaults: [String: String] = [:]
        var account = ClaudeAccount(
            displayName: "Giorgos", email: "me@example.com", plan: "Claude Max",
            organization: nil)
        var pixies: [Pixie] = []
        var teams: [PixieTeam] = []
        /// What a pixie file save answers with a `staleFile` error, when set.
        var staleFile: PixieFile?
        /// Pixie files by name.
        var pixieFiles: [String: PixieFile] = [:]
        var pixieNotes: [String] = []
        var pixieHits: [PixieSearchHit] = []
        var pixieActivity: [PixieActivityEntry] = []
        /// Habits by pixie id, and their runs by habit id (B42).
        var habits: [String: [PixieHabit]] = [:]
        var habitRuns: [String: [HabitRun]] = [:]
        var reports: [PixieReport] = []
        /// Models without Auto: a pixie in Auto moved to one drops to Ask before edits.
        var dropsAutoFor: Set<String> = []
        var agentDefaults = AgentDefaults(
            model: "opus", effort: .xhigh, permissionMode: .default, mode: .inPlace)
        /// What a rewind preview answers, by session id.
        var rewinds: [String: RewindPreview] = [:]
        /// Gitignored files a repo suggests linking, by repo name.
        var linkSuggestions: [String: [String]] = [:]
        /// Each chat's pixies, by session id (B46).
        var pixieGroups: [String: [ChatPixieEntry]] = [:]
        /// What Send away answers.
        var sendAwayAnswer: [ChatPixieEntry] = []
        /// Subagents' transcripts by "<session>/<tool use id>"; others are not found.
        var transcripts: [String: AgentWork] = [:]
        /// A pixie's calls in a chat by "<session>/<pixie id>".
        var pixieCallWork: [String: [PixieCallWork]] = [:]
        /// What each project's chats are working towards, by repo name (B47).
        var goals: [String: [SessionGoals]] = [:]
        // Settings (B81)
        var pushDevices = 1
        var branches: [String: [String]] = [:]
        /// Each repo's branch map (B96); a repo without one is not found.
        var branchMaps: [String: BranchMap] = [:]
        var storage = StorageUsage(
            totalBytes: 1_400, chatsBytes: 800, attachmentsBytes: 500, artifactsBytes: 40,
            otherBytes: 60)
        var storageSettings = StorageSettings()
        var largeAttachments: [LargeAttachment] = []
        var pixieSettings = PixieSettings()
        var notificationRules = NotificationRules()
        var pixieSkills: [PixieSkillChoice] = []
        var github = GitHubAccount(
            state: .signedIn, login: "octo", checkedAt: Date(timeIntervalSince1970: 0))
        /// Every engine's accounts (B98), what a refresh answers, and the page a sign-in
        /// answers with.
        var accounts: [EngineAccount] = []
        var refreshedAccounts: [EngineAccount]?
        var signInURL: URL?
        /// Each Codex account's banked resets with details, and what using one answers.
        var banked: [String: BankedResets] = [:]
        var useOutcome = BankedResetOutcome.reset
        var claudeCode = ClaudeCodeStatus(
            installed: false, path: nil, version: nil, bundledVersion: "2.1.0")
        var plugins = [InstalledPlugin(id: "pdf@official", name: "pdf", marketplace: "official")]
        var skills = [StandaloneSkill(name: "notes", path: "/s/notes")]
        var marketplaces = [PluginMarketplace(name: "official", kind: "github", source: "a/b")]
        var available = [
            AvailablePlugin(
                id: "pdf@official", name: "pdf", marketplace: "official", source: "official",
                installed: true),
            AvailablePlugin(
                id: "lint@official", name: "lint", marketplace: "official", source: "x"),
        ]
        /// Artifacts newest first, and their versions' content by "<id>/<version>" (B79).
        var artifacts: [Artifact] = []
        var artifactContents: [String: ArtifactContent] = [:]
        var unseenArtifacts = 0
        /// What each artifact's page stored, by artifact id (B88).
        var artifactStorage: [String: ArtifactStorage] = [:]
        var askAnswer = ArtifactAnswer(text: "", remaining: 19, limit: 20)
        var askStatus = ArtifactAskStatus(
            used: 0, limit: 20, remaining: 20, resetsAt: nil, enabled: true)
        // Configuration (B97)
        var configuration = Fixture.configurationPage
        /// Configuration files by path; others read as missing.
        var configFiles: [String: ConfigFile] = [:]
        var mcpServers: [String: MCPServerSpec] = [:]
        var copyPreview = Fixture.copyPreview
        var repoConfigurations: [String: RepoConfiguration] = [:]
        var codexPlugins: [CodexPlugin] = []
        var codexMarketplaces: [CodexMarketplace] = []
    }

    let state = Mutex(State())

    var calls: [String] { state.withLock { $0.calls } }

    func set(_ change: (inout State) -> Void) {
        state.withLock { change(&$0) }
    }

    func fail(_ call: String, with error: any Error = APIError.server(status: 500, detail: "boom"))
    {
        state.withLock { $0.failures[call] = error }
    }

    private func pass(_ gate: String) async {
        if let stream = state.withLock({ $0.gates[gate] }) {
            for await _ in stream {}
        }
    }

    private func call<T>(_ name: String, _ detail: String = "", _ answer: (inout State) -> T) throws
        -> T
    {
        try state.withLock { state in
            state.calls.append(detail.isEmpty ? name : "\(name) \(detail)")
            if let failure = state.failures[name] ?? state.failNext.removeValue(forKey: name) {
                throw failure
            }
            return answer(&state)
        }
    }

    private func session(_ id: String, in state: inout State, change: (inout Session) -> Void)
        -> Session
    {
        let index = state.sessions.firstIndex { $0.id == id }!
        change(&state.sessions[index])
        return state.sessions[index]
    }

    func repos() async throws -> [Repo] {
        try call("repos") { $0.repos }
    }

    func registerRepo(path: String, name: String?) async throws -> Repo {
        try call("registerRepo", path) { state in
            var repo = state.repos[0]
            repo.name = name ?? URL(fileURLWithPath: path).lastPathComponent
            repo.path = path
            state.repos.append(repo)
            return repo
        }
    }

    func openRepo(_ name: String, in app: RepoApp) async throws {
        try call("openRepo", "\(name) \(app.rawValue)") { _ in }
    }

    func removeRepo(_ name: String, purgeSessions: Bool) async throws {
        try call("removeRepo", "\(name) purge=\(purgeSessions)") { state in
            state.repos.removeAll { $0.name == name }
        }
    }

    func updateRepo(_ name: String, _ patch: RepoPatch) async throws -> Repo {
        await pass("updateRepo")
        return try call("updateRepo", "\(name) \(Fixture.json(patch))") { state in
            let index = state.repos.firstIndex { $0.name == name }!
            if patch.changesDefault {
                state.repos[index].worktree.isDefault = patch.isDefault
            }
            state.repos[index].worktree.link = patch.link ?? state.repos[index].worktree.link
            state.repos[index].worktree.setup = patch.setup ?? state.repos[index].worktree.setup
            if patch.changesIcon {
                state.repos[index].icon = patch.icon
            }
            if patch.changesIconColor {
                state.repos[index].iconColor = patch.iconColor
            }
            if let branch = patch.defaultBranch {
                state.repos[index].defaultBranch = branch
            }
            if patch.changesRemoteURL {
                state.repos[index].remoteURL = patch.remoteURL
            }
            if let seconds = patch.setupTimeoutSeconds {
                state.repos[index].worktree.setupTimeoutSeconds = seconds
            }
            return state.repos[index]
        }
    }

    func linkSuggestions(_ name: String) async throws -> [String] {
        try call("linkSuggestions", name) { $0.linkSuggestions[name] ?? [] }
    }

    /// Sorts the repos as the daemon does: named ones first, the rest after in order.
    func reorderRepos(_ order: [String]) async throws -> [Repo] {
        await pass("reorderRepos")
        return try call("reorderRepos", order.joined(separator: ",")) { state in
            let rank = { (repo: Repo) in order.firstIndex(of: repo.name) ?? order.count }
            state.repos = state.repos.enumerated()
                .sorted { (rank($0.element), $0.offset) < (rank($1.element), $1.offset) }
                .map(\.element)
            return state.repos
        }
    }

    /// Both wait at the "sessions" gate, after reading what they answer.
    func sessions(repo: String?, archived: Bool) async throws -> [Session] {
        let answer = try call("sessions", "archived=\(archived)") { state in
            state.sessions.filter { $0.isArchived == archived && (repo == nil || $0.repo == repo) }
        }
        await pass("sessions")
        return answer
    }

    func session(_ id: String) async throws -> Session {
        let answer = try call("session", id) { state in
            state.details[id] ?? state.sessions.first { $0.id == id }!
        }
        await pass("session")
        return answer
    }

    /// Answers what the daemon read before the gate opens, as a slow read does.
    func goals(repo: String) async throws -> [SessionGoals] {
        let answer = try call("goals", repo) { $0.goals[repo] ?? [] }
        await pass("goals")
        return answer
    }

    func createSession(_ request: CreateSessionRequest) async throws -> Session {
        try call("createSession", request.prompt) { state in
            var session = Fixture.session(
                "new-\(state.sessions.count)", repo: request.repo, state: .starting)
            session.prompt = request.prompt
            session.model = request.model
            session.effort = request.effort
            session.permissionMode = request.permissionMode ?? .default
            session.provider = request.provider ?? "claude"
            state.sessions.append(session)
            return session
        }
    }

    func updateSession(_ id: String, _ request: UpdateSessionRequest) async throws -> Session {
        try call("updateSession", id) { state in
            session(id, in: &state) { session in
                session.title = request.title ?? session.title
                session.pinned = request.pinned ?? session.pinned
                session.model = request.model ?? session.model
                session.effort = request.effort ?? session.effort
                session.permissionMode = request.permissionMode ?? session.permissionMode
                if let archived = request.archived {
                    session.archivedAt = archived ? Date(timeIntervalSince1970: 5_000) : nil
                }
            }
        }
    }

    func deleteSession(_ id: String) async throws {
        try call("deleteSession", id) { state in state.sessions.removeAll { $0.id == id } }
    }

    func sessionEvents(_ id: String, after: Int, before: Int?, limit: Int?) async throws
        -> [Event]
    {
        let detail =
            "\(id) after=\(after)" + (before.map { " before=\($0)" } ?? "")
            + (limit.map { " limit=\($0)" } ?? "")
        // Read before the gate, as the daemon answers from what it stored by then.
        let answer = try call("sessionEvents", detail) { state in
            let range = (state.events[id] ?? []).filter {
                ($0.id ?? 0) > after && ($0.id ?? 0) < (before ?? .max)
            }
            guard let limit else { return range }
            return before == nil ? Array(range.prefix(limit)) : Array(range.suffix(limit))
        }
        await pass("sessionEvents")
        return answer
    }

    func sendMessage(_ id: String, text: String, attachmentIDs: [String], interrupt: Bool)
        async throws -> SentMessage
    {
        let detail = "\(id) \(text) \(attachmentIDs)" + (interrupt ? " interrupt" : "")
        return try call("sendMessage", detail) { state in
            let queued =
                state.queueSends
                ? QueuedMessage(
                    id: "q-\(text)", text: text, createdAt: Date(timeIntervalSince1970: 0))
                : nil
            return SentMessage(
                session: session(id, in: &state) { $0.state = .running }, queuedMessage: queued)
        }
    }

    func cancelQueued(_ id: String, queuedID: String) async throws {
        try call("cancelQueued", "\(id) \(queuedID)") { _ in }
    }

    func runShell(_ id: String, command: String) async throws -> ShellRun {
        await pass("runShell")
        return try call("runShell", "\(id) \(command)") { _ in
            ShellRun(
                command: command, exitCode: 0, output: "output of \(command)", truncated: false,
                timedOut: false, context: "context of \(command)")
        }
    }

    func saveMemory(_ id: String, text: String, scope: MemoryScope) async throws -> SavedMemory {
        try call("saveMemory", "\(id) \(scope.rawValue) \(text)") { _ in
            SavedMemory(path: "/\(scope.rawValue)/CLAUDE.md", scope: scope, line: "- \(text)")
        }
    }

    func attachmentData(_ id: String) async throws -> Data {
        try call("attachmentData", id) { _ in Data("image \(id)".utf8) }
    }

    func sendQueuedNow(_ id: String, queuedID: String) async throws {
        try call("sendQueuedNow", "\(id) \(queuedID)") { _ in }
    }

    func sessionCommands(_ id: String) async throws -> CommandList {
        try call("sessionCommands", id) { state in
            state.commands["session:\(id)"] ?? CommandList(source: .none, commands: [])
        }
    }

    func repoCommands(_ repo: String) async throws -> CommandList {
        try call("repoCommands", repo) { state in
            state.commands["repo:\(repo)"] ?? CommandList(source: .none, commands: [])
        }
    }

    func sessionFiles(_ id: String, query: String) async throws -> [String] {
        await pass("sessionFiles \(query)")
        return try call("sessionFiles", "\(id) \(query)") { $0.files[query] ?? [] }
    }

    func interrupt(_ id: String) async throws {
        try call("interrupt", id) { _ in }
    }

    /// Ends the pause, after the gate named "resumeLimit" opens when one is set.
    func resumeLimit(_ id: String) async throws -> Session {
        let answer = try call("resumeLimit", id) { state in
            session(id, in: &state) { $0.limitPause = nil }
        }
        await pass("resumeLimit")
        return answer
    }

    func stopTask(_ id: String, task: String) async throws {
        try call("stopTask", "\(id) \(task)") { _ in }
    }

    func rewindPreview(_ id: String, message: Int, restore: RewindRestore) async throws
        -> RewindPreview
    {
        try call("rewindPreview", "\(id) \(message) \(restore.rawValue)") { state in
            state.rewinds["\(id) \(restore.rawValue)"] ?? RewindPreview(canRewind: true)
        }
    }

    /// A conversation rewind answers "message <id>" for the composer.
    func rewind(_ id: String, message: Int, restore: RewindRestore) async throws
        -> RewindPreview
    {
        await pass("rewind")
        return try call("rewind", "\(id) \(message) \(restore.rawValue)") { _ in
            RewindPreview(
                canRewind: true, restore: restore,
                text: restore == .code ? nil : "message \(message)")
        }
    }

    func fork(_ id: String, message: Int) async throws -> ForkedChat {
        try call("fork", "\(id) \(message)") { state in
            let original = state.sessions.first { $0.id == id }!
            var session = Fixture.session(
                "fork-\(state.sessions.count)", repo: original.repo,
                title: "\(original.title) (fork)")
            session.mode = original.mode
            state.sessions.append(session)
            return ForkedChat(
                session: session,
                message: RestoredMessage(text: "message \(message)", attachments: []))
        }
    }

    func ciFeedback(_ id: String) async throws {
        try call("ciFeedback", id) { _ in }
    }

    func issues(repo: String, refresh: Bool, show: IssueShow?) async throws -> IssueList {
        let detail =
            repo + (show.map { " show=\($0.rawValue)" } ?? "") + (refresh ? " refresh" : "")
        return try call("issues", detail) { state in
            if show == .mine {
                return state.mineIssues[repo]
                    ?? IssueList(available: true, show: .mine, issues: [])
            }
            return state.issues[repo] ?? IssueList(available: false, show: .all, issues: [])
        }
    }

    func reviewFeedback(_ id: String, ids: [String]?) async throws {
        try call("reviewFeedback", ids.map { "\(id) \($0.joined(separator: ","))" } ?? id) { _ in }
        await pass("reviewFeedback")
    }

    func setReviewAutoSend(_ id: String, _ on: Bool) async throws -> Session {
        try call("setReviewAutoSend", "\(id) \(on)") { state in
            session(id, in: &state) { $0.review?.autoSend = on }
        }
    }

    func openInClaudeCode(_ id: String) async throws -> ClaudeCodeLaunch {
        try call("openInClaudeCode", id) { _ in
            ClaudeCodeLaunch(launcher: "/tmp/\(id).command", warning: nil)
        }
    }

    func claudeChats(repo: String?, includeAutomated: Bool) async throws -> [ClaudeChat] {
        let detail = "\(repo ?? "all") automated=\(includeAutomated)"
        return try call("claudeChats", detail) { state in
            state.claudeChats.filter {
                (repo == nil || $0.repo == repo) && (includeAutomated || !$0.automated)
            }
        }
    }

    func claudeChat(_ id: String) async throws -> ClaudeChat {
        try call("claudeChat", id) { state in state.claudeChats.first { $0.id == id }! }
    }

    func claudeChatEvents(_ id: String) async throws -> [Event] {
        try call("claudeChatEvents", id) { $0.claudeChatEvents[id] ?? [] }
    }

    /// Waits at its gate before it answers, so a failure can follow a refresh.
    func setClaudeChatArchived(_ id: String, archived: Bool) async throws -> ClaudeChat {
        state.withLock { $0.calls.append("setClaudeChatArchived \(id) \(archived)") }
        await pass("setClaudeChatArchived")
        return try state.withLock { state in
            if let failure = state.failures["setClaudeChatArchived"] {
                throw failure
            }
            guard let index = state.claudeChats.firstIndex(where: { $0.id == id }) else {
                throw APIError.notFound("No Claude Code chat \(id)")
            }
            state.claudeChats[index].archived = archived
            return state.claudeChats[index]
        }
    }

    func adoptClaudeChat(_ id: String) async throws -> Session {
        try call("adoptClaudeChat", id) { state in
            let chat = state.claudeChats.first { $0.id == id }!
            var session = Fixture.session("adopted-\(id)", repo: chat.repo, title: chat.title)
            session.providerSessionID = id
            session.mode = .inPlace
            state.claudeChats.removeAll { $0.id == id }
            state.sessions.append(session)
            return session
        }
    }

    func diff(_ sessionID: String) async throws -> SessionDiff {
        await pass("diff")
        return try call("diff", sessionID) { $0.diff }
    }

    func approve(_ sessionID: String, _ request: ApproveRequest) async throws -> Session {
        let files = request.files.map { " files=\($0)" } ?? ""
        let head = request.expectedHead.map { " head=\($0)" } ?? ""
        let fingerprint = request.expectedFingerprint.map { " fingerprint=\($0)" } ?? ""
        let remote = request.confirmRemoteURL.map { " remote=\($0)" } ?? ""
        let detail =
            "\(sessionID) \(request.commitMessage) open_pr=\(request.openPR)\(files)\(head)"
            + fingerprint + remote
        await pass("approve")
        return try call("approve", detail) { state in
            session(sessionID, in: &state) { $0.prURL = "https://example.com/pr/1" }
        }
    }

    func feedback(_ sessionID: String, text: String) async throws -> Session {
        try call("feedback", "\(sessionID) \(text)") { state in
            session(sessionID, in: &state) { $0.state = .running }
        }
    }

    func merge(_ sessionID: String, _ request: MergeRequest) async throws -> Session {
        let deleting = request.deleteBranch ? " delete-branch" : ""
        return try call("merge", "\(sessionID) \(request.method.rawValue)\(deleting)") { state in
            session(sessionID, in: &state) {
                $0.state = .closed
                $0.pr?.state = .merged
            }
        }
    }

    func refreshPR(_ sessionID: String) async throws -> Session {
        try call("refreshPR", sessionID) { state in
            let pr = state.githubPRs[sessionID]
            return session(sessionID, in: &state) { $0.pr = pr }
        }
    }

    func search(query: String, repo: String?, limit: Int) async throws -> SearchResults {
        await pass("search \(query)")
        return try call("search", "\(query) \(repo ?? "all") \(limit)") { state in
            state.searches[query] ?? SearchResults(hits: [], indexing: false)
        }
    }

    func approvals(status: ApprovalStatus?, project: String?) async throws -> [Approval] {
        let answer = try call("approvals") { state in
            state.approvals.filter { status == nil || $0.status == status }
        }
        await pass("approvals")
        return answer
    }

    func resolveApproval(_ id: String, _ request: ResolveApprovalRequest) async throws -> Approval {
        try call("resolveApproval", "\(id) \(Fixture.json(request))") { state in
            let index = state.approvals.firstIndex { $0.id == id }!
            state.approvals[index].status = .resolved
            return state.approvals[index]
        }
    }

    func uploadAttachment(filename: String, mediaType: String, data: Data) async throws
        -> Attachment
    {
        try call("uploadAttachment", filename) { _ in
            Attachment(
                id: "att", filename: filename, mediaType: mediaType, size: data.count,
                createdAt: nil)
        }
    }

    func connectors() async throws -> [Connector] {
        try call("connectors") { $0.connectors }
    }

    /// The fixture's numbers for any period, starting on the day asked for.
    func usagePeriod(unit: UsageUnit, date: CalendarDay) async throws -> UsagePeriod {
        await pass("usagePeriod")
        return try call("usagePeriod", "\(unit.rawValue) \(date.description)") { state in
            var period = Fixture.usagePeriod
            period.unit = unit
            period.start = date
            period.engines = state.periodEngines
            return period
        }
    }

    func usageLimits() async throws -> UsageLimits {
        try call("usageLimits") { $0.limits }
    }

    func usageSettings() async throws -> UsageSettings {
        try call("usageSettings") { $0.usageSettings }
    }

    func updateUsageSettings(_ settings: UsageSettings) async throws -> UsageSettings {
        try call("updateUsageSettings", "\(settings.refreshMinutes)") { state in
            state.usageSettings = settings
            return settings
        }
    }

    func stuckSettings() async throws -> StuckSettings {
        try call("stuckSettings") { $0.stuckSettings }
    }

    func updateStuckSettings(_ settings: StuckSettings) async throws -> StuckSettings {
        try call("updateStuckSettings", "\(settings.repeatedCalls)") { state in
            state.stuckSettings = settings
            return settings
        }
    }

    func reportVisibility(_ visible: Bool, client: String) async throws {
        await pass("reportVisibility")
        try call("reportVisibility", "\(visible) \(client)") { _ in }
    }

    func models() async throws -> ModelList {
        try call("models") { ModelList(models: $0.models, defaultModel: $0.defaultModel) }
    }

    func models(provider: String) async throws -> ModelList {
        try call("modelsFor", provider) {
            ModelList(
                models: $0.providerModels[provider] ?? [],
                defaultModel: $0.providerDefaults[provider])
        }
    }

    func providers(refresh: Bool) async throws -> ProviderList {
        try call("providers", "\(refresh)") { ProviderList(providers: $0.providers) }
    }

    func account() async throws -> ClaudeAccount {
        try call("account") { $0.account }
    }

    func agentDefaults() async throws -> AgentDefaults {
        try call("agentDefaults") { $0.agentDefaults }
    }

    func updateAgentDefaults(_ defaults: AgentDefaults) async throws -> AgentDefaults {
        let detail = [
            defaults.provider, defaults.model ?? "nil", defaults.effort?.rawValue ?? "nil",
            defaults.permissionMode.rawValue, defaults.mode.rawValue,
        ].joined(separator: " ")
        return try call("updateAgentDefaults", detail) { state in
            state.agentDefaults = defaults
            return defaults
        }
    }

    func pixies() async throws -> [Pixie] {
        try call("pixies") { $0.pixies }
    }

    func pixieSkills() async throws -> [PixieSkillChoice] {
        try call("pixieSkills") { $0.pixieSkills }
    }

    func createPixie(_ request: CreatePixieRequest) async throws -> Pixie {
        try call("createPixie", request.name) { state in
            var pixie = Fixture.decode(Pixie.self, "pixie")
            pixie.id = "new-\(state.pixies.count)"
            pixie.name = request.name
            pixie.hidden = request.hidden ?? false
            state.pixies.append(pixie)
            return pixie
        }
    }

    /// Waits at the "updatePixie" gate after taking the change, as the daemon answers.
    func updatePixie(_ id: String, _ request: UpdatePixieRequest) async throws -> Pixie {
        let answer = try call("updatePixie", id) { state in
            let index = state.pixies.firstIndex { $0.id == id }!
            var pixie = state.pixies[index].applying(request)
            if pixie.permissionMode == .auto, let model = pixie.model,
                state.dropsAutoFor.contains(model)
            {
                pixie.permissionMode = .default
            }
            state.pixies[index] = pixie
            return pixie
        }
        await pass("updatePixie")
        return answer
    }

    /// Waits at the "reorderPixies" gate first, so a refusal can be set while it waits.
    func reorderPixies(_ ids: [String]) async throws -> [Pixie] {
        await pass("reorderPixies")
        return try call("reorderPixies", ids.joined(separator: ",")) { state in
            let byID = Dictionary(uniqueKeysWithValues: state.pixies.map { ($0.id, $0) })
            state.pixies = ids.enumerated().map { index, id in
                var pixie = byID[id]!
                pixie.position = index
                return pixie
            }
            return state.pixies
        }
    }

    func deletePixie(_ id: String) async throws {
        try call("deletePixie", id) { state in state.pixies.removeAll { $0.id == id } }
    }

    func sendToPixie(_ id: String, text: String) async throws -> SentMessage {
        try call("sendToPixie", id) { state in
            var session = Fixture.session("chat-\(id)", repo: "pixie:\(id)", state: .running)
            session.pixieID = id
            let queued =
                state.queueSends
                ? QueuedMessage(
                    id: "q-\(text)", text: text, createdAt: Date(timeIntervalSince1970: 0))
                : nil
            return SentMessage(session: session, queuedMessage: queued)
        }
    }

    func resetPixie(_ id: String) async throws -> Pixie {
        try call("resetPixie", id) { state in state.pixies.first { $0.id == id }! }
    }

    func pixieFile(_ id: String, name: String) async throws -> PixieFile {
        try call("pixieFile", "\(id) \(name)") { state in
            state.pixieFiles[name] ?? PixieFile(text: "", hash: "empty")
        }
    }

    func savePixieFile(_ id: String, name: String, text: String, hash: String?) async throws
        -> PixieFile
    {
        let stale = try call("savePixieFile", "\(id) \(name)") { $0.staleFile }
        if let stale {
            throw APIError.staleFile(text: stale.text, hash: stale.hash)
        }
        return state.withLock { state in
            let saved = PixieFile(text: text, hash: "hash-of-\(text)")
            state.pixieFiles[name] = saved
            return saved
        }
    }

    func pixieNotes(_ id: String) async throws -> [String] {
        try call("pixieNotes", id) { $0.pixieNotes }
    }

    func searchPixie(_ id: String, query: String) async throws -> [PixieSearchHit] {
        try call("searchPixie", "\(id) \(query)") { $0.pixieHits }
    }

    func pixieActivity(_ id: String) async throws -> [PixieActivityEntry] {
        try call("pixieActivity", id) { $0.pixieActivity }
    }

    func pixieHabits(_ id: String) async throws -> [PixieHabit] {
        try call("pixieHabits", id) { $0.habits[id] ?? [] }
    }

    func createHabit(_ pixie: String, _ request: CreateHabitRequest) async throws -> PixieHabit {
        try call("createHabit", "\(pixie) \(request.name)") { state in
            var habit = Fixture.decode(
                PixieHabit.self, json: PixieHabitsTests.habitJSON(pixie: pixie))
            habit.id = "h-new-\(state.habits[pixie, default: []].count)"
            habit.name = request.name
            habit.prompt = request.prompt
            habit.schedule = request.schedule
            habit.triggers = request.triggers
            habit.maxMinutes = request.maxMinutes
            habit.enabled = request.enabled
            habit.createdAt = habit.createdAt.addingTimeInterval(60)
            state.habits[pixie, default: []].append(habit)
            return habit
        }
    }

    func updateHabit(_ pixie: String, _ habit: String, _ request: UpdateHabitRequest)
        async throws -> PixieHabit
    {
        try call("updateHabit", "\(pixie) \(habit)") { state in
            let index = state.habits[pixie]!.firstIndex { $0.id == habit }!
            var changed = state.habits[pixie]![index]
            changed.name = request.name ?? changed.name
            changed.prompt = request.prompt ?? changed.prompt
            changed.schedule = request.clearsSchedule ? nil : request.schedule ?? changed.schedule
            changed.triggers = request.triggers ?? changed.triggers
            changed.maxMinutes = request.maxMinutes ?? changed.maxMinutes
            changed.enabled = request.enabled ?? changed.enabled
            changed.updatedAt = changed.updatedAt.addingTimeInterval(1)
            state.habits[pixie]![index] = changed
            return changed
        }
    }

    func deleteHabit(_ pixie: String, _ habit: String) async throws {
        try call("deleteHabit", "\(pixie) \(habit)") { state in
            state.habits[pixie]?.removeAll { $0.id == habit }
        }
    }

    func runHabit(_ pixie: String, _ habit: String) async throws -> HabitRun {
        try call("runHabit", "\(pixie) \(habit)") { state in
            var run = Fixture.decode(
                HabitRun.self,
                json: PixieHabitsTests.runJSON(
                    habit: habit, outcome: "queued", started: "null", ended: "null",
                    title: "null"))
            run.id = "run-\(state.habitRuns[habit, default: []].count)"
            state.habitRuns[habit, default: []].insert(run, at: 0)
            return run
        }
    }

    func habitRuns(_ pixie: String, _ habit: String) async throws -> [HabitRun] {
        try call("habitRuns", "\(pixie) \(habit)") { $0.habitRuns[habit] ?? [] }
    }

    func pixieReports(unread: Bool) async throws -> [PixieReport] {
        try call("pixieReports", "unread=\(unread)") { state in
            unread ? state.reports.filter { $0.readAt == nil } : state.reports
        }
    }

    func markReportRead(_ id: String) async throws {
        try call("markReportRead", id) { _ in }
    }

    func markPixieReportsRead(_ id: String) async throws {
        try call("markPixieReportsRead", id) { _ in }
    }

    /// A copy right after the original, as the daemon makes it; later pixies move down.
    func duplicatePixie(_ id: String) async throws -> Pixie {
        try call("duplicatePixie", id) { state in
            let index = state.pixies.firstIndex { $0.id == id }!
            var copy = state.pixies[index]
            copy.id = "\(id)-copy"
            copy.slug = "\(copy.slug)-2"
            copy.name = "\(copy.name) 2"
            copy.position = copy.position + 1
            copy.updatedAt = Date(timeIntervalSince1970: 2_000_000_000)
            for later in state.pixies.indices where state.pixies[later].position >= copy.position {
                state.pixies[later].position += 1
            }
            state.pixies.insert(copy, at: index + 1)
            return copy
        }
    }

    func pixieTeams() async throws -> [PixieTeam] {
        try call("pixieTeams") { $0.teams }
    }

    func createPixieTeam(_ request: CreatePixieTeamRequest) async throws -> PixieTeam {
        try call("createPixieTeam", request.name) { state in
            var team = Fixture.decode(PixieTeam.self, "pixie_team")
            team.id = "team-\(state.teams.count)"
            team.name = request.name
            team.handle = request.handle ?? request.name.lowercased()
            team.leaderID = nil
            team.position = state.teams.count
            state.teams.append(team)
            return team
        }
    }

    /// Refuses a leader that is not a member, as the daemon does.
    func updatePixieTeam(_ id: String, _ request: UpdatePixieTeamRequest) async throws
        -> PixieTeam
    {
        let answer: Result<PixieTeam, APIError> = try call("updatePixieTeam", id) { state in
            let index = state.teams.firstIndex { $0.id == id }!
            if let leader = request.leaderID,
                !state.pixies.contains(where: { $0.id == leader && $0.teamID == id })
            {
                return .failure(.conflict("leader_not_member"))
            }
            var team = state.teams[index]
            team.name = request.name ?? team.name
            team.handle = request.handle ?? team.handle
            team.leaderID = request.leaderID ?? team.leaderID
            team.updatedAt = team.updatedAt.addingTimeInterval(1)
            state.teams[index] = team
            return .success(team)
        }
        return try answer.get()
    }

    func deletePixieTeam(_ id: String) async throws {
        try call("deletePixieTeam", id) { state in
            state.teams.removeAll { $0.id == id }
            for index in state.pixies.indices where state.pixies[index].teamID == id {
                state.pixies[index].teamID = nil
            }
        }
    }

    /// Answers what the daemon read before the gate opens, as a slow read does.
    func pixieGroups() async throws -> [String: [ChatPixieEntry]] {
        let groups = try call("pixieGroups") { $0.pixieGroups }
        await pass("pixieGroups")
        return groups
    }

    func chatPixies(_ id: String) async throws -> [ChatPixieEntry] {
        try call("chatPixies", id) { $0.pixieGroups[id] ?? [] }
    }

    func sendAway(_ id: String, _ request: SendAwayRequest) async throws -> [ChatPixieEntry] {
        let named = request.teamID.map { "team=\($0)" } ?? "pixie=\(request.pixieID ?? "")"
        return try call("sendAway", "\(id) \(named)") { $0.sendAwayAnswer }
    }

    func pixieCallWork(_ id: String, pixie: String) async throws -> [PixieCallWork] {
        try call("pixieCallWork", "\(id) \(pixie)") { $0.pixieCallWork["\(id)/\(pixie)"] ?? [] }
    }

    func agentTranscript(_ id: String, toolUseID: String) async throws -> AgentWork {
        let work = try call("agentTranscript", "\(id) \(toolUseID)") {
            $0.transcripts["\(id)/\(toolUseID)"]
        }
        guard let work else { throw APIError.notFound("not found") }
        return work
    }

    func artifacts(repo: String?, sessionID: String?, pixieID: String?) async throws
        -> [Artifact]
    {
        let filters = [("repo", repo), ("session", sessionID), ("pixie", pixieID)]
            .compactMap { name, value in value.map { "\(name)=\($0)" } }
            .joined(separator: " ")
        await pass("artifacts")
        return try call("artifacts", filters) { state in
            state.artifacts.filter { artifact in
                (repo.map { $0 == artifact.repo } ?? true)
                    && (sessionID.map { $0 == artifact.sessionID } ?? true)
                    && (pixieID.map { $0 == artifact.pixieID } ?? true)
            }
        }
    }

    func unseenArtifacts() async throws -> Int {
        try call("unseenArtifacts") { $0.unseenArtifacts }
    }

    func artifact(_ id: String) async throws -> ArtifactDetail {
        let found = try call("artifact", id) { state in
            state.artifacts.first { $0.id == id }
        }
        await pass("artifact")
        guard let found else { throw APIError.notFound("artifact not found") }
        return Fixture.detail(found)
    }

    func artifactContent(_ id: String, version: Int) async throws -> ArtifactContent {
        let content = try call("artifactContent", "\(id)/\(version)") {
            $0.artifactContents["\(id)/\(version)"]
        }
        guard let content else { throw APIError.notFound("version not found") }
        return content
    }

    func markArtifactSeen(_ id: String) async throws -> Artifact {
        try call("markArtifactSeen", id) { state in
            let index = state.artifacts.firstIndex { $0.id == id }!
            state.artifacts[index].seen = true
            return state.artifacts[index]
        }
    }

    /// A user's save: the next version, titled "Edited", once the artifact is known.
    func saveArtifactVersion(_ id: String, content: String, baseVersion: Int) async throws
        -> ArtifactVersion
    {
        try call("saveArtifactVersion", "\(id) base=\(baseVersion) \(content)") { state in
            let index = state.artifacts.firstIndex { $0.id == id }!
            state.artifacts[index].latestVersion += 1
            return ArtifactVersion(
                version: state.artifacts[index].latestVersion, title: "Edited",
                size: content.utf8.count, createdAt: Fixture.date("2026-10-17T10:00:00Z"),
                author: .user)
        }
    }

    func artifactStorage(_ id: String) async throws -> ArtifactStorage {
        try call("artifactStorage", id) {
            $0.artifactStorage[id] ?? ArtifactStorage(items: [:], size: 0)
        }
    }

    /// Applies the change; the size counts each key's and value's UTF-8 bytes.
    func writeArtifactStorage(_ id: String, set: [String: String], remove: [String])
        async throws -> Int
    {
        let detail =
            "\(id) set=\(set.keys.sorted().joined(separator: ",")) remove=\(remove.joined(separator: ","))"
        return try call("writeArtifactStorage", detail) { state in
            var items = state.artifactStorage[id]?.items ?? [:]
            items.merge(set) { $1 }
            for key in remove {
                items[key] = nil
            }
            let size = items.reduce(0) { $0 + $1.key.utf8.count + $1.value.utf8.count }
            state.artifactStorage[id] = ArtifactStorage(items: items, size: size)
            return size
        }
    }

    func askArtifact(_ id: String, prompt: String, system: String?) async throws
        -> ArtifactAnswer
    {
        // A refusal answers at once; an answer may wait at the gate.
        let answer = try call("askArtifact", "\(id) \(prompt) system=\(system ?? "")") {
            $0.askAnswer
        }
        await pass("askArtifact")
        return answer
    }

    func askStatus(_ id: String) async throws -> ArtifactAskStatus {
        try call("askStatus", id) { $0.askStatus }
    }

    func clearArtifactStorage(_ id: String) async throws {
        try call("clearArtifactStorage", id) { $0.artifactStorage[id] = nil }
    }

    func deleteArtifact(_ id: String) async throws {
        try call("deleteArtifact", id) { state in state.artifacts.removeAll { $0.id == id } }
    }

    func createPairingCode() async throws -> PairingCode {
        await pass("createPairingCode")
        return try call("createPairingCode") { _ in
            PairingCode(code: "ABCD", expiresAt: Date(timeIntervalSince1970: 0))
        }
    }

    func devices() async throws -> [Device] {
        try call("devices") { $0.devices }
    }

    func revokeDevice(_ id: String) async throws {
        try call("revokeDevice", id) { state in state.devices.removeAll { $0.id == id } }
    }

    func pushStatus() async throws -> PushStatus {
        try call("pushStatus") { PushStatus(devices: $0.pushDevices) }
    }

    func health() async throws -> DaemonHealth {
        try call("health") { $0.health }
    }

    func restartService() async throws {
        try call("restartService") { _ in }
    }

    // MARK: Settings (B81)

    func repoBranches(_ name: String) async throws -> [String] {
        try call("repoBranches", name) { $0.branches[name] ?? [] }
    }

    func repoBranchMap(_ name: String) async throws -> BranchMap {
        guard let map = try call("repoBranchMap", name, { $0.branchMaps[name] }) else {
            throw APIError.notFound("unknown repo")
        }
        return map
    }

    func storage() async throws -> StorageUsage {
        try call("storage") { $0.storage }
    }

    func storageSettings() async throws -> StorageSettings {
        try call("storageSettings") { $0.storageSettings }
    }

    func updateStorageSettings(_ settings: StorageSettings) async throws -> StorageSettings {
        await pass("updateStorageSettings")
        return try call("updateStorageSettings", "\(settings.archiveAfterDays ?? 0)") { state in
            state.storageSettings = settings
            return settings
        }
    }

    func largeAttachments(limit: Int) async throws -> [LargeAttachment] {
        try call("largeAttachments", "\(limit)") { Array($0.largeAttachments.prefix(limit)) }
    }

    func deleteAttachment(_ id: String) async throws {
        await pass("deleteAttachment")
        try call("deleteAttachment", id) { state in
            state.largeAttachments.removeAll { $0.id == id }
        }
    }

    func rebuildSearch() async throws {
        await pass("rebuildSearch")
        try call("rebuildSearch") { _ in }
    }

    func pixieSettings() async throws -> PixieSettings {
        try call("pixieSettings") { $0.pixieSettings }
    }

    func updatePixieSettings(_ settings: PixieSettings) async throws -> PixieSettings {
        try call("updatePixieSettings") { state in
            state.pixieSettings = settings
            return settings
        }
    }

    func notificationRules() async throws -> NotificationRules {
        try call("notificationRules") { $0.notificationRules }
    }

    func updateNotificationRules(_ rules: NotificationRules) async throws -> NotificationRules {
        try call("updateNotificationRules", rules.pixieReportLevel.rawValue) { state in
            state.notificationRules = rules
            return rules
        }
    }

    func githubAccount() async throws -> GitHubAccount {
        try call("githubAccount") { $0.github }
    }

    func checkGitHubAccount() async throws -> GitHubAccount {
        await pass("checkGitHubAccount")
        return try call("checkGitHubAccount") { $0.github }
    }

    func engineAccounts() async throws -> [EngineAccount] {
        try call("engineAccounts") { $0.accounts }
    }

    func addAccount(provider: String) async throws -> AccountSignIn {
        try call("addAccount", provider) { state in
            let account = EngineAccount(
                id: "new\(state.accounts.count)", provider: provider, title: provider.capitalized,
                signedIn: false, active: false, first: false, signingIn: true)
            state.accounts.append(account)
            return AccountSignIn(account: account, authURL: state.signInURL)
        }
    }

    func signInAccount(_ id: String) async throws -> AccountSignIn {
        try call("signInAccount", id) { state in
            let index = state.accounts.firstIndex { $0.id == id }!
            state.accounts[index].signingIn = true
            return AccountSignIn(account: state.accounts[index], authURL: state.signInURL)
        }
    }

    func cancelAccountSignIn(_ id: String) async throws {
        try call("cancelAccountSignIn", id) { _ in }
    }

    func signOutAccount(_ id: String) async throws -> EngineAccount {
        await pass("signOutAccount")
        return try call("signOutAccount", id) { state in
            let index = state.accounts.firstIndex { $0.id == id }!
            state.accounts[index].signedIn = false
            return state.accounts[index]
        }
    }

    func renameAccount(_ id: String, name: String?) async throws -> EngineAccount {
        try call("renameAccount", "\(id) \(name ?? "-")") { state in
            let index = state.accounts.firstIndex { $0.id == id }!
            state.accounts[index].name = name
            state.accounts[index].title = name ?? state.accounts[index].email ?? "Claude"
            return state.accounts[index]
        }
    }

    func activateAccount(_ id: String) async throws -> [EngineAccount] {
        await pass("activateAccount")
        return try call("activateAccount", id) { state in
            let provider = state.accounts.first { $0.id == id }!.provider
            for index in state.accounts.indices where state.accounts[index].provider == provider {
                state.accounts[index].active = state.accounts[index].id == id
            }
            return state.accounts
        }
    }

    func removeAccount(_ id: String) async throws -> [EngineAccount] {
        try call("removeAccount", id) { state in
            state.accounts.removeAll { $0.id == id }
            return state.accounts
        }
    }

    func bankedResets(_ id: String) async throws -> BankedResets {
        try call("bankedResets", id) { $0.banked[id] ?? BankedResets(available: 0, credits: []) }
    }

    /// A reset uses the credit: one fewer available, and it leaves the details.
    func useBankedReset(_ id: String, creditID: String) async throws -> BankedResetUse {
        try call("useBankedReset", "\(id) \(creditID)") { state in
            if state.useOutcome == .reset, var banked = state.banked[id] {
                banked.credits?.removeAll { $0.id == creditID }
                banked.available -= 1
                state.banked[id] = banked
                let index = state.accounts.firstIndex { $0.id == id }!
                state.accounts[index].bankedResets?.available = banked.available
            }
            return BankedResetUse(outcome: state.useOutcome, accounts: state.accounts)
        }
    }

    func refreshAccounts() async throws -> [EngineAccount] {
        await pass("refreshAccounts")
        return try call("refreshAccounts") { state in
            state.accounts = state.refreshedAccounts ?? state.accounts
            return state.accounts
        }
    }

    func claudeCode() async throws -> ClaudeCodeStatus {
        try call("claudeCode") { $0.claudeCode }
    }

    func installClaudeCode() async throws {
        try call("installClaudeCode") { _ in }
    }

    func plugins() async throws -> [InstalledPlugin] {
        try call("plugins") { $0.plugins }
    }

    func standaloneSkills() async throws -> [StandaloneSkill] {
        try call("standaloneSkills") { $0.skills }
    }

    func marketplaces() async throws -> [PluginMarketplace] {
        try call("marketplaces") { $0.marketplaces }
    }

    func addMarketplace(source: String) async throws {
        try call("addMarketplace", source) { state in
            state.marketplaces.append(PluginMarketplace(name: source, kind: "url", source: source))
        }
    }

    func removeMarketplace(_ name: String) async throws {
        try call("removeMarketplace", name) { state in
            state.marketplaces.removeAll { $0.name == name }
        }
    }

    func availablePlugins() async throws -> [AvailablePlugin] {
        try call("availablePlugins") { $0.available }
    }

    func pluginDetails(_ id: String) async throws -> PluginDetails {
        try call("pluginDetails", id) { _ in
            PluginDetails(id: id, name: id, marketplace: "official", source: "x")
        }
    }

    func installPlugin(_ id: String) async throws {
        await pass("installPlugin")
        try call("installPlugin", id) { state in
            state.plugins.append(InstalledPlugin(id: id, name: id, marketplace: "official"))
        }
    }

    func uninstallPlugin(_ id: String) async throws {
        try call("uninstallPlugin", id) { state in state.plugins.removeAll { $0.id == id } }
    }

    func setPluginEnabled(_ id: String, enabled: Bool) async throws {
        try call("setPluginEnabled", "\(id) \(enabled)") { _ in }
    }

    // MARK: Configuration (B97)

    func configuration() async throws -> ConfigurationPage {
        try call("configuration") { $0.configuration }
    }

    func configurationFile(path: String) async throws -> ConfigFile {
        try call("configurationFile", path) {
            $0.configFiles[path] ?? ConfigFile(path: path, text: "")
        }
    }

    /// Refuses with a conflict when the version is not the stored file's, as the daemon.
    func saveConfigurationFile(path: String, text: String, expectedVersion: String?)
        async throws -> String
    {
        await pass("saveConfigurationFile")
        let current = try call("saveConfigurationFile", "\(path) \(expectedVersion ?? "nil")") {
            $0.configFiles[path]?.version
        }
        guard current == expectedVersion else {
            throw APIError.conflict("changed on disk")
        }
        let version = "v-\(text.count)-\(text.hashValue)"
        self.set { $0.configFiles[path] = ConfigFile(path: path, text: text, version: version) }
        return version
    }

    func setUsesShared(engine: String, item: SharedItem, on: Bool) async throws
        -> ConfigurationPage
    {
        try call("setUsesShared", "\(engine) \(item.rawValue) \(on)") { state in
            let index = state.configuration.engines.firstIndex { $0.id == engine }!
            state.configuration.engines[index].usesShared[item].on = on
            return state.configuration
        }
    }

    func createSkill(name: String, description: String) async throws -> ConfigurationPage {
        try call("createSkill", "\(name) \(description)") { state in
            state.configuration.shared.skills.items.append(
                ConfigSkill(
                    name: name, description: description, path: "/s/\(name)/SKILL.md",
                    source: .yours))
            return state.configuration
        }
    }

    func deleteSkill(_ name: String) async throws -> ConfigurationPage {
        try call("deleteSkill", name) { state in
            state.configuration.shared.skills.items.removeAll { $0.name == name }
            return state.configuration
        }
    }

    func makeSkillShared(_ name: String, engine: String) async throws -> ConfigurationPage {
        try call("makeSkillShared", "\(name) \(engine)") { state in
            let index = state.configuration.shared.skills.items.firstIndex { $0.name == name }!
            state.configuration.shared.skills.items[index].source = .yours
            state.configuration.shared.skills.items[index].engine = nil
            return state.configuration
        }
    }

    func setSkillEnabled(_ name: String, codex enabled: Bool) async throws -> ConfigurationPage {
        await pass("setSkillEnabled")
        return try call("setSkillEnabled", "\(name) \(enabled)") { state in
            let index = state.configuration.shared.skills.items.firstIndex { $0.name == name }!
            state.configuration.shared.skills.items[index].codexEnabled = enabled
            return state.configuration
        }
    }

    func saveMCPServer(_ name: String, _ spec: MCPServerSpec) async throws -> ConfigurationPage {
        try call("saveMCPServer", "\(name) \(Fixture.json(spec))") { state in
            state.mcpServers[name] = spec
            state.configuration.shared.mcpServers.removeAll { $0.name == name }
            state.configuration.shared.mcpServers.append(
                MCPServerEntry(
                    name: name, summary: spec.command ?? spec.url ?? "", transport: spec.transport,
                    engines: ["claude", "codex"]))
            return state.configuration
        }
    }

    func deleteMCPServer(_ name: String) async throws -> ConfigurationPage {
        try call("deleteMCPServer", name) { state in
            state.configuration.shared.mcpServers.removeAll { $0.name == name }
            return state.configuration
        }
    }

    func mcpServer(_ name: String) async throws -> MCPServerSpec {
        try call("mcpServer", name) { $0.mcpServers[name] ?? MCPServerSpec(transport: .stdio) }
    }

    func copyPreview(engine: String) async throws -> CopyPreview {
        try call("copyPreview", engine) { $0.copyPreview }
    }

    func copyToShared(engine: String, instructions: Bool) async throws -> CopyResult {
        try call("copyToShared", "\(engine) instructions=\(instructions)") { state in
            let index = state.configuration.engines.firstIndex { $0.id == engine }!
            state.configuration.engines[index].missingFromShared = MissingFromShared()
            return CopyResult(
                summary: "Copied to Shared: 2 skills added.", undoID: "backup-1",
                page: state.configuration)
        }
    }

    func undoCopy(_ id: String) async throws -> ConfigurationPage {
        try call("undoCopy", id) { _ in Fixture.configurationPage }
    }

    func repoConfiguration(_ repo: String) async throws -> RepoConfiguration {
        try call("repoConfiguration", repo) { state in
            state.repoConfigurations[repo]
                ?? RepoConfiguration(instructions: [], skills: [], mcpServers: [])
        }
    }

    func saveRepoMCPServer(_ repo: String, _ name: String, _ spec: MCPServerSpec) async throws {
        try call("saveRepoMCPServer", "\(repo) \(name)") { state in
            var config =
                state.repoConfigurations[repo]
                ?? RepoConfiguration(instructions: [], skills: [], mcpServers: [])
            config.mcpServers.append(
                MCPServerEntry(name: name, summary: spec.command ?? "", transport: spec.transport))
            state.repoConfigurations[repo] = config
        }
    }

    func deleteRepoMCPServer(_ repo: String, _ name: String) async throws {
        try call("deleteRepoMCPServer", "\(repo) \(name)") { state in
            state.repoConfigurations[repo]?.mcpServers.removeAll { $0.name == name }
        }
    }

    func createRepoSkill(_ repo: String, name: String, description: String) async throws {
        try call("createRepoSkill", "\(repo) \(name) \(description)") { state in
            state.repoConfigurations[repo]?.skills.append(
                ConfigSkill(name: name, path: "/r/\(name)/SKILL.md", source: .project))
        }
    }

    func codexPlugins(query: String) async throws -> [CodexPlugin] {
        await pass("codexPlugins \(query)")
        return try call("codexPlugins", query) { state in
            query.isEmpty
                ? state.codexPlugins : state.codexPlugins.filter { $0.name.contains(query) }
        }
    }

    func installCodexPlugin(_ id: String) async throws {
        try call("installCodexPlugin", id) { state in
            let index = state.codexPlugins.firstIndex { $0.id == id }!
            state.codexPlugins[index].installed = true
        }
    }

    func uninstallCodexPlugin(_ id: String) async throws {
        try call("uninstallCodexPlugin", id) { state in
            let index = state.codexPlugins.firstIndex { $0.id == id }!
            state.codexPlugins[index].installed = false
        }
    }

    func codexMarketplaces() async throws -> [CodexMarketplace] {
        try call("codexMarketplaces") { $0.codexMarketplaces }
    }

    func addCodexMarketplace(source: String) async throws {
        try call("addCodexMarketplace", source) { state in
            state.codexMarketplaces.append(CodexMarketplace(name: source, path: source))
        }
    }

    func removeCodexMarketplace(_ name: String) async throws {
        try call("removeCodexMarketplace", name) { state in
            state.codexMarketplaces.removeAll { $0.name == name }
        }
    }
}
