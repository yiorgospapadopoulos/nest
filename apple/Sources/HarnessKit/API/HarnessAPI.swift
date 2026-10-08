import Foundation

/// Everything the Mac app asks of the daemon. `APIClient` implements it over HTTP;
/// store tests use a fake.
public protocol HarnessAPI: Sendable {
    func repos() async throws -> [Repo]
    func registerRepo(path: String, name: String?) async throws -> Repo
    func openRepo(_ name: String, in app: RepoApp) async throws
    /// The slash commands of the repo's latest agent run, for chats not started yet.
    func repoCommands(_ repo: String) async throws -> CommandList

    func sessions(repo: String?, archived: Bool) async throws -> [Session]
    func session(_ id: String) async throws -> Session
    func createSession(_ request: CreateSessionRequest) async throws -> Session
    func updateSession(_ id: String, _ request: UpdateSessionRequest) async throws -> Session
    func deleteSession(_ id: String) async throws
    /// Stored events with `after < id < before`, oldest first; with a limit, the ones
    /// nearest `before` when it is given, else nearest `after`.
    func sessionEvents(_ id: String, after: Int, before: Int?, limit: Int?) async throws
        -> [Event]
    /// Starts a turn, or queues the message while one runs; `interrupt` stops the running
    /// turn and runs this message next.
    func sendMessage(_ id: String, text: String, attachmentIDs: [String], interrupt: Bool)
        async throws -> SentMessage
    /// Cancels a queued message before its turn starts.
    func cancelQueued(_ id: String, queuedID: String) async throws
    func interrupt(_ id: String) async throws
    /// The session's slash commands, or its repo's while it has none.
    func sessionCommands(_ id: String) async throws -> CommandList
    /// Up to 50 paths relative to the session's folder, for an @ mention.
    func sessionFiles(_ id: String, query: String) async throws -> [String]
    func openInClaudeCode(_ id: String) async throws -> ClaudeCodeLaunch

    /// Claude Code chats harness does not own, newest first; automated ones only when asked.
    func claudeChats(repo: String?, includeAutomated: Bool) async throws -> [ClaudeChat]
    func claudeChat(_ id: String) async throws -> ClaudeChat
    /// The chat's read-only history, as session events numbered from 1.
    func claudeChatEvents(_ id: String) async throws -> [Event]
    /// Archives or unarchives the chat in harness; answers the updated chat.
    func setClaudeChatArchived(_ id: String, archived: Bool) async throws -> ClaudeChat
    /// Continues the chat in harness: the new session, or the one that already continues it.
    func adoptClaudeChat(_ id: String) async throws -> Session

    func diff(_ sessionID: String) async throws -> SessionDiff
    func approve(_ sessionID: String, _ request: ApproveRequest) async throws -> Session
    func reject(_ sessionID: String) async throws -> Session
    func feedback(_ sessionID: String, text: String) async throws -> Session
    /// Merges the session's pull request and closes the session.
    func merge(_ sessionID: String, _ request: MergeRequest) async throws -> Session
    /// Reads the session's pull request from GitHub now.
    func refreshPR(_ sessionID: String) async throws -> Session

    /// Chats whose titles or messages match the query, best match first.
    func search(query: String, repo: String?, limit: Int) async throws -> SearchResults

    func approvals(status: ApprovalStatus?, project: String?) async throws -> [Approval]
    func resolveApproval(_ id: String, _ request: ResolveApprovalRequest) async throws -> Approval

    func uploadAttachment(filename: String, mediaType: String, data: Data) async throws
        -> Attachment

    func connectors() async throws -> [Connector]
    func usageMonth(year: Int, month: Int) async throws -> UsageMonth
    func usageLimits() async throws -> UsageLimits
    /// Asks Claude for the limits now; rate limited within 20 s of the previous ask.
    func refreshUsage() async throws -> UsageLimits
    func usageSettings() async throws -> UsageSettings
    func updateUsageSettings(_ settings: UsageSettings) async throws -> UsageSettings
    func stuckSettings() async throws -> StuckSettings
    func updateStuckSettings(_ settings: StuckSettings) async throws -> StuckSettings
    /// Tells the daemon whether this client is on screen, so it refreshes the limits then.
    func reportVisibility(_ visible: Bool, client: String) async throws

    /// Claude Code's model list, with each model's thinking levels.
    func models() async throws -> ModelList
    /// The Claude login Claude Code uses.
    func account() async throws -> ClaudeAccount
    func agentDefaults() async throws -> AgentDefaults
    func updateAgentDefaults(_ defaults: AgentDefaults) async throws -> AgentDefaults

    func createPairingCode() async throws -> PairingCode
    func devices() async throws -> [Device]
    func revokeDevice(_ id: String) async throws
}

extension HarnessAPI {
    /// Every stored event after `after`.
    public func sessionEvents(_ id: String, after: Int) async throws -> [Event] {
        try await sessionEvents(id, after: after, before: nil, limit: nil)
    }

    public func sendMessage(_ id: String, text: String, attachmentIDs: [String]) async throws
        -> SentMessage
    {
        try await sendMessage(id, text: text, attachmentIDs: attachmentIDs, interrupt: false)
    }
}
