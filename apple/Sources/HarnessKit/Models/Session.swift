import Foundation

public enum SessionState: String, UnknownSafeEnum {
    /// Creating the worktree and running setup.
    case starting
    /// A turn is in progress.
    case running
    /// A permission prompt or question is pending.
    case waiting
    /// The turn finished; waiting for the user.
    case idle
    /// A turn was cut off by an interrupt or a daemon restart.
    case interrupted
    case failed
    case closed
    case unknown

    /// The agent is working, so the session cannot be approved yet.
    public var isInFlight: Bool {
        self == .starting || self == .running || self == .waiting
    }
}

public enum SessionMode: String, UnknownSafeEnum {
    case worktree
    case inPlace = "in_place"
    case unknown
}

public enum Effort: String, UnknownSafeEnum {
    case low, medium, high, xhigh, max
    case unknown

    public static let selectable: [Effort] = [.low, .medium, .high, .xhigh, .max]
}

public enum PermissionMode: String, UnknownSafeEnum {
    case `default`
    case acceptEdits
    case bypassPermissions
    case plan
    case unknown

    public static let selectable: [PermissionMode] = [
        .default, .acceptEdits, .plan, .bypassPermissions,
    ]

    /// The short label the composer shows.
    public var label: String {
        switch self {
        case .default: "Ask"
        case .acceptEdits: "Accept edits"
        case .bypassPermissions: "Bypass"
        case .plan: "Plan"
        case .unknown: "Unknown"
        }
    }
}

/// An agent session (a chat). Detail responses also carry its tasks, agents, background
/// work and queued messages.
public struct Session: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var repo: String
    public var title: String
    public var prompt: String
    public var mode: SessionMode
    public var cwd: String?
    public var model: String?
    public var effort: Effort?
    public var permissionMode: PermissionMode
    public var provider: String
    public var baseRef: String?
    public var state: SessionState
    public var worktreePath: String?
    public var branch: String?
    public var providerSessionID: String?
    public var gitViolation: Bool
    public var createdAt: Date
    public var updatedAt: Date
    public var lastError: String?
    public var commitSHA: String?
    public var prURL: String?
    /// The pull request's last known status; nil before harness first reads it.
    public var pr: PullRequest?
    /// Up to three lines on the pull request: the agent's summary and the diff stats.
    public var prSummary: String?
    public var allowedTools: [String]
    public var pinned: Bool
    public var archivedAt: Date?
    /// How full the context window was after the last turn; nil before the first.
    public var context: SessionContext?
    /// Why the running chat looks stuck, while it does (D036).
    public var stuck: StuckFlag?
    /// Only in `GET /api/sessions/{id}`.
    public var tasks: [TrackedTask]?
    public var agents: [TrackedAgent]?
    public var background: BackgroundSummary?
    /// Messages waiting for the running turn to end, oldest first.
    public var queued: [QueuedMessage]?

    public var isArchived: Bool { archivedAt != nil }

    /// The folder the agent works in: its worktree, else the folder it runs in.
    public var folder: String? { worktreePath ?? cwd }

    enum CodingKeys: String, CodingKey {
        case id, repo, title, prompt, mode, cwd, model, effort, provider, state, branch, pinned
        case pr
        case prSummary = "pr_summary"
        case tasks, agents, background, context, queued, stuck
        case permissionMode = "permission_mode"
        case baseRef = "base_ref"
        case worktreePath = "worktree_path"
        case providerSessionID = "provider_session_id"
        case gitViolation = "git_violation"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case lastError = "last_error"
        case commitSHA = "commit_sha"
        case prURL = "pr_url"
        case allowedTools = "allowed_tools"
        case archivedAt = "archived_at"
    }
}

public enum TaskStatus: String, UnknownSafeEnum {
    case pending
    case inProgress = "in_progress"
    case completed
    case deleted
    case unknown
}

/// One entry of the main agent's task list.
public struct TrackedTask: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var subject: String
    public var description: String?
    public var activeForm: String?
    public var status: TaskStatus

    enum CodingKeys: String, CodingKey {
        case id, subject, description, status
        case activeForm = "active_form"
    }
}

public enum AgentStatus: String, UnknownSafeEnum {
    case running, done, failed
    case unknown
}

/// One tool call of an agent.
public struct AgentStep: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var tool: String
    public var arg: String
    public var result: String?
}

/// The main agent (id "main") or a subagent, identified by its Agent tool use id.
public struct TrackedAgent: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var name: String
    public var description: String?
    public var status: AgentStatus
    /// The latest tool call while running, such as "Edit src/x.ts".
    public var activity: String?
    public var startedAt: Date?
    public var finishedAt: Date?
    public var steps: [AgentStep]

    public var isMain: Bool { id == "main" }

    enum CodingKeys: String, CodingKey {
        case id, name, description, status, activity, steps
        case startedAt = "started_at"
        case finishedAt = "finished_at"
    }
}
