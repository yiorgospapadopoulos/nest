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

/// Per session: the agent's tasks (Goals), its agents (main and subagents), its
/// background work (subagents and background commands, which can outlive the turn) and
/// the messages queued for the end of the turn.
@MainActor @Observable
public final class ActivityStore {
    public static let recentStepLimit = 5
    /// Idle chats updated this recently are loaded too: their background work may still run.
    public static let idleWatchWindow: TimeInterval = 12 * 3600

    private var tasks: [String: [TrackedTask]] = [:]
    private var agents: [String: [TrackedAgent]] = [:]
    private var background: [String: BackgroundSummary] = [:]
    private var queued: [String: [QueuedMessage]] = [:]

    let api: any HarnessAPI
    @ObservationIgnored private let live = LiveEventLog()

    public init(api: any HarnessAPI) {
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
        } replay: {
            apply($0)
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

    /// Running agents and background commands across the given sessions, for the Agents
    /// card header.
    public func runningAgents(in sessions: [String]) -> Int {
        sessions.reduce(0) { total, id in
            total + (agents[id] ?? []).count { $0.status == .running }
                + background(session: id).runningCommands.count
        }
    }

    /// Messages waiting for the running turn, oldest first.
    public func queued(session id: String) -> [QueuedMessage] {
        queued[id] ?? []
    }

    /// Shows a message the daemon just queued, ahead of its `session.queued` event.
    public func enqueue(_ message: QueuedMessage, session id: String) {
        guard !queued(session: id).contains(where: { $0.id == message.id }) else { return }
        queued[id, default: []].append(message)
    }

    /// Cancels a queued message; one already delivered or gone is dropped from the list.
    public func cancelQueued(_ message: String, session id: String) async throws {
        do {
            try await api.cancelQueued(id, queuedID: message)
        } catch APIError.notFound {
            // Delivered or cancelled elsewhere in the meantime.
        }
        queued[id]?.removeAll { $0.id == message }
    }

    /// An agent's last steps, oldest first.
    public func recentSteps(of agent: TrackedAgent) -> [AgentStep] {
        Array(agent.steps.suffix(Self.recentStepLimit))
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
            guard let id = event.sessionID, task.phase == .finished,
                let toolUseID = task.toolUseID
            else { return }
            background[id]?.finish(toolUseID: toolUseID, as: task.agentStatus, at: event.ts)
        case .queued(let list):
            guard let id = event.sessionID else { return }
            queued[id] = list
        case .sessionDeleted(let id):
            tasks[id] = nil
            agents[id] = nil
            background[id] = nil
            queued[id] = nil
        default:
            break
        }
    }
}
