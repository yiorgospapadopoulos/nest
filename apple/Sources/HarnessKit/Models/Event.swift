import Foundation

/// An event from the daemon's bus, as `GET /api/sessions/{id}/events` and the websocket
/// deliver it. Ephemeral events (text deltas, some agent snapshots) have no id.
public struct Event: Decodable, Sendable, Hashable {
    public let id: Int?
    public let type: String
    public let ts: Date
    public let sessionID: String?
    public let payload: JSONValue
    /// The payload read as the type's typed body; `.other` for types the app ignores or
    /// payloads it cannot read.
    public let body: EventBody

    enum CodingKeys: String, CodingKey {
        case id, type, ts, payload
        case sessionID = "session_id"
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(Int.self, forKey: .id)
        type = try container.decode(String.self, forKey: .type)
        ts = try container.decode(Date.self, forKey: .ts)
        sessionID = try container.decodeIfPresent(String.self, forKey: .sessionID)
        payload = try container.decode(JSONValue.self, forKey: .payload)
        body = (try? EventBody(type: type, payload: payload)) ?? .other
    }

    /// A message the user sent.
    var isUserMessage: Bool {
        if case .userMessage = body { true } else { false }
    }
}

/// Event type names; a wire contract with the daemon.
public enum EventType {
    public static let sessionCreated = "session.created"
    public static let sessionUpdated = "session.updated"
    public static let sessionState = "session.state"
    public static let sessionUserMessage = "session.user_message"
    public static let sessionMessage = "session.message"
    public static let sessionDelta = "session.delta"
    /// Ephemeral: a main-agent thinking block started (`active` true) or ended.
    public static let sessionThinking = "session.thinking"
    public static let sessionResult = "session.result"
    public static let sessionDeleted = "session.deleted"
    public static let sessionTasks = "session.tasks"
    public static let sessionAgents = "session.agents"
    public static let sessionAgentTask = "session.agent_task"
    public static let sessionContext = "session.context"
    public static let sessionQueued = "session.queued"
    public static let sessionPR = "session.pr"
    public static let sessionStuck = "session.stuck"
    public static let sessionUnstuck = "session.unstuck"
    /// A line from Claude Code for the transcript, such as "Conversation compacted".
    public static let sessionNotice = "session.notice"
    public static let approvalCreated = "approval.created"
    public static let approvalResolved = "approval.resolved"
    public static let gitCommitted = "git.committed"
    public static let gitPushed = "git.pushed"
    public static let gitFailed = "git.failed"
    public static let prOpened = "pr.opened"
    public static let notify = "notify"
    public static let connectorsUpdated = "connectors.updated"
    public static let usageUpdated = "usage.updated"
    public static let claudeChatsUpdated = "claude_chats.updated"
    public static let repoAdded = "repo.added"
    /// A repo's registration changed, such as a plain folder that git now tracks.
    public static let repoUpdated = "repo.updated"
    public static let repoRemoved = "repo.removed"
}

public enum EventBody: Sendable, Hashable {
    case sessionCreated(Session)
    case sessionUpdated(Session)
    case sessionState(SessionState, error: String?)
    case userMessage(UserMessage)
    case message(AgentMessage)
    case delta(String)
    /// A main-agent thinking block started or ended (D045).
    case thinking(active: Bool)
    case result(TurnResult)
    case sessionDeleted(sessionID: String)
    case tasks([TrackedTask])
    /// The agents, with the background summary when the daemon sends one.
    case agents([TrackedAgent], background: BackgroundSummary?)
    /// A subagent or background command started, moved to the background or finished.
    case agentTask(AgentTask)
    /// How full the context window is after a turn.
    case context(SessionContext?)
    /// The whole list of messages waiting for the turn, oldest first.
    case queued([QueuedMessage])
    /// The pull request's status changed on GitHub.
    case pullRequest(PullRequest)
    /// The chat looks stuck, or stuck for another reason now.
    case stuck(StuckFlag)
    /// The chat no longer looks stuck.
    case unstuck(reason: StuckReason)
    case approvalCreated(Approval)
    case approvalResolved(Approval)
    case gitCommitted(sha: String)
    case gitPushed(branch: String)
    case gitFailed(step: String, stderr: String)
    case prOpened(url: String)
    case notify(Notice)
    case connectorsUpdated([Connector])
    case usageUpdated(UsageLimits)
    /// The Claude Code chats of these repos changed; list them again.
    case claudeChatsUpdated(repos: [String])
    /// A repo was registered, changed or removed; the list is read again, whatever the
    /// payload holds.
    case reposChanged
    /// A muted line for the transcript.
    case sessionNotice(text: String)
    case other

    init(type: String, payload: JSONValue) throws {
        func field<T: Decodable>(_ key: String, as _: T.Type) throws -> T {
            try (payload[key] ?? .null).decode(T.self)
        }
        switch type {
        case EventType.sessionCreated:
            self = .sessionCreated(try field("session", as: Session.self))
        case EventType.sessionUpdated:
            self = .sessionUpdated(try field("session", as: Session.self))
        case EventType.sessionState:
            self = .sessionState(
                try field("state", as: SessionState.self),
                error: try field("error", as: String?.self))
        case EventType.sessionUserMessage: self = .userMessage(try payload.decode(UserMessage.self))
        case EventType.sessionMessage: self = .message(try payload.decode(AgentMessage.self))
        case EventType.sessionDelta: self = .delta(try field("text", as: String.self))
        case EventType.sessionThinking:
            self = .thinking(active: payload["active"]?.boolValue == true)
        case EventType.sessionResult: self = .result(try payload.decode(TurnResult.self))
        case EventType.sessionDeleted:
            self = .sessionDeleted(sessionID: try field("session_id", as: String.self))
        case EventType.sessionTasks: self = .tasks(try field("tasks", as: [TrackedTask].self))
        case EventType.sessionAgents:
            self = .agents(
                try field("agents", as: [TrackedAgent].self),
                background: try field("background", as: BackgroundSummary?.self))
        case EventType.sessionAgentTask: self = .agentTask(try payload.decode(AgentTask.self))
        case EventType.sessionContext:
            self = .context(try field("context", as: SessionContext?.self))
        case EventType.sessionQueued: self = .queued(try field("queued", as: [QueuedMessage].self))
        case EventType.sessionPR: self = .pullRequest(try field("pr", as: PullRequest.self))
        case EventType.sessionStuck: self = .stuck(try payload.decode(StuckFlag.self))
        case EventType.sessionUnstuck:
            self = .unstuck(reason: try field("reason", as: StuckReason.self))
        case EventType.approvalCreated:
            self = .approvalCreated(try field("approval", as: Approval.self))
        case EventType.approvalResolved:
            self = .approvalResolved(try field("approval", as: Approval.self))
        case EventType.gitCommitted: self = .gitCommitted(sha: try field("sha", as: String.self))
        case EventType.gitPushed: self = .gitPushed(branch: try field("branch", as: String.self))
        case EventType.gitFailed:
            self = .gitFailed(
                step: try field("step", as: String.self),
                stderr: try field("stderr", as: String.self))
        case EventType.prOpened: self = .prOpened(url: try field("url", as: String.self))
        case EventType.notify: self = .notify(try payload.decode(Notice.self))
        case EventType.connectorsUpdated:
            self = .connectorsUpdated(try field("connectors", as: [Connector].self))
        case EventType.usageUpdated: self = .usageUpdated(try payload.decode(UsageLimits.self))
        case EventType.claudeChatsUpdated:
            self = .claudeChatsUpdated(repos: try field("repos", as: [String].self))
        case EventType.repoAdded, EventType.repoUpdated, EventType.repoRemoved:
            self = .reposChanged
        case EventType.sessionNotice:
            self = .sessionNotice(text: try field("text", as: String.self))
        default: self = .other
        }
    }
}

public struct UserMessage: Decodable, Sendable, Hashable {
    public var text: String
    public var attachments: [Attachment]
}

/// An agent message; subagent messages carry the Agent tool use id they belong to.
public struct AgentMessage: Decodable, Sendable, Hashable {
    public var blocks: [MessageBlock]
    public var parentToolUseID: String?

    enum CodingKeys: String, CodingKey {
        case blocks
        case parentToolUseID = "parent_tool_use_id"
    }
}

public enum MessageBlock: Decodable, Sendable, Hashable {
    case text(String)
    /// Thinking text, with how long it took when the daemon timed it.
    case thinking(String, durationMS: Int?)
    case toolUse(id: String, name: String, input: JSONValue)
    case toolResult(toolUseID: String, content: String, isError: Bool)
    case unknown

    enum CodingKeys: String, CodingKey {
        case type, text, id, name, input, content
        case durationMS = "duration_ms"
        case toolUseID = "tool_use_id"
        case isError = "is_error"
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        switch try container.decode(String.self, forKey: .type) {
        case "text": self = .text(try container.decode(String.self, forKey: .text))
        case "thinking":
            self = .thinking(
                try container.decode(String.self, forKey: .text),
                durationMS: try container.decodeIfPresent(Int.self, forKey: .durationMS))
        case "tool_use":
            self = .toolUse(
                id: try container.decode(String.self, forKey: .id),
                name: try container.decode(String.self, forKey: .name),
                input: try container.decode(JSONValue.self, forKey: .input))
        case "tool_result":
            self = .toolResult(
                toolUseID: try container.decode(String.self, forKey: .toolUseID),
                content: try container.decode(String.self, forKey: .content),
                isError: try container.decodeIfPresent(Bool.self, forKey: .isError) ?? false)
        default: self = .unknown
        }
    }
}

/// The end of one turn.
public struct TurnResult: Decodable, Sendable, Hashable {
    public var isError: Bool
    public var subtype: String
    /// How long the turn took; older events may lack it.
    public var durationMS: Int?
    public var numTurns: Int
    public var costUSD: Double?
    public var errors: [String]

    enum CodingKeys: String, CodingKey {
        case subtype, errors
        case isError = "is_error"
        case durationMS = "duration_ms"
        case numTurns = "num_turns"
        case costUSD = "cost_usd"
    }

    /// The line for a turn that ended in an error: its first error, else its subtype, as
    /// the daemon words the failed state (D045).
    public var failure: String { "Failed: \(errors.first ?? subtype)" }
}

public enum NoticeKind: String, UnknownSafeEnum {
    case needsApproval = "needs_approval"
    case question
    case reviewReady = "review_ready"
    case failed
    case finished
    /// A chat's pull request failed its checks.
    case ciFailed = "ci_failed"
    /// A chat's pull request is green and mergeable.
    case readyToMerge = "ready_to_merge"
    case stuck
    case unknown
}

/// Something the user should hear about (`notify` events).
public struct Notice: Decodable, Sendable, Hashable {
    public var kind: NoticeKind
    public var sessionID: String
    public var repo: String
    public var title: String
    public var text: String

    enum CodingKeys: String, CodingKey {
        case kind, repo, title, text
        case sessionID = "session_id"
    }
}
