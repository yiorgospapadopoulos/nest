import Foundation

/// Where a folder's run command is (B108).
public enum RunState: String, UnknownSafeEnum {
    /// Never started, or stopped by the user.
    case stopped
    /// Alive, nothing listening yet.
    case starting
    /// Alive and listening on one or more ports.
    case running
    /// Ended on its own; `exit_code` says how.
    case exited
    case unknown
}

/// A folder's port block: `NEST_PORT` is `start`, the rest follow up to `end`.
public struct PortBlock: Codable, Sendable, Hashable {
    public var start: Int
    public var end: Int

    public init(start: Int, end: Int) {
        self.start = start
        self.end = end
    }

    public func contains(_ port: Int) -> Bool {
        start <= port && port <= end
    }
}

/// A chat's folder's run, as `GET /api/sessions/{id}/run` and `run.changed` carry it.
public struct RunStatus: Codable, Sendable, Hashable {
    /// The repo has a run command and the chat's folder exists; otherwise no Run control.
    public var available: Bool
    public var command: String?
    public var folder: String
    /// Nil when no block was free.
    public var block: PortBlock?
    public var state: RunState
    /// Ascending; may hold ports outside the block.
    public var listening: [Int]
    public var exitCode: Int?
    public var startedAt: Date?

    public init(
        available: Bool, command: String?, folder: String, block: PortBlock? = nil,
        state: RunState = .stopped, listening: [Int] = [], exitCode: Int? = nil,
        startedAt: Date? = nil
    ) {
        self.available = available
        self.command = command
        self.folder = folder
        self.block = block
        self.state = state
        self.listening = listening
        self.exitCode = exitCode
        self.startedAt = startedAt
    }

    enum CodingKeys: String, CodingKey {
        case available, command, folder, block, state, listening
        case exitCode = "exit_code"
        case startedAt = "started_at"
    }

    /// The process is alive: starting or running.
    public var isAlive: Bool { state == .starting || state == .running }
}

/// `GET /api/sessions/{id}/run/output`: the last lines the run wrote, raw.
public struct RunOutput: Codable, Sendable, Hashable {
    public var folder: String
    public var text: String

    public init(folder: String, text: String) {
        self.folder = folder
        self.text = text
    }
}

/// `run.changed`: a folder's run changed state or ports.
public struct RunChanged: Decodable, Sendable, Hashable {
    public var folder: String
    public var repo: String
    public var status: RunStatus
}
