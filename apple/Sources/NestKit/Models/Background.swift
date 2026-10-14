import Foundation

public enum BackgroundKind: String, UnknownSafeEnum {
    /// A subagent started with the Agent tool.
    case agent
    /// A Bash command run in the background.
    case bash
    case unknown
}

/// A subagent or a background command, for the "N running · M completed" bar.
public struct BackgroundItem: Codable, Sendable, Hashable, Identifiable {
    /// The Agent or Bash tool use id.
    public var id: String
    public var kind: BackgroundKind
    /// The subagent's type, or the command shortened to one line.
    public var name: String
    public var description: String?
    public var status: AgentStatus
    public var startedAt: Date?
    public var finishedAt: Date?

    enum CodingKeys: String, CodingKey {
        case id, kind, name, description, status
        case startedAt = "started_at"
        case finishedAt = "finished_at"
    }

    public var isRunning: Bool { status == .running }

    /// How long it ran, or has been running at `now`; nil without a start time.
    public func duration(at now: Date) -> String? {
        startedAt.map { Elapsed.duration(from: $0, to: finishedAt ?? now) }
    }
}

/// A session's subagents and background commands, oldest first, with their counts. The
/// bar shows the current exchange's share (`exchange(since:)`).
public struct BackgroundSummary: Codable, Sendable, Hashable {
    public var running: Int
    /// Finished, whether done or failed.
    public var completed: Int
    public var items: [BackgroundItem]

    public static let empty = BackgroundSummary(running: 0, completed: 0, items: [])

    /// Nothing ran: the bar stays hidden.
    public var isEmpty: Bool { running == 0 && completed == 0 }

    /// The bar's text, such as "2 running · 3 completed", or "1 running task" while none
    /// finished yet.
    public var label: String {
        if completed == 0 && running > 0 {
            return running == 1 ? "1 running task" : "\(running) running tasks"
        }
        return "\(running) running · \(completed) completed"
    }

    public var runningItems: [BackgroundItem] { items.filter(\.isRunning) }
    public var finishedItems: [BackgroundItem] { items.filter { !$0.isRunning } }
    /// Background commands still running; subagents are listed with the agents.
    public var runningCommands: [BackgroundItem] {
        runningItems.filter { $0.kind == .bash }
    }

    /// The bar's tasks: those of the exchange the user's latest message (at `start`)
    /// opened, and any earlier one still at work or finished since, which counts as
    /// completed. Without that message, all of them.
    public func exchange(since start: Date?) -> BackgroundSummary {
        guard let start else { return self }
        return exchange(since: ExchangeStart(date: start))
    }

    /// As `exchange(since:)` with a date, placing tasks by event id where `start` knows
    /// the events of their start or end.
    public func exchange(since start: ExchangeStart) -> BackgroundSummary {
        let kept = items.filter { item in
            item.isRunning || start.began(item) || start.ended(item)
        }
        let running = kept.count(where: \.isRunning)
        return BackgroundSummary(running: running, completed: kept.count - running, items: kept)
    }

    /// Applies a task's end ahead of the next snapshot: the item started by that tool call
    /// stops running.
    mutating func finish(toolUseID: String, as status: AgentStatus, at date: Date) {
        guard let index = items.firstIndex(where: { $0.id == toolUseID && $0.isRunning })
        else { return }
        items[index].status = status
        items[index].finishedAt = date
        running = max(0, running - 1)
        completed += 1
    }
}

/// Where the current exchange starts: the user's latest message, by time and, when known,
/// by event id, with the events that started and finished background tasks (I-H).
public struct ExchangeStart: Sendable, Hashable {
    public var date: Date
    /// The message's event id.
    public var event: Int?
    /// The event of each task's tool call, by tool use id.
    public var starts: [String: Int]
    /// The event that reported each task's end, by tool use id.
    public var ends: [String: Int]

    public init(
        date: Date, event: Int? = nil, starts: [String: Int] = [:], ends: [String: Int] = [:]
    ) {
        self.date = date
        self.event = event
        self.starts = starts
        self.ends = ends
    }

    /// The task started in the exchange.
    func began(_ item: BackgroundItem) -> Bool {
        if let event, let start = starts[item.id] {
            return start > event
        }
        return item.startedAt.map { $0 >= date } == true
    }

    /// The task finished during the exchange.
    func ended(_ item: BackgroundItem) -> Bool {
        if let event, let end = ends[item.id] {
            return end > event
        }
        return item.finishedAt.map { $0 >= date } == true
    }
}

public enum AgentTaskPhase: String, UnknownSafeEnum {
    case started
    /// A foreground task moved to the background.
    case backgrounded
    case finished
    case unknown
}

public enum AgentTaskEnd: String, UnknownSafeEnum {
    case completed, failed, stopped
    case unknown
}

/// A step in the life of a subagent or command the engine runs beside the turn
/// (`session.agent_task` events).
public struct AgentTask: Decodable, Sendable, Hashable {
    public var taskID: String
    public var phase: AgentTaskPhase
    /// The Agent or Bash call that started it, when the engine says.
    public var toolUseID: String?
    /// The engine's kind of task, such as `local_agent` or `local_bash`.
    public var taskType: String?
    public var description: String?
    public var background: Bool
    /// How a finished task ended.
    public var status: AgentTaskEnd?

    enum CodingKeys: String, CodingKey {
        case phase, description, background, status
        case taskID = "task_id"
        case toolUseID = "tool_use_id"
        case taskType = "task_type"
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        taskID = try container.decode(String.self, forKey: .taskID)
        phase = try container.decode(AgentTaskPhase.self, forKey: .phase)
        toolUseID = try container.decodeIfPresent(String.self, forKey: .toolUseID)
        taskType = try container.decodeIfPresent(String.self, forKey: .taskType)
        description = try container.decodeIfPresent(String.self, forKey: .description)
        background = try container.decodeIfPresent(Bool.self, forKey: .background) ?? false
        status = try container.decodeIfPresent(AgentTaskEnd.self, forKey: .status)
    }

    /// The status a finished task leaves its agent or command in.
    public var agentStatus: AgentStatus {
        status == .completed ? .done : .failed
    }
}
