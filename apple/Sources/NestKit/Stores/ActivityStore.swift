import Foundation
import Observation

/// A session's task list as the Goals card shows it.
public struct Goals: Sendable, Hashable {
    /// The agent's tasks in order, deleted ones left out.
    public let tasks: [TrackedTask]

    public var completed: Int { tasks.count { $0.status == .completed } }
    public var inProgress: Int { tasks.count { $0.status == .inProgress } }
    public var pending: Int { tasks.count { $0.status == .pending } }
    /// The task being worked on now.
    public var current: TrackedTask? { tasks.first { $0.status == .inProgress } }
    /// Completed share from 0 to 1; 0 without tasks.
    public var progress: Double { tasks.isEmpty ? 0 : Double(completed) / Double(tasks.count) }
}

/// A chat in the Goals card, with its checklist.
public struct GoalEntry: Sendable, Hashable, Identifiable {
    public let session: Session
    public let goals: Goals

    public var id: String { session.id }
}

/// Per session: the agent's tasks (Goals), its agents (main and subagents), its
/// background work (subagents and background commands, which can outlive the turn) and
/// the pending messages Claude has not read yet.
@MainActor @Observable
public final class ActivityStore {
    /// Idle chats updated this recently are loaded too: their background work may still run.
    public static let idleWatchWindow: TimeInterval = 12 * 3600

    private var tasks: [String: [TrackedTask]] = [:]
    private var agents: [String: [TrackedAgent]] = [:]
    private var background: [String: BackgroundSummary] = [:]
    private var queued: [String: [QueuedMessage]] = [:]
    /// Pending messages Claude read before Remove reached it, until the next list.
    private var taken: [String: Set<String>] = [:]
    /// Pending messages whose Send now waits for the next list.
    private var sendingNow: [String: Set<String>] = [:]
    /// Tasks asked to stop, by session, until their end arrives (B59).
    private var stopping: [String: Set<String>] = [:]
    /// Sessions whose Claude Code run is closed, so nothing can be stopped until it runs.
    private var noRun: Set<String> = []

    let api: any NestAPI
    @ObservationIgnored private let live = LiveEventLog()

    public init(api: any NestAPI) {
        self.api = api
    }

    /// Loads the current tasks, agents and background work from the session detail; live
    /// events that arrive meanwhile apply again on top.
    public func load(session id: String) async throws {
        _ = try await live.read {
            try await self.api.session(id)
        } store: { detail in
            tasks[id] = detail.tasks ?? []
            agents[id] = detail.agents ?? []
            background[id] = detail.background ?? .empty
            queued[id] = detail.queued ?? []
            taken[id] = nil
            sendingNow[id] = nil
        } replay: {
            apply($0)
        }
    }

    /// Loads what the project's chats are working towards (D092); events that arrive
    /// meanwhile apply again on top. Of `sessions`, the project's chats, those the daemon
    /// leaves out have no tasks left, as when a list was cleared while disconnected.
    public func loadGoals(repo: String, sessions: [Session]) async throws {
        _ = try await live.read {
            try await self.api.goals(repo: repo)
        } store: { goals in
            let listed = Set(goals.map(\.sessionID))
            for session in sessions where !listed.contains(session.id) {
                tasks[session.id] = []
            }
            for goal in goals {
                tasks[goal.sessionID] = goal.tasks
            }
        } replay: {
            apply($0)
        }
    }

    /// The Goals card's chats among the project's `sessions`: each one working or with
    /// tasks in its list, working ones first, then the most recently updated. Archived
    /// chats are left out.
    public func goalEntries(_ sessions: [Session]) -> [GoalEntry] {
        sessions
            .filter { !$0.isArchived }
            .map { GoalEntry(session: $0, goals: goals(session: $0.id)) }
            .filter { $0.session.state.isInFlight || !$0.goals.tasks.isEmpty }
            .sorted {
                ($0.session.state.isInFlight ? 1 : 0, $0.session.updatedAt, $0.id)
                    > ($1.session.state.isInFlight ? 1 : 0, $1.session.updatedAt, $1.id)
            }
    }

    /// The chats whose activity the panel loads: busy ones, open panes, chats with work
    /// still running, and idle chats updated within `idleWatchWindow` of `now`.
    public func watchList(_ sessions: [Session], open: [String], now: Date) -> [String] {
        var ids = sessions.filter { session in
            session.state.isInFlight || hasRunningWork(session: session.id)
                || (session.state == .idle && !session.isArchived
                    && now.timeIntervalSince(session.updatedAt) < Self.idleWatchWindow)
        }
        .map(\.id)
        for id in open where !ids.contains(id) {
            ids.append(id)
        }
        return ids
    }

    public func goals(session id: String) -> Goals {
        Goals(tasks: (tasks[id] ?? []).filter { $0.status != .deleted })
    }

    /// The main agent first, then subagents in the order they started.
    public func agents(session id: String) -> [TrackedAgent] {
        let list = agents[id] ?? []
        return list.filter(\.isMain) + list.filter { !$0.isMain }
    }

    /// Subagents and background commands, for the bar above the composer.
    public func background(session id: String) -> BackgroundSummary {
        background[id] ?? .empty
    }

    /// An agent or a background command of the session is still at work, even when the
    /// chat itself is idle.
    public func hasRunningWork(session id: String) -> Bool {
        (agents[id] ?? []).contains { $0.status == .running }
            || background(session: id).running > 0
    }

    /// Pending messages Claude has not read yet, oldest first (B59).
    public func queued(session id: String) -> [QueuedMessage] {
        queued[id] ?? []
    }

    /// Shows a message the daemon just queued, ahead of its `session.queued` event.
    public func enqueue(_ message: QueuedMessage, session id: String) {
        guard !queued(session: id).contains(where: { $0.id == message.id }) else { return }
        queued[id, default: []].append(message)
    }

    /// Remove was refused because Claude read the message; it leaves with the next list.
    public func isTaken(_ message: String, session id: String) -> Bool {
        taken[id]?.contains(message) == true
    }

    /// Send now was tapped and the daemon's next list has not come yet.
    public func isSendingNow(_ message: String, session id: String) -> Bool {
        sendingNow[id]?.contains(message) == true
    }

    /// The quiet line under a pending message; `agent` names the chat's engine. Remove
    /// came too late for a taken one.
    public func note(
        for message: QueuedMessage, session id: String, working: Bool, agent: String
    ) -> String {
        isTaken(message.id, session: id)
            ? "\(agent) already read this message"
            : message.note(working: working, agent: agent)
    }

    /// Removes a pending message; one already gone leaves the list too. False when Claude
    /// already read it: the row stays, saying so, and the message shows in the transcript.
    @discardableResult
    public func remove(_ message: String, session id: String) async throws -> Bool {
        do {
            try await api.cancelQueued(id, queuedID: message)
        } catch APIError.notFound {
            // Read or removed elsewhere in the meantime.
        } catch APIError.messageTaken {
            taken[id, default: []].insert(message)
            return false
        }
        queued[id]?.removeAll { $0.id == message }
        return true
    }

    /// Stops the turn and sends the message right after it; the control stays off until
    /// the next list. A message Claude already read leaves the list.
    public func sendNow(_ message: String, session id: String) async throws {
        guard !isSendingNow(message, session: id) else { return }
        sendingNow[id, default: []].insert(message)
        do {
            try await api.sendQueuedNow(id, queuedID: message)
        } catch APIError.notFound {
            sendingNow[id]?.remove(message)
            queued[id]?.removeAll { $0.id == message }
        } catch {
            sendingNow[id]?.remove(message)
            throw error
        }
    }

    /// Whether the session's background tasks and subagents can be stopped one by one:
    /// not while its Claude Code run is known to be closed.
    public func canStop(session id: String) -> Bool {
        !noRun.contains(id)
    }

    /// A stop was sent for the task (by its task or tool use id) and it has not ended yet.
    public func isStopping(_ task: String, session id: String) -> Bool {
        stopping[id]?.contains(task) == true
    }

    /// Stops one background task or subagent; the turn goes on. A task that is no longer
    /// running reloads the rows, and a closed run hides the control.
    public func stop(task: String, session id: String) async throws {
        guard !isStopping(task, session: id) else { return }
        stopping[id, default: []].insert(task)
        do {
            try await api.stopTask(id, task: task)
        } catch APIError.notFound {
            stopping[id]?.remove(task)
            try? await load(session: id)
        } catch APIError.conflict {
            stopping[id]?.remove(task)
            noRun.insert(id)
        } catch {
            stopping[id]?.remove(task)
            throw error
        }
    }

    public func apply(_ event: Event) {
        live.record(event)
        switch event.body {
        case .tasks(let list):
            guard let id = event.sessionID else { return }
            tasks[id] = list
        case .agents(let list, let summary):
            guard let id = event.sessionID else { return }
            agents[id] = list
            if let summary {
                background[id] = summary
            }
        case .agentTask(let task):
            // The next snapshot confirms it; this keeps the counts right in between.
            guard let id = event.sessionID, task.phase == .finished else { return }
            stopping[id]?.remove(task.taskID)
            guard let toolUseID = task.toolUseID else { return }
            stopping[id]?.remove(toolUseID)
            background[id]?.finish(toolUseID: toolUseID, as: task.agentStatus, at: event.ts)
        case .sessionState(.running, _):
            guard let id = event.sessionID else { return }
            noRun.remove(id)
        case .queued(let list):
            guard let id = event.sessionID else { return }
            queued[id] = list
            taken[id] = nil
            sendingNow[id] = nil
        case .sessionDeleted(let id):
            tasks[id] = nil
            agents[id] = nil
            background[id] = nil
            queued[id] = nil
            taken[id] = nil
            sendingNow[id] = nil
            stopping[id] = nil
            noRun.remove(id)
        default:
            break
        }
    }
}
