import Foundation

public enum BackgroundKind: String, UnknownSafeEnum {
    /// A subagent started with the Agent tool.
    case agent
    /// A Bash command run in the background.
    case bash
    case unknown
}

/// A subagent or a background command.
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

/// A session's subagents and background commands, oldest first, with their counts.
public struct BackgroundSummary: Codable, Sendable, Hashable {
    public var running: Int
    /// Finished, whether done or failed.
    public var completed: Int
    public var items: [BackgroundItem]

    public static let empty = BackgroundSummary(running: 0, completed: 0, items: [])

    public var runningItems: [BackgroundItem] { items.filter(\.isRunning) }

    /// The Mac's bar above the composer (B76), such as "1 running task".
    public var runningLabel: String {
        let count = runningItems.count
        return count == 1 ? "1 running task" : "\(count) running tasks"
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
    /// A finished subagent's report, when the engine gives one (B46).
    public var summary: String?

    enum CodingKeys: String, CodingKey {
        case phase, description, background, status, summary
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
        summary = try container.decodeIfPresent(String.self, forKey: .summary)
    }

    /// The status a finished task leaves its agent or command in.
    public var agentStatus: AgentStatus {
        status == .completed ? .done : .failed
    }
}
