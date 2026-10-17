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
    /// Ephemeral: the next piece of thinking text, the main agent's or a subagent's (B59).
    public static let sessionThinkingDelta = "session.thinking_delta"
    /// Ephemeral: the next piece of a subagent's text, under its Agent call (B59).
    public static let sessionSubagentDelta = "session.subagent_delta"
    /// A hook's message or output for the user (B59).
    public static let sessionHook = "session.hook"
    public static let sessionResult = "session.result"
    public static let sessionDeleted = "session.deleted"
    public static let sessionTasks = "session.tasks"
    public static let sessionAgents = "session.agents"
    public static let sessionAgentTask = "session.agent_task"
    /// The chat's group of pixies changed: a call started or ended, or one was sent away
    /// (B46).
    public static let sessionPixies = "session.pixies"
    public static let sessionContext = "session.context"
    public static let sessionQueued = "session.queued"
    /// The conversation was rewound: its events in a range were deleted (B59).
    public static let sessionRewound = "session.rewound"
    public static let sessionPR = "session.pr"
    public static let sessionStuck = "session.stuck"
    public static let sessionUnstuck = "session.unstuck"
    /// A worktree chat's folder, branch and base, once the worktree exists.
    public static let sessionWorkspace = "session.workspace"
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
    /// A limit window reached the warning level (B81).
    public static let usageWarning = "usage.warning"
    /// The Claude Code login changed, or signing in ended (B81).
    public static let accountClaude = "account.claude"
    /// Installing Claude Code moved on.
    public static let claudeCodeInstall = "claude_code.install"
    /// Claude Code was installed: its new state.
    public static let claudeCodeUpdated = "claude_code.updated"
    /// Plugins or marketplaces changed.
    public static let extensionsUpdated = "extensions.updated"
    public static let claudeChatsUpdated = "claude_chats.updated"
    public static let repoAdded = "repo.added"
    /// A repo's registration changed, such as a plain folder that git now tracks.
    public static let repoUpdated = "repo.updated"
    public static let repoRemoved = "repo.removed"
    /// The projects were reordered on some device (D090).
    public static let reposReordered = "repos.reordered"
    public static let pixieUpdated = "pixie.updated"
    public static let pixieDeleted = "pixie.deleted"
    public static let pixieTeamUpdated = "pixie_team.updated"
    public static let pixieTeamDeleted = "pixie_team.deleted"
    /// A card in a pixie's chat for a chat it started or a pull request it reports (B41).
    public static let pixieCard = "pixie.card"
    /// A pixie's habit was made or changed (B42).
    public static let habitUpdated = "habit.updated"
    public static let habitDeleted = "habit.deleted"
    /// A habit run was queued, started or ended.
    public static let habitRunUpdated = "habit.run_updated"
    /// A pixie made a report.
    public static let pixieReport = "pixie.report"
    /// Reports were marked read, here or on another device.
    public static let pixieReportRead = "pixie.report_read"
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
    /// Thinking text to append; `parent` names a subagent's Agent call, nil for the main
    /// agent.
    case thinkingDelta(String, parent: String?)
    /// A subagent's text to append under its Agent call.
    case subagentDelta(String, parent: String)
    case hook(HookRun)
    case result(TurnResult)
    case sessionDeleted(sessionID: String)
    case tasks([TrackedTask])
    /// The agents, with the background summary when the daemon sends one.
    case agents([TrackedAgent], background: BackgroundSummary?)
    /// A subagent or background command started, moved to the background or finished.
    case agentTask(AgentTask)
    /// The chat's whole group of pixies, as `GET /api/sessions/{id}/pixies` lists it.
    case pixieGroup([ChatPixieEntry])
    /// How full the context window is after a turn.
    case context(SessionContext?)
    /// The whole list of messages waiting for the turn, oldest first.
    case queued([QueuedMessage])
    /// The conversation went back to before a user message; its events in the range are
    /// gone.
    case rewound(SessionRewind)
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
    case usageWarning(UsageWarning)
    case claudeAccount(ClaudeLogin)
    case claudeCodeInstall(ClaudeCodeInstallProgress)
    case claudeCodeUpdated(ClaudeCodeStatus)
    /// List the plugins, skills and marketplaces again.
    case extensionsChanged
    /// The Claude Code chats of these repos changed; list them again.
    case claudeChatsUpdated(repos: [String])
    /// A repo was registered, changed or removed, or the repos were reordered; the list is
    /// read again, whatever the payload holds.
    case reposChanged
    /// A muted line for the transcript.
    case sessionNotice(text: String)
    case workspace(SessionWorkspace)
    case pixieUpdated(Pixie)
    case pixieDeleted(String)
    case pixieTeamUpdated(PixieTeam)
    case pixieTeamDeleted(String)
    case pixieCard(PixieCard)
    case habitUpdated(PixieHabit)
    case habitDeleted(id: String, pixieID: String)
    case habitRunUpdated(HabitRun)
    case pixieReport(PixieReport)
    case pixieReportRead(ids: [String])
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
        case EventType.sessionThinkingDelta:
            self = .thinkingDelta(
                try field("text", as: String.self),
                parent: try field("parent_tool_use_id", as: String?.self))
        case EventType.sessionSubagentDelta:
            self = .subagentDelta(
                try field("text", as: String.self),
                parent: try field("parent_tool_use_id", as: String.self))
        case EventType.sessionHook: self = .hook(try payload.decode(HookRun.self))
        case EventType.sessionResult: self = .result(try payload.decode(TurnResult.self))
        case EventType.sessionDeleted:
            self = .sessionDeleted(sessionID: try field("session_id", as: String.self))
        case EventType.sessionTasks: self = .tasks(try field("tasks", as: [TrackedTask].self))
        case EventType.sessionAgents:
            self = .agents(
                try field("agents", as: [TrackedAgent].self),
                background: try field("background", as: BackgroundSummary?.self))
        case EventType.sessionAgentTask: self = .agentTask(try payload.decode(AgentTask.self))
        case EventType.sessionPixies:
            self = .pixieGroup(try field("group", as: [ChatPixieEntry].self))
        case EventType.sessionContext:
            self = .context(try field("context", as: SessionContext?.self))
        case EventType.sessionQueued: self = .queued(try field("queued", as: [QueuedMessage].self))
        case EventType.sessionRewound: self = .rewound(try payload.decode(SessionRewind.self))
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
        case EventType.usageWarning: self = .usageWarning(try payload.decode(UsageWarning.self))
        case EventType.accountClaude: self = .claudeAccount(try payload.decode(ClaudeLogin.self))
        case EventType.claudeCodeInstall:
            self = .claudeCodeInstall(try payload.decode(ClaudeCodeInstallProgress.self))
        case EventType.claudeCodeUpdated:
            self = .claudeCodeUpdated(try payload.decode(ClaudeCodeStatus.self))
        case EventType.extensionsUpdated: self = .extensionsChanged
        case EventType.claudeChatsUpdated:
            self = .claudeChatsUpdated(repos: try field("repos", as: [String].self))
        case EventType.repoAdded, EventType.repoUpdated, EventType.repoRemoved,
            EventType.reposReordered:
            self = .reposChanged
        case EventType.sessionNotice:
            self = .sessionNotice(text: try field("text", as: String.self))
        case EventType.sessionWorkspace:
            self = .workspace(try payload.decode(SessionWorkspace.self))
        case EventType.pixieUpdated: self = .pixieUpdated(try field("pixie", as: Pixie.self))
        case EventType.pixieDeleted: self = .pixieDeleted(try field("pixie_id", as: String.self))
        case EventType.pixieTeamUpdated:
            self = .pixieTeamUpdated(try field("team", as: PixieTeam.self))
        case EventType.pixieTeamDeleted:
            self = .pixieTeamDeleted(try field("id", as: String.self))
        case EventType.pixieCard: self = .pixieCard(try payload.decode(PixieCard.self))
        case EventType.habitUpdated: self = .habitUpdated(try field("habit", as: PixieHabit.self))
        case EventType.habitDeleted:
            self = .habitDeleted(
                id: try field("id", as: String.self),
                pixieID: try field("pixie_id", as: String.self))
        case EventType.habitRunUpdated:
            self = .habitRunUpdated(try field("run", as: HabitRun.self))
        case EventType.pixieReport: self = .pixieReport(try field("report", as: PixieReport.self))
        case EventType.pixieReportRead:
            self = .pixieReportRead(ids: try field("ids", as: [String].self))
        default: self = .other
        }
    }
}

/// `session.rewound`: the daemon deleted the chat's events with ids from `message`
/// through `through`; later ones stay.
public struct SessionRewind: Decodable, Sendable, Hashable {
    /// The rewound user message's event id.
    public var message: Int
    public var through: Int
    public var text: String
    public var attachments: [Attachment]

    public func contains(_ event: Int) -> Bool {
        message <= event && event <= through
    }
}

/// Where a worktree chat works, from `session.workspace`.
public struct SessionWorkspace: Decodable, Sendable, Hashable {
    public var path: String
    public var branch: String?
    public var baseRef: String?

    public init(path: String, branch: String?, baseRef: String?) {
        self.path = path
        self.branch = branch
        self.baseRef = baseRef
    }

    enum CodingKeys: String, CodingKey {
        case path, branch
        case baseRef = "base_ref"
    }
}

/// Where a user message came from, when not from the user typing it.
public enum MessageOrigin: String, UnknownSafeEnum {
    /// The daemon's report that the chats a pixie started have finished (B41).
    case reportBack = "report_back"
    /// A habit run's report, starting a pixie turn so the user can reply in context (B42).
    case report
    /// Nest's message that lets Claude continue after the usage limit reset (B78).
    case limitResume = "limit_resume"
    case unknown
}

public struct UserMessage: Decodable, Sendable, Hashable {
    public var text: String
    public var attachments: [Attachment]
    /// The pixie that sent it into this chat with its tools (B41).
    public var fromPixie: String?
    public var origin: MessageOrigin?

    enum CodingKeys: String, CodingKey {
        case text, attachments, origin
        case fromPixie = "from_pixie"
    }
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
    /// `images` are attachments the result carries (B59).
    case toolResult(toolUseID: String, content: String, isError: Bool, images: [ToolImage] = [])
    case unknown

    enum CodingKeys: String, CodingKey {
        case type, text, id, name, input, content, images
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
                isError: try container.decodeIfPresent(Bool.self, forKey: .isError) ?? false,
                images: try container.decodeIfPresent([ToolImage].self, forKey: .images) ?? [])
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
    public var errors: [String]
    /// The turn ended only to make way for the next message (Send now, or Claude Code
    /// ending it holding that message), so its error is no failure (B59).
    public var handoff: Bool
    /// The user stopped the turn: its error is no failure, the stopped line says it (B59).
    public var stopped: Bool
    /// The usage limit cut the turn off: its error is no failure, the chat is paused (B78).
    public var limit: Bool

    enum CodingKeys: String, CodingKey {
        case subtype, errors, handoff, stopped, limit
        case isError = "is_error"
        case durationMS = "duration_ms"
        case numTurns = "num_turns"
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        isError = try container.decode(Bool.self, forKey: .isError)
        subtype = try container.decode(String.self, forKey: .subtype)
        durationMS = try container.decodeIfPresent(Int.self, forKey: .durationMS)
        numTurns = try container.decode(Int.self, forKey: .numTurns)
        errors = try container.decode([String].self, forKey: .errors)
        handoff = try container.decodeIfPresent(Bool.self, forKey: .handoff) ?? false
        stopped = try container.decodeIfPresent(Bool.self, forKey: .stopped) ?? false
        limit = try container.decodeIfPresent(Bool.self, forKey: .limit) ?? false
    }

    /// Whether the turn failed: an error result that neither handed off, was stopped nor
    /// met the usage limit.
    public var failed: Bool { isError && !handoff && !stopped && !limit }

    /// The line for a turn that ended in an error: its first error, else its subtype, as
    /// the daemon words the failed state (D045).
    public var failure: String { "Failed: \(errors.first ?? subtype)" }
}

public enum HookOutcome: String, UnknownSafeEnum {
    case success, error, cancelled
    case unknown
}

/// A hook that had something to say, from `session.hook`: its message for the user, what
/// it printed, or why it failed. Shown as a muted line like Claude Code's.
public struct HookRun: Decodable, Sendable, Hashable {
    /// The event and what it matched, such as `PostToolUse:Edit`.
    public var name: String
    public var event: String
    public var outcome: HookOutcome
    public var exitCode: Int?
    public var systemMessage: String?
    public var output: String?

    public init(
        name: String, event: String, outcome: HookOutcome, exitCode: Int?,
        systemMessage: String?, output: String?
    ) {
        self.name = name
        self.event = event
        self.outcome = outcome
        self.exitCode = exitCode
        self.systemMessage = systemMessage
        self.output = output
    }

    enum CodingKeys: String, CodingKey {
        case outcome, output
        case name = "hook_name"
        case event = "hook_event"
        case exitCode = "exit_code"
        case systemMessage = "system_message"
    }

    public var isFailure: Bool { outcome == .error }

    /// Whether Claude Code would show it: a message for the user, or a hook that did not
    /// succeed. A successful hook's output was context for Claude (SessionStart,
    /// UserPromptSubmit); the daemon no longer sends it, older chats stored it (B59).
    public var isShown: Bool {
        systemMessage != nil || outcome != .success || (exitCode ?? 0) != 0
    }

    /// "PreToolUse:Bash hook failed (exit 2)", "PostToolUse:Edit says: Formatted 2 files",
    /// or "PostToolUse:Edit hook output".
    public var title: String {
        if isFailure {
            return "\(name) hook failed" + (exitCode.map { " (exit \($0))" } ?? "")
        }
        return systemMessage.map { "\(name) says: \($0)" } ?? "\(name) hook output"
    }

    /// What the line opens to: the output, and on a failure its message first.
    public var detail: String? {
        let parts = isFailure ? [systemMessage, output] : [output]
        let text = parts.compactMap { $0 }.joined(separator: "\n")
        return text.isEmpty ? nil : text
    }
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
    /// A pixie's report (B42); the Mac posts these from `pixie.report` events.
    case pixieReport = "pixie_report"
    /// A chat paused at the usage limit, in place of `finished` for that turn (B78).
    case usageLimit = "usage_limit"
    case unknown
}

/// Something the user should hear about (`notify` events).
public struct Notice: Decodable, Sendable, Hashable {
    public var kind: NoticeKind
    public var sessionID: String
    public var repo: String
    public var title: String
    public var text: String
    /// The pixie's name, on a pixie's notices such as `pixie_report` (B42).
    public var pixieName: String?

    enum CodingKeys: String, CodingKey {
        case kind, repo, title, text
        case sessionID = "session_id"
        case pixieName = "pixie_name"
    }
}
