import Foundation

/// Everything the Mac app asks of the daemon. `APIClient` implements it over HTTP;
/// store tests use a fake.
public protocol NestAPI: Sendable {
    func repos() async throws -> [Repo]
    func registerRepo(path: String, name: String?) async throws -> Repo
    func openRepo(_ name: String, in app: RepoApp) async throws
    /// The slash commands of the repo's latest agent run, for chats not started yet.
    func repoCommands(_ repo: String) async throws -> CommandList
    /// Unregisters the repo; `purgeSessions` deletes its chats first. The folder stays.
    func removeRepo(_ name: String, purgeSessions: Bool) async throws
    /// Changes only the repo settings the patch names: its worktree default, links or
    /// setup commands.
    func updateRepo(_ name: String, _ patch: RepoPatch) async throws -> Repo
    /// Gitignored files in the checkout worth linking into worktrees.
    func linkSuggestions(_ name: String) async throws -> [String]
    /// Saves the project order every device shows (D090); answers the repos in that order.
    func reorderRepos(_ order: [String]) async throws -> [Repo]

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
    /// Removes a pending message Claude has not read yet; `messageTaken` when it has.
    func cancelQueued(_ id: String, queuedID: String) async throws
    /// Sends a pending message now: the running turn stops and it starts right after.
    func sendQueuedNow(_ id: String, queuedID: String) async throws
    /// Runs a `!` command in the chat's folder; answers even when the command fails.
    func runShell(_ id: String, command: String) async throws -> ShellRun
    /// Appends a `#` memory to the project's or the user's CLAUDE.md.
    func saveMemory(_ id: String, text: String, scope: MemoryScope) async throws
        -> SavedMemory
    /// An attachment's bytes, such as a tool result's image.
    func attachmentData(_ id: String) async throws -> Data
    func interrupt(_ id: String) async throws
    /// Stops one background task or subagent by its task id or the id of the tool call
    /// that started it; the turn goes on (B59).
    func stopTask(_ id: String, task: String) async throws
    /// The session's slash commands, or its repo's while it has none.
    func sessionCommands(_ id: String) async throws -> CommandList
    /// Up to 50 paths relative to the session's folder, for an @ mention.
    func sessionFiles(_ id: String, query: String) async throws -> [String]
    func openInClaudeCode(_ id: String) async throws -> ClaudeCodeLaunch
    /// What rewinding to before a user message (by event id) would change.
    func rewindPreview(_ id: String, message: Int, restore: RewindRestore) async throws
        -> RewindPreview
    /// Rewinds the files, the conversation or both to before a user message; no turn may
    /// run. A conversation rewind answers the message for the composer.
    func rewind(_ id: String, message: Int, restore: RewindRestore) async throws
        -> RewindPreview
    /// A new chat continuing the conversation as it was before a user message.
    func fork(_ id: String, message: Int) async throws -> ForkedChat
    /// The daemon reads the failing checks' logs with its own GitHub login and sends them
    /// to the chat.
    func ciFeedback(_ id: String) async throws

    /// Claude Code chats Nest does not own, newest first; automated ones only when asked.
    func claudeChats(repo: String?, includeAutomated: Bool) async throws -> [ClaudeChat]
    func claudeChat(_ id: String) async throws -> ClaudeChat
    /// The chat's read-only history, as session events numbered from 1.
    func claudeChatEvents(_ id: String) async throws -> [Event]
    /// Archives or unarchives the chat in Nest; answers the updated chat.
    func setClaudeChatArchived(_ id: String, archived: Bool) async throws -> ClaudeChat
    /// Continues the chat in Nest: the new session, or the one that already continues it.
    func adoptClaudeChat(_ id: String) async throws -> Session

    func diff(_ sessionID: String) async throws -> SessionDiff
    func approve(_ sessionID: String, _ request: ApproveRequest) async throws -> Session
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

    func pixies() async throws -> [Pixie]
    func createPixie(_ request: CreatePixieRequest) async throws -> Pixie
    func updatePixie(_ id: String, _ request: UpdatePixieRequest) async throws -> Pixie
    /// Names every pixie once, in the new order; answers them all in that order.
    func reorderPixies(_ ids: [String]) async throws -> [Pixie]
    /// Stops the pixie's run and removes its chat and folder.
    func deletePixie(_ id: String) async throws
    /// Sends the text into the pixie's chat; answers the chat, and the queued message when
    /// the chat was busy.
    func sendToPixie(_ id: String, text: String) async throws -> SentMessage
    /// Opens a fresh run for the pixie's chat.
    func resetPixie(_ id: String) async throws -> Pixie
    /// A file of the pixie's folder, such as `soul` or `notes/ideas`.
    func pixieFile(_ id: String, name: String) async throws -> PixieFile
    /// Writes the file; the hash must be the one read, else the call fails with
    /// `APIError.staleFile`.
    func savePixieFile(_ id: String, name: String, text: String, hash: String?) async throws
        -> PixieFile
    func pixieNotes(_ id: String) async throws -> [String]
    func searchPixie(_ id: String, query: String) async throws -> [PixieSearchHit]
    /// What the pixie did with its Nest tools, newest first (B41).
    func pixieActivity(_ id: String) async throws -> [PixieActivityEntry]
    /// The pixie's habits, oldest first (B42).
    func pixieHabits(_ id: String) async throws -> [PixieHabit]
    func createHabit(_ pixie: String, _ request: CreateHabitRequest) async throws -> PixieHabit
    func updateHabit(_ pixie: String, _ habit: String, _ request: UpdateHabitRequest)
        async throws -> PixieHabit
    /// Cancels its queued runs too.
    func deleteHabit(_ pixie: String, _ habit: String) async throws
    /// Run now: queues a run that ignores lateness and the usage guard.
    func runHabit(_ pixie: String, _ habit: String) async throws -> HabitRun
    /// The latest 20 runs, newest first, plus any queued or running.
    func habitRuns(_ pixie: String, _ habit: String) async throws -> [HabitRun]
    /// Every pixie's reports, newest first, the latest 200; only unread ones when asked.
    func pixieReports(unread: Bool) async throws -> [PixieReport]
    func markReportRead(_ id: String) async throws
    /// Marks all of a pixie's reports read.
    func markPixieReportsRead(_ id: String) async throws
    /// A copy right after the original, in its team, with its settings, soul, memory, notes
    /// and archive; not its chat.
    func duplicatePixie(_ id: String) async throws -> Pixie
    /// The teams, in their order.
    func pixieTeams() async throws -> [PixieTeam]
    func createPixieTeam(_ request: CreatePixieTeamRequest) async throws -> PixieTeam
    func updatePixieTeam(_ id: String, _ request: UpdatePixieTeamRequest) async throws
        -> PixieTeam
    /// Its pixies stay, without a team.
    func deletePixieTeam(_ id: String) async throws

    func createPairingCode() async throws -> PairingCode
    func devices() async throws -> [Device]
    func revokeDevice(_ id: String) async throws
}

extension NestAPI {
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
