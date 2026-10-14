import Foundation
import Synchronization

@testable import HarnessKit

/// An in-memory daemon: answers from its state, records each call, and fails calls named
/// in `failures`.
final class FakeAPI: HarnessAPI {
    struct State {
        var calls: [String] = []
        var failures: [String: any Error] = [:]
        var repos = Fixture.repos
        var sessions: [Session] = []
        var details: [String: Session] = [:]
        var events: [String: [Event]] = [:]
        var approvals: [Approval] = []
        var diff = Fixture.diff
        var connectors = Fixture.connectors
        var months: [String: UsageMonth] = [:]
        var limits = Fixture.usageLimits
        /// What a manual refresh answers.
        var refreshedLimits = Fixture.usageLimits
        var usageSettings = UsageSettings(refreshMinutes: 3)
        var devices = Fixture.decode([Device].self, "devices")
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
        /// Search answers by query.
        var searches: [String: SearchResults] = [:]
        var stuckSettings = StuckSettings(
            waitingMinutes: 15, silentMinutes: 10, repeatedCalls: 4, turnMinutes: 60)
        var models = Fixture.models
        var account = ClaudeAccount(
            displayName: "Sam", email: "me@example.com", plan: "Claude Max",
            organization: nil)
        var agentDefaults = AgentDefaults(
            model: "opus", effort: .xhigh, permissionMode: .default, mode: .inPlace)
        /// What a rewind preview answers, by session id.
        var rewinds: [String: RewindPreview] = [:]
        /// Gitignored files a repo suggests linking, by repo name.
        var linkSuggestions: [String: [String]] = [:]
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
            if let failure = state.failures[name] {
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
            return state.repos[index]
        }
    }

    func linkSuggestions(_ name: String) async throws -> [String] {
        try call("linkSuggestions", name) { $0.linkSuggestions[name] ?? [] }
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

    func createSession(_ request: CreateSessionRequest) async throws -> Session {
        try call("createSession", request.prompt) { state in
            var session = Fixture.session(
                "new-\(state.sessions.count)", repo: request.repo, state: .starting)
            session.prompt = request.prompt
            session.model = request.model
            session.effort = request.effort
            session.permissionMode = request.permissionMode ?? .default
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

    func rewindPreview(_ id: String, message: Int) async throws -> RewindPreview {
        try call("rewindPreview", "\(id) \(message)") { state in
            state.rewinds[id] ?? RewindPreview(canRewind: true)
        }
    }

    func rewind(_ id: String, message: Int) async throws {
        await pass("rewind")
        try call("rewind", "\(id) \(message)") { _ in }
    }

    func ciFeedback(_ id: String) async throws {
        try call("ciFeedback", id) { _ in }
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

    func reject(_ sessionID: String) async throws -> Session {
        try call("reject", sessionID) { state in
            session(sessionID, in: &state) { $0.state = .closed }
        }
    }

    func feedback(_ sessionID: String, text: String) async throws -> Session {
        try call("feedback", "\(sessionID) \(text)") { state in
            session(sessionID, in: &state) { $0.state = .running }
        }
    }

    func merge(_ sessionID: String, _ request: MergeRequest) async throws -> Session {
        try call("merge", "\(sessionID) \(request.method.rawValue)") { state in
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

    func usageMonth(year: Int, month: Int) async throws -> UsageMonth {
        try call("usageMonth", "\(year)-\(month)") { state in
            if let stored = state.months["\(year)-\(month)"] {
                return stored
            }
            var usage = Fixture.usageMonth
            usage.year = year
            usage.month = month
            usage.days = usage.days.map { day in
                var day = day
                day.date = CalendarDay(year: year, month: month, day: day.date.day)
                return day
            }
            return usage
        }
    }

    func usageLimits() async throws -> UsageLimits {
        try call("usageLimits") { $0.limits }
    }

    func refreshUsage() async throws -> UsageLimits {
        await pass("refreshUsage")
        return try call("refreshUsage") { state in
            state.limits = state.refreshedLimits
            return state.limits
        }
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
        try call("models") { ModelList(models: $0.models, updatedAt: nil) }
    }

    func account() async throws -> ClaudeAccount {
        try call("account") { $0.account }
    }

    func agentDefaults() async throws -> AgentDefaults {
        try call("agentDefaults") { $0.agentDefaults }
    }

    func updateAgentDefaults(_ defaults: AgentDefaults) async throws -> AgentDefaults {
        let detail = [
            defaults.model ?? "nil", defaults.effort?.rawValue ?? "nil",
            defaults.permissionMode?.rawValue ?? "nil", defaults.mode.rawValue,
        ].joined(separator: " ")
        return try call("updateAgentDefaults", detail) { state in
            state.agentDefaults = defaults
            return defaults
        }
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
}
