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
    /// The repo's open GitHub issues, newest updated first: all, or the user's; nil leaves
    /// it to the repo's setting. `refresh` skips the daemon's short cache (B101).
    func issues(repo: String, refresh: Bool, show: IssueShow?) async throws -> IssueList

    func sessions(repo: String?, archived: Bool) async throws -> [Session]
    func session(_ id: String) async throws -> Session
    /// The repo's chats that are working or have tasks left in their visible list, working
    /// ones first, then the most recently updated (D092).
    func goals(repo: String) async throws -> [SessionGoals]
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
    /// Ends a usage limit pause now; the chat goes on at once (B78).
    func resumeLimit(_ id: String) async throws -> Session
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
    /// The daemon sends the pull request's pending review comments to the chat, or only
    /// those `ids`, and marks them sent (B101).
    func reviewFeedback(_ id: String, ids: [String]?) async throws
    /// Whether new review comments go to the agent as they arrive; answers the session.
    func setReviewAutoSend(_ id: String, _ on: Bool) async throws -> Session

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
    func usagePeriod(unit: UsageUnit, date: CalendarDay) async throws -> UsagePeriod
    func usageLimits() async throws -> UsageLimits
    func usageSettings() async throws -> UsageSettings
    func updateUsageSettings(_ settings: UsageSettings) async throws -> UsageSettings
    func stuckSettings() async throws -> StuckSettings
    func updateStuckSettings(_ settings: StuckSettings) async throws -> StuckSettings
    /// Tells the daemon whether this client is on screen, so it refreshes the limits then.
    func reportVisibility(_ visible: Bool, client: String) async throws

    /// Claude Code's model list, with each model's thinking levels.
    func models() async throws -> ModelList
    /// Another engine's model list, such as Codex's (B91).
    func models(provider: String) async throws -> ModelList
    /// The engines a new chat can run on; `refresh` asks for their login now (B91).
    func providers(refresh: Bool) async throws -> ProviderList
    /// The Claude login Claude Code uses.
    func account() async throws -> ClaudeAccount
    func agentDefaults() async throws -> AgentDefaults
    func updateAgentDefaults(_ defaults: AgentDefaults) async throws -> AgentDefaults

    func pixies() async throws -> [Pixie]
    /// Every skill a pixie may be given, standalone and from plugins, by name (B85).
    func pixieSkills() async throws -> [PixieSkillChoice]
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

    /// Every chat's group of pixies, by session id; chats with none are left out (B46).
    func pixieGroups() async throws -> [String: [ChatPixieEntry]]
    /// The pixies and teams the chat called and did not send away, first called first.
    func chatPixies(_ id: String) async throws -> [ChatPixieEntry]
    /// The pixie, or the team with its members, leaves the chat's group and its next call
    /// starts fresh; answers the group.
    func sendAway(_ id: String, _ request: SendAwayRequest) async throws -> [ChatPixieEntry]
    /// Every call of the pixie in the chat, newest first, with its work.
    func pixieCallWork(_ id: String, pixie: String) async throws -> [PixieCallWork]
    /// A subagent's own transcript so far, by its Agent call; `notFound` for a call the
    /// chat did not make.
    func agentTranscript(_ id: String, toolUseID: String) async throws -> AgentWork

    /// Artifacts newest first, at most 500; the filters combine (B79).
    func artifacts(repo: String?, sessionID: String?, pixieID: String?) async throws
        -> [Artifact]
    /// How many artifacts' latest versions the user has not opened, in every project.
    func unseenArtifacts() async throws -> Int
    func artifact(_ id: String) async throws -> ArtifactDetail
    func artifactContent(_ id: String, version: Int) async throws -> ArtifactContent
    /// The user opened its latest version; answers the artifact.
    func markArtifactSeen(_ id: String) async throws -> Artifact
    /// The user's edit of a document as a new version, made from `baseVersion`; a 409
    /// (`APIError.conflict`) when that is no longer the latest (B88).
    /// What the artifact's page stored (B88).
    func artifactStorage(_ id: String) async throws -> ArtifactStorage
    /// Sets and removes keys at once and answers the new size; over a cap is
    /// `APIError.payloadTooLarge`.
    func writeArtifactStorage(_ id: String, set: [String: String], remove: [String])
        async throws -> Int
    func clearArtifactStorage(_ id: String) async throws
    /// A page's small request to Claude: 429 is the day's limit used, 403 asking turned
    /// off, 409 an ask already running for the artifact.
    func askStatus(_ id: String) async throws -> ArtifactAskStatus
    func askArtifact(_ id: String, prompt: String, system: String?) async throws
        -> ArtifactAnswer
    func saveArtifactVersion(_ id: String, content: String, baseVersion: Int) async throws
        -> ArtifactVersion
    /// Removes it with every version.
    func deleteArtifact(_ id: String) async throws

    func createPairingCode() async throws -> PairingCode
    func devices() async throws -> [Device]
    func revokeDevice(_ id: String) async throws
    /// How many devices get push notifications (B81).
    func pushStatus() async throws -> PushStatus

    // MARK: Settings (B81)

    /// The repo's local branches, for its default branch.
    func repoBranches(_ name: String) async throws -> [String]
    /// The repo's branches and worktrees, each with the branch it comes from (B96).
    func repoBranchMap(_ name: String) async throws -> BranchMap
    func storage() async throws -> StorageUsage
    func storageSettings() async throws -> StorageSettings
    func updateStorageSettings(_ settings: StorageSettings) async throws -> StorageSettings
    /// The largest attachments, largest first.
    func largeAttachments(limit: Int) async throws -> [LargeAttachment]
    func deleteAttachment(_ id: String) async throws
    /// Clears the search index and builds it again in the background.
    func rebuildSearch() async throws
    func pixieSettings() async throws -> PixieSettings
    func updatePixieSettings(_ settings: PixieSettings) async throws -> PixieSettings
    /// The daemon's notification rules (B85: the pixie report level).
    func notificationRules() async throws -> NotificationRules
    /// Replaces the whole section; answers what was saved.
    func updateNotificationRules(_ rules: NotificationRules) async throws -> NotificationRules
    func githubAccount() async throws -> GitHubAccount
    /// Asks `gh` again.
    func checkGitHubAccount() async throws -> GitHubAccount
    /// Every engine's accounts (B98), Claude's first, each engine's in the user's order.
    func engineAccounts() async throws -> [EngineAccount]
    /// Adds an account at the end and starts its sign-in: Claude's opens the browser on the
    /// Mac, Codex's answers the page to open; `accounts.changed` tells the outcome.
    func addAccount(provider: String) async throws -> AccountSignIn
    /// Signs in to the account again.
    func signInAccount(_ id: String) async throws -> AccountSignIn
    func cancelAccountSignIn(_ id: String) async throws
    func signOutAccount(_ id: String) async throws -> EngineAccount
    /// Nil clears the user's name.
    func renameAccount(_ id: String, name: String?) async throws -> EngineAccount
    /// Turns from the next one run on this account; it must be signed in.
    func activateAccount(_ id: String) async throws -> [EngineAccount]
    /// Signs out of an added account and deletes it; the first account cannot be removed.
    func removeAccount(_ id: String) async throws -> [EngineAccount]
    /// Asks every signed-in account for its limits now.
    func refreshAccounts() async throws -> [EngineAccount]
    /// A Codex account's banked resets with their details.
    func bankedResets(_ id: String) async throws -> BankedResets
    /// Uses one of a signed-in Codex account's banked resets on its limits now.
    func useBankedReset(_ id: String, creditID: String) async throws -> BankedResetUse
    func claudeCode() async throws -> ClaudeCodeStatus
    /// Runs Anthropic's installer; `claude_code.install` events tell how it goes.
    func installClaudeCode() async throws
    /// The installed Claude Code plugins.
    func plugins() async throws -> [InstalledPlugin]
    /// The skills in `~/.claude/skills`.
    func standaloneSkills() async throws -> [StandaloneSkill]
    func marketplaces() async throws -> [PluginMarketplace]
    /// Adds a marketplace from a URL, a path or a GitHub repo.
    func addMarketplace(source: String) async throws
    func removeMarketplace(_ name: String) async throws
    /// Every plugin the marketplaces offer.
    func availablePlugins() async throws -> [AvailablePlugin]
    func pluginDetails(_ id: String) async throws -> PluginDetails
    func installPlugin(_ id: String) async throws
    func uninstallPlugin(_ id: String) async throws
    func setPluginEnabled(_ id: String, enabled: Bool) async throws

    // MARK: Configuration (B97)

    /// The shared instructions, skills and MCP servers, and each signed-in engine's setup.
    func configuration() async throws -> ConfigurationPage
    /// A file on the configuration allow-list; a missing one reads as empty.
    func configurationFile(path: String) async throws -> ConfigFile
    /// Writes the file and answers its new version; `APIError.conflict` when it changed
    /// since `expectedVersion`.
    func saveConfigurationFile(path: String, text: String, expectedVersion: String?)
        async throws -> String
    func setUsesShared(engine: String, item: SharedItem, on: Bool) async throws
        -> ConfigurationPage
    /// A new skill in the shared folder.
    func createSkill(name: String, description: String) async throws -> ConfigurationPage
    func deleteSkill(_ name: String) async throws -> ConfigurationPage
    /// Moves a skill found only in the engine's own folder into the shared one.
    func makeSkillShared(_ name: String, engine: String) async throws -> ConfigurationPage
    /// Whether Codex loads the skill.
    func setSkillEnabled(_ name: String, codex enabled: Bool) async throws -> ConfigurationPage
    /// Creates or replaces the server in every engine that shares MCP servers.
    func saveMCPServer(_ name: String, _ spec: MCPServerSpec) async throws -> ConfigurationPage
    func deleteMCPServer(_ name: String) async throws -> ConfigurationPage
    /// The server as Claude stores it, for the edit form.
    func mcpServer(_ name: String) async throws -> MCPServerSpec
    func copyPreview(engine: String) async throws -> CopyPreview
    /// Copies the engine's setup to Shared; `instructions` false keeps Shared's.
    func copyToShared(engine: String, instructions: Bool) async throws -> CopyResult
    func undoCopy(_ id: String) async throws -> ConfigurationPage
    func repoConfiguration(_ repo: String) async throws -> RepoConfiguration
    /// Writes the server into the repo's `.mcp.json`.
    func saveRepoMCPServer(_ repo: String, _ name: String, _ spec: MCPServerSpec) async throws
    func deleteRepoMCPServer(_ repo: String, _ name: String) async throws
    /// A new skill in the repo's `.claude/skills`.
    func createRepoSkill(_ repo: String, name: String, description: String) async throws
    /// Codex's own plugins, installed and offered, matching the query.
    func codexPlugins(query: String) async throws -> [CodexPlugin]
    func installCodexPlugin(_ id: String) async throws
    func uninstallCodexPlugin(_ id: String) async throws
    func codexMarketplaces() async throws -> [CodexMarketplace]
    func addCodexMarketplace(source: String) async throws
    func removeCodexMarketplace(_ name: String) async throws

    // MARK: Local models (B106)

    /// The added local models, the engine local chats run on and the local-only choice.
    func localModels() async throws -> LocalModelList
    /// Running servers on this Mac and models waiting in the model folders.
    func findLocalModels() async throws -> LocalFind
    /// Whether the server at the address can run agents, and its models.
    func checkLocalServer(address: String, key: String?) async throws -> LocalCheck
    /// Adds the server's models, by their ids on the server; answers them added.
    func addLocalModels(address: String, key: String?, models: [String]) async throws
        -> [LocalModel]
    func removeLocalModel(_ id: String) async throws
    /// The engine new local chats run on: "claude" or "codex".
    func setLocalEngine(_ engine: String) async throws
    /// Starts the app's server; `notFound` when the app is not installed.
    func startLocalServer(_ app: LocalApp) async throws
    func localUsage() async throws -> LocalUsage
    /// Whether to show the first-run welcome.
    func setup() async throws -> SetupState
    /// The user chose local models only; the welcome is done.
    func useLocalOnly() async throws
    func finishSetup() async throws
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
