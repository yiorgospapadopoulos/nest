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

/// All sessions (chats) by id, with the actions of the sidebar and composer.
@MainActor @Observable
public final class SessionsStore {
    public private(set) var sessions: [String: Session] = [:]
    /// Sessions whose pull request is being read from GitHub now.
    public private(set) var refreshingPR: Set<String> = []

    let api: any HarnessAPI
    let approvals: ApprovalsStore

    public init(api: any HarnessAPI, approvals: ApprovalsStore) {
        self.api = api
        self.approvals = approvals
    }

    /// Loads open and archived sessions of every repo.
    public func load() async throws {
        let active = try await api.sessions(repo: nil, archived: false)
        let archived = try await api.sessions(repo: nil, archived: true)
        var loaded: [String: Session] = [:]
        for session in active + archived {
            loaded[session.id] = session
        }
        sessions = loaded
    }

    public func session(_ id: String) -> Session? {
        sessions[id]
    }

    /// The repo's sessions, most recently updated first. Pixie chats belong to no project
    /// and are left out (D057).
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

    /// Waiting on a prompt or question, holding work to review, or looking stuck.
    public func needsYou(_ session: Session) -> Bool {
        session.state == .waiting || approvals.hasPendingReview(session: session.id)
            || session.stuck != nil
    }

    /// The status color of a session's dot and pill; a pull request ready to merge shows
    /// as review too.
    public func tone(of session: Session) -> StatusTone {
        let ready =
            approvals.hasPendingReview(session: session.id)
            || approvals.pending(session: session.id).contains { $0.kind == .merge }
        return StatusTone.of(session.state, hasReview: ready)
    }

    /// The status words of a session's pill, sidebar row and palette entry.
    public func statusLabel(of session: Session) -> String {
        switch session.state {
        case .starting: return "Starting"
        case .running: return "Running"
        case .waiting:
            // A question first, then a plan, then a permission prompt (as on the iPhone).
            let kinds = Set(approvals.pending(session: session.id).map(\.kind))
            if kinds.contains(.question) {
                return "Question"
            }
            return kinds.contains(.plan) ? "Plan ready" : "Needs approval"
        case .interrupted: return "Interrupted"
        case .failed: return "Failed"
        case .closed: return "Done"
        case .idle, .unknown:
            if approvals.hasPendingReview(session: session.id) {
                return "Ready for review"
            }
            return tone(of: session) == .review ? "Ready to merge" : "Idle"
        }
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
    /// working, closed or archived, and with no review of new work pending.
    public func checksFailed(in repo: String?) -> [Session] {
        listed(in: repo).filter { session in
            guard let pr = session.pr, pr.state == .open, pr.checks.state == .failure else {
                return false
            }
            return !session.state.isInFlight && session.state != .closed && !session.isArchived
                && !approvals.hasPendingReview(session: session.id)
        }
    }

    /// Chats that look stuck, for their Needs you cards; archived ones and pixie chats are
    /// left out.
    public func stuck(in repo: String?) -> [Session] {
        listed(in: repo).filter { $0.stuck != nil && !$0.isArchived }
    }

    /// What needs the user, for the project's tab and the Dock badge (every project's
    /// without a repo): pending approvals, pull requests whose checks failed and chats
    /// that look stuck, as on the iPhone. A pixie's pending approvals count in the Dock
    /// badge, but no project's count; its chat is not a project chat, so it adds no failed
    /// checks or stuck flags (D057).
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
        store(try await api.createSession(request))
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
        let sent = try await api.sendMessage(id, text: text, attachmentIDs: attachmentIDs)
        store(sent.session)
        return sent.queuedMessage
    }

    /// Asks Claude Code to compact the chat's context; queued while a turn runs.
    @discardableResult
    public func compact(_ id: String) async throws -> QueuedMessage? {
        try await send(id, text: "/compact")
    }

    /// Sends the failing check names into the chat, asking the agent to fix them; nothing
    /// is sent while no check failed.
    @discardableResult
    public func sendChecksFailure(_ id: String) async throws -> QueuedMessage? {
        guard let names = sessions[id]?.pr?.failingChecks, !names.isEmpty else { return nil }
        return try await send(id, text: CIFailure.message(names))
    }

    /// Reads the pull request from GitHub now.
    public func refreshPR(_ id: String) async throws {
        refreshingPR.insert(id)
        defer { refreshingPR.remove(id) }
        store(try await api.refreshPR(id))
    }

    /// Send a nudge: stops the stuck turn and sends a message asking for another
    /// approach; nothing is sent once the chat no longer looks stuck.
    @discardableResult
    public func nudge(_ id: String) async throws -> QueuedMessage? {
        guard let flag = sessions[id]?.stuck else { return nil }
        let sent = try await api.sendMessage(
            id, text: flag.nudge, attachmentIDs: [], interrupt: true)
        store(sent.session)
        return sent.queuedMessage
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
        case .sessionDeleted(let id):
            sessions[id] = nil
        default:
            break
        }
    }

    private func update(_ id: String, _ request: UpdateSessionRequest) async throws {
        store(try await api.updateSession(id, request))
    }

    @discardableResult
    private func store(_ session: Session) -> Session {
        sessions[session.id] = session
        return session
    }
}
