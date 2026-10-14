import Foundation
import Observation

/// The sidebar's groups, in display order.
public enum SessionGroupKind: String, Sendable, CaseIterable {
    case pinned, needsYou, running, idle, done, archived

    public var title: String {
        switch self {
        case .pinned: "Pinned"
        case .needsYou: "Needs you"
        case .running: "Running"
        case .idle: "Idle"
        case .done: "Done"
        case .archived: "Archived"
        }
    }
}

public struct SessionGroup: Sendable, Hashable, Identifiable {
    public let kind: SessionGroupKind
    public let sessions: [Session]

    public var id: SessionGroupKind { kind }
}

/// The Board view's columns, in display order.
public enum BoardColumn: String, Sendable, CaseIterable {
    case running, waiting, review, done

    public var title: String {
        switch self {
        case .running: "Running"
        case .waiting: "Waiting on you"
        case .review: "Ready for review"
        case .done: "Done"
        }
    }
}

/// The kinds of Needs you cards, in the order they are listed (`design/ui-rules.json`).
public enum NeedsYouSection: String, Sendable, CaseIterable {
    /// Pending approvals, oldest first.
    case approvals
    /// Chats whose pull request failed its checks (`SessionsStore.checksFailed`).
    case checksFailed = "checks_failed"
    /// Chats that look stuck (`SessionsStore.stuck`).
    case stuck
}

/// All sessions (chats) by id, with the actions of the sidebar and composer.
@MainActor @Observable
public final class SessionsStore {
    public private(set) var sessions: [String: Session] = [:]
    /// Sessions whose pull request is being read from GitHub now.
    public private(set) var refreshingPR: Set<String> = []

    let api: any NestAPI
    let approvals: ApprovalsStore
    @ObservationIgnored private let live = LiveEventLog()

    public init(api: any NestAPI, approvals: ApprovalsStore) {
        self.api = api
        self.approvals = approvals
    }

    /// Loads open and archived sessions of every repo; live events that arrive meanwhile
    /// apply again on top. The daemon lists no pixie chats, so the ones already read stay
    /// (D072).
    public func load() async throws {
        _ = try await live.read {
            try await self.api.sessions(repo: nil, archived: false)
                + self.api.sessions(repo: nil, archived: true)
        } store: { list in
            var loaded = sessions.filter { $0.value.pixieID != nil }
            for session in list {
                loaded[session.id] = session
            }
            sessions = loaded
        } replay: {
            apply($0)
        }
    }

    public func session(_ id: String) -> Session? {
        sessions[id]
    }

    /// The repo's sessions, most recently updated first. Pixie chats belong to no project
    /// and are left out (D072).
    public func sessions(in repo: String) -> [Session] {
        sessions.values.filter { $0.repo == repo && $0.pixieID == nil }.sorted {
            ($0.updatedAt, $0.id) > ($1.updatedAt, $1.id)
        }
    }

    /// Sidebar groups; empty groups are left out. Archived sessions only appear under
    /// Archived, and pinned ones only under Pinned.
    public func groups(in repo: String) -> [SessionGroup] {
        let grouped = Dictionary(grouping: sessions(in: repo), by: group(of:))
        return SessionGroupKind.allCases.compactMap { kind in
            grouped[kind].map { SessionGroup(kind: kind, sessions: $0) }
        }
    }

    public func group(of session: Session) -> SessionGroupKind {
        if session.isArchived {
            return .archived
        }
        if session.pinned {
            return .pinned
        }
        if needsYou(session) {
            return .needsYou
        }
        switch session.state {
        case .starting, .running: return .running
        case .closed: return .done
        default: return .idle
        }
    }

    /// Waiting on a prompt or question, holding work to review or a pull request to
    /// merge, or looking stuck, as on the iPhone (`design/ui-rules.json`).
    public func needsYou(_ session: Session) -> Bool {
        let tone = tone(of: session)
        return tone == .waiting || tone == .review || session.stuck != nil
    }

    /// The status color of a session's dot and pill: a prompt, question or plan waits
    /// first; work to review or a pull request to merge shows as review while idle.
    public func tone(of session: Session) -> StatusTone {
        let kinds = pendingKinds(of: session)
        if session.state == .waiting || !kinds.isDisjoint(with: Self.promptKinds) {
            return .waiting
        }
        let idle = session.state == .idle || session.state == .unknown
        let ready = idle && (kinds.contains(.review) || kinds.contains(.merge))
        return StatusTone.of(session.state, hasReview: ready)
    }

    /// Idle chats with nothing to review show a hollow dot.
    public func isHollow(_ session: Session) -> Bool {
        session.state == .idle && tone(of: session) == .done
    }

    /// The status words of a session's pill, sidebar row and palette entry: a question
    /// first, then a plan, then a permission prompt, as on the iPhone.
    public func statusLabel(of session: Session) -> String {
        let kinds = pendingKinds(of: session)
        if kinds.contains(.question) {
            return "Question"
        }
        if kinds.contains(.plan) {
            return "Plan ready"
        }
        if kinds.contains(.permission) || session.state == .waiting {
            return "Needs approval"
        }
        switch session.state {
        case .starting: return "Starting"
        case .running: return "Running"
        case .interrupted: return "Interrupted"
        case .failed: return "Failed"
        case .closed: return "Done"
        case .idle, .waiting, .unknown:
            if kinds.contains(.review) {
                return "Ready for review"
            }
            return kinds.contains(.merge) ? "Ready to merge" : "Idle"
        }
    }

    /// Approvals that make a chat wait on the user before anything else.
    static let promptKinds: Set<ApprovalKind> = [.question, .plan, .permission]

    private func pendingKinds(of session: Session) -> Set<ApprovalKind> {
        Set(approvals.pending(session: session.id).map(\.kind))
    }

    /// The Board view of a repo's open (not archived) sessions.
    public func board(in repo: String) -> [BoardColumn: [Session]] {
        var columns: [BoardColumn: [Session]] = [:]
        for session in sessions(in: repo) where !session.isArchived {
            columns[column(of: session), default: []].append(session)
        }
        return columns
    }

    func column(of session: Session) -> BoardColumn {
        switch session.state {
        case .starting, .running: .running
        case .waiting: .waiting
        default: approvals.hasPendingReview(session: session.id) ? .review : .done
        }
    }

    /// Chats whose open pull request has failed checks and that wait for the user: not
    /// working, closed or archived, and with no review of new work pending. The ones whose
    /// checks changed longest ago come first.
    public func checksFailed(in repo: String?) -> [Session] {
        listed(in: repo).compactMap { session -> (Session, Date)? in
            guard let pr = session.pr, pr.state == .open, pr.checks.state == .failure,
                !session.state.isInFlight, session.state != .closed, !session.isArchived,
                !approvals.hasPendingReview(session: session.id)
            else { return nil }
            return (session, pr.changedAt)
        }
        .sorted { ($0.1, $0.0.id) < ($1.1, $1.0.id) }
        .map(\.0)
    }

    /// Chats that look stuck, for their Needs you cards, the longest stuck first; archived
    /// ones and pixie chats are left out.
    public func stuck(in repo: String?) -> [Session] {
        listed(in: repo).compactMap { session -> (Session, Date)? in
            guard let flag = session.stuck, !session.isArchived else { return nil }
            return (session, flag.since)
        }
        .sorted { ($0.1, $0.0.id) < ($1.1, $1.0.id) }
        .map(\.0)
    }

    /// What needs the user, for the project's tab and the Dock badge (every project's
    /// without a repo): pending approvals, pull requests whose checks failed and chats
    /// that look stuck, as on the iPhone. A pixie's pending approvals count in the Dock
    /// badge, but no project's count; its chat is not a project chat, so it adds no failed
    /// checks or stuck flags (D072).
    public func attention(of repo: String? = nil) -> Int {
        let pending = repo.map(approvals.pending(repo:)) ?? approvals.pending
        return pending.count + checksFailed(in: repo).count + stuck(in: repo).count
    }

    private func listed(in repo: String?) -> [Session] {
        repo.map(sessions(in:)) ?? sessions.values.filter { $0.pixieID == nil }
    }

    // MARK: Actions

    @discardableResult
    public func create(_ request: CreateSessionRequest) async throws -> Session {
        try await fetch { try await self.api.createSession(request) }
    }

    /// Reads one session, such as a pixie's chat, which no list carries.
    public func fetch(_ id: String) async throws {
        store(try await api.session(id))
    }

    /// A session the app got from another call, such as an adopted Claude Code chat.
    public func insert(_ session: Session) {
        store(session)
    }

    /// Sends a message; while a turn runs the daemon queues it, and the queued message
    /// comes back.
    @discardableResult
    public func send(_ id: String, text: String, attachmentIDs: [String] = []) async throws
        -> QueuedMessage?
    {
        try await sendFetched {
            try await self.api.sendMessage(id, text: text, attachmentIDs: attachmentIDs)
        }
    }

    /// Asks Claude Code to compact the chat's context; queued while a turn runs.
    @discardableResult
    public func compact(_ id: String) async throws -> QueuedMessage? {
        try await send(id, text: "/compact")
    }

    /// Has the daemon send the failing checks, with their logs' tails, into the chat for
    /// the agent to fix (IMP-08); the daemon reads them with its own GitHub login, which
    /// agents lack. Nothing is sent while no check failed; whether it was.
    @discardableResult
    public func sendChecksFailure(_ id: String) async throws -> Bool {
        guard let names = sessions[id]?.pr?.failingChecks, !names.isEmpty else { return false }
        try await api.ciFeedback(id)
        return true
    }

    /// Reads the pull request from GitHub now.
    public func refreshPR(_ id: String) async throws {
        refreshingPR.insert(id)
        defer { refreshingPR.remove(id) }
        try await fetch { try await self.api.refreshPR(id) }
    }

    /// Send a nudge: stops the stuck turn and sends a message asking for another
    /// approach; nothing is sent once the chat no longer looks stuck.
    @discardableResult
    public func nudge(_ id: String) async throws -> QueuedMessage? {
        guard let flag = sessions[id]?.stuck else { return nil }
        return try await sendFetched {
            try await self.api.sendMessage(id, text: flag.nudge, attachmentIDs: [], interrupt: true)
        }
    }

    /// Approves a review (`ApprovalsStore.publish`). A refusal (409) means the chat
    /// changed since it was shown, so the chat and its diff are read again before the
    /// error is passed on: a violation's switch, the moved branch or the changed files then
    /// show, and Approve waits for them.
    @discardableResult
    public func publish(_ approval: Approval, _ form: PublishForm) async throws -> Session {
        do {
            return try await fetch { try await self.approvals.publish(approval, form) }
        } catch let error as APIError where error.isConflict {
            _ = try? await fetch { try await self.api.session(approval.sessionID) }
            _ = try? await approvals.loadDiff(for: approval)
            throw error
        }
    }

    public func interrupt(_ id: String) async throws {
        try await api.interrupt(id)
    }

    public func setPinned(_ id: String, _ pinned: Bool) async throws {
        try await update(id, UpdateSessionRequest(pinned: pinned))
    }

    public func rename(_ id: String, to title: String) async throws {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed != sessions[id]?.title else { return }
        try await update(id, UpdateSessionRequest(title: trimmed))
    }

    public func archive(_ id: String) async throws {
        try await update(id, UpdateSessionRequest(archived: true))
    }

    public func unarchive(_ id: String) async throws {
        try await update(id, UpdateSessionRequest(archived: false))
    }

    /// With an effort when the new model needs a different one (`AgentsStore.effort`).
    public func setModel(_ id: String, _ model: String, effort: Effort? = nil) async throws {
        try await update(id, UpdateSessionRequest(model: model, effort: effort))
    }

    /// The engine takes effort when a run opens, so it applies from the chat's next message.
    public func setEffort(_ id: String, _ effort: Effort) async throws {
        try await update(id, UpdateSessionRequest(effort: effort))
    }

    public func setPermissionMode(_ id: String, _ mode: PermissionMode) async throws {
        try await update(id, UpdateSessionRequest(permissionMode: mode))
    }

    /// Deletes the session for good, with its worktree, branch and history.
    public func delete(_ id: String) async throws {
        try await api.deleteSession(id)
        sessions[id] = nil
    }

    public func openInClaudeCode(_ id: String) async throws -> ClaudeCodeLaunch {
        try await api.openInClaudeCode(id)
    }

    // MARK: Events

    public func apply(_ event: Event) {
        live.record(event)
        switch event.body {
        case .sessionCreated(let session), .sessionUpdated(let session):
            store(session)
        case .sessionState(let state, let error):
            guard let id = event.sessionID, var session = sessions[id] else { return }
            session.state = state
            session.lastError = error ?? session.lastError
            session.updatedAt = max(session.updatedAt, event.ts)
            sessions[id] = session
        case .prOpened(let url):
            guard let id = event.sessionID else { return }
            sessions[id]?.prURL = url
        case .context(let context):
            guard let id = event.sessionID else { return }
            sessions[id]?.context = context
        case .pullRequest(let pr):
            guard let id = event.sessionID else { return }
            sessions[id]?.pr = pr
        case .stuck(let flag):
            guard let id = event.sessionID else { return }
            sessions[id]?.stuck = flag
        case .unstuck:
            guard let id = event.sessionID else { return }
            sessions[id]?.stuck = nil
        case .gitViolation:
            guard let id = event.sessionID else { return }
            sessions[id]?.gitViolation = true
        case .workspace(let workspace):
            guard let id = event.sessionID, var session = sessions[id] else { return }
            session.worktreePath = workspace.path
            session.cwd = workspace.path
            session.branch = workspace.branch
            session.baseRef = workspace.baseRef
            sessions[id] = session
        case .sessionDeleted(let id):
            sessions[id] = nil
        default:
            break
        }
    }

    private func update(_ id: String, _ request: UpdateSessionRequest) async throws {
        try await fetch { try await self.api.updateSession(id, request) }
    }

    /// Stores the session a call answers with, then the live events that arrived while it
    /// ran: the answer may be older than they are. The session as it stands is returned.
    @discardableResult
    private func fetch(_ call: () async throws -> Session) async throws -> Session {
        let session = try await live.read(call, store: { store($0) }, replay: apply)
        return sessions[session.id] ?? session
    }

    private func sendFetched(_ call: () async throws -> SentMessage) async throws
        -> QueuedMessage?
    {
        try await live.read(call, store: { store($0.session) }, replay: apply).queuedMessage
    }

    @discardableResult
    private func store(_ session: Session) -> Session {
        sessions[session.id] = session
        return session
    }
}
