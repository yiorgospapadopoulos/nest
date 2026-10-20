import Foundation

/// The daemon's HTTP API with the device's bearer token.
public struct APIClient: NestAPI {
    public static let defaultBaseURL = URL(string: "http://127.0.0.1:8765")!

    public let baseURL: URL
    let deviceToken: DeviceToken
    let transport: any HTTPTransport

    public init(
        token: String, baseURL: URL = APIClient.defaultBaseURL,
        transport: any HTTPTransport = URLSessionTransport()
    ) {
        self.init(token: DeviceToken(token), baseURL: baseURL, transport: transport)
    }

    init(token: DeviceToken, baseURL: URL, transport: any HTTPTransport = URLSessionTransport()) {
        deviceToken = token
        self.baseURL = baseURL
        self.transport = transport
    }

    var token: String { deviceToken.current }

    // MARK: Repos

    public func repos() async throws -> [Repo] {
        try await get("repos")
    }

    public func registerRepo(path: String, name: String?) async throws -> Repo {
        try await call("POST", ["repos"], body: RegisterRepoRequest(path: path, name: name))
    }

    public func openRepo(_ name: String, in app: RepoApp) async throws {
        try await perform("POST", ["repos", name, "open"], body: OpenRepoRequest(app: app))
    }

    public func repoCommands(_ repo: String) async throws -> CommandList {
        try await get("repos", repo, "commands")
    }

    public func removeRepo(_ name: String, purgeSessions: Bool) async throws {
        let query = purgeSessions ? [URLQueryItem(name: "purge_sessions", value: "true")] : []
        try await perform("DELETE", ["repos", name], query: query)
    }

    public func updateRepo(_ name: String, _ patch: RepoPatch) async throws -> Repo {
        try await call("PATCH", ["repos", name], body: patch)
    }

    public func linkSuggestions(_ name: String) async throws -> [String] {
        try await get("repos", name, "link-suggestions")
    }

    public func reorderRepos(_ order: [String]) async throws -> [Repo] {
        try await call("PUT", ["repos", "order"], body: RepoOrderRequest(order: order))
    }

    // MARK: Sessions

    public func sessions(repo: String?, archived: Bool) async throws -> [Session] {
        var query = [URLQueryItem(name: "archived", value: archived ? "true" : "false")]
        if let repo {
            query.insert(URLQueryItem(name: "repo", value: repo), at: 0)
        }
        return try await call("GET", ["sessions"], query: query)
    }

    public func session(_ id: String) async throws -> Session {
        try await get("sessions", id)
    }

    public func goals(repo: String) async throws -> [SessionGoals] {
        try await call("GET", ["goals"], query: [URLQueryItem(name: "repo", value: repo)])
    }

    public func createSession(_ request: CreateSessionRequest) async throws -> Session {
        try await call("POST", ["sessions"], body: request)
    }

    public func updateSession(_ id: String, _ request: UpdateSessionRequest) async throws
        -> Session
    {
        try await call("PATCH", ["sessions", id], body: request)
    }

    /// Deletes the session for good, with its worktree and history; its branch stays.
    public func deleteSession(_ id: String) async throws {
        try await perform(
            "DELETE", ["sessions", id], query: [URLQueryItem(name: "purge", value: "true")])
    }

    public func sessionEvents(_ id: String, after: Int, before: Int?, limit: Int?) async throws
        -> [Event]
    {
        var query = [URLQueryItem(name: "after", value: "\(after)")]
        if let before {
            query.append(URLQueryItem(name: "before", value: "\(before)"))
        }
        if let limit {
            query.append(URLQueryItem(name: "limit", value: "\(limit)"))
        }
        return try await call("GET", ["sessions", id, "events"], query: query)
    }

    public func sendMessage(
        _ id: String, text: String, attachmentIDs: [String], interrupt: Bool
    ) async throws -> SentMessage {
        let body = MessageRequest(
            text: text, attachmentIDs: attachmentIDs, interrupt: interrupt ? true : nil)
        return try await call("POST", ["sessions", id, "messages"], body: body)
    }

    public func cancelQueued(_ id: String, queuedID: String) async throws {
        try await perform("DELETE", ["sessions", id, "queue", queuedID])
    }

    public func runShell(_ id: String, command: String) async throws -> ShellRun {
        try await call("POST", ["sessions", id, "shell"], body: ShellRequest(command: command))
    }

    public func saveMemory(_ id: String, text: String, scope: MemoryScope) async throws
        -> SavedMemory
    {
        try await call(
            "POST", ["sessions", id, "memory"], body: MemoryRequest(text: text, scope: scope))
    }

    public func attachmentData(_ id: String) async throws -> Data {
        try await send(try encodedRequest("GET", ["attachments", id], query: [], body: nil)).body
    }

    public func sendQueuedNow(_ id: String, queuedID: String) async throws {
        try await perform("POST", ["sessions", id, "queue", queuedID, "send-now"])
    }

    public func interrupt(_ id: String) async throws {
        try await perform("POST", ["sessions", id, "interrupt"])
    }

    public func resumeLimit(_ id: String) async throws -> Session {
        try await call("POST", ["sessions", id, "limit", "resume"])
    }

    public func stopTask(_ id: String, task: String) async throws {
        try await perform("POST", ["sessions", id, "tasks", task, "stop"])
    }

    public func sessionCommands(_ id: String) async throws -> CommandList {
        try await get("sessions", id, "commands")
    }

    public func sessionFiles(_ id: String, query: String) async throws -> [String] {
        let list: FileList = try await call(
            "GET", ["sessions", id, "files"], query: [URLQueryItem(name: "q", value: query)])
        return list.files
    }

    public func openInClaudeCode(_ id: String) async throws -> ClaudeCodeLaunch {
        try await call("POST", ["sessions", id, "open-in-claude-code"])
    }

    public func rewindPreview(_ id: String, message: Int, restore: RewindRestore) async throws
        -> RewindPreview
    {
        try await call(
            "GET", ["sessions", id, "rewind"],
            query: [
                URLQueryItem(name: "message", value: "\(message)"),
                URLQueryItem(name: "restore", value: restore.rawValue),
            ])
    }

    public func rewind(_ id: String, message: Int, restore: RewindRestore) async throws
        -> RewindPreview
    {
        try await call(
            "POST", ["sessions", id, "rewind"],
            body: RewindRequest(message: message, restore: restore))
    }

    public func fork(_ id: String, message: Int) async throws -> ForkedChat {
        try await call("POST", ["sessions", id, "fork"], body: ForkRequest(message: message))
    }

    public func ciFeedback(_ id: String) async throws {
        try await perform("POST", ["sessions", id, "ci-feedback"])
    }

    // MARK: Claude Code chats

    public func claudeChats(repo: String?, includeAutomated: Bool) async throws -> [ClaudeChat] {
        var query: [URLQueryItem] = []
        if let repo {
            query.append(URLQueryItem(name: "repo", value: repo))
        }
        if includeAutomated {
            query.append(URLQueryItem(name: "include_automated", value: "true"))
        }
        return try await call("GET", ["claude-chats"], query: query)
    }

    public func claudeChat(_ id: String) async throws -> ClaudeChat {
        try await get("claude-chats", id)
    }

    public func claudeChatEvents(_ id: String) async throws -> [Event] {
        try await get("claude-chats", id, "events")
    }

    public func setClaudeChatArchived(_ id: String, archived: Bool) async throws -> ClaudeChat {
        try await call(
            "PUT", ["claude-chats", id, "archived"], body: ArchiveRequest(archived: archived))
    }

    public func adoptClaudeChat(_ id: String) async throws -> Session {
        try await call("POST", ["claude-chats", id, "adopt"])
    }

    // MARK: Review

    public func diff(_ sessionID: String) async throws -> SessionDiff {
        try await get("sessions", sessionID, "diff")
    }

    public func approve(_ sessionID: String, _ request: ApproveRequest) async throws -> Session {
        try await call("POST", ["sessions", sessionID, "approve"], body: request)
    }

    public func feedback(_ sessionID: String, text: String) async throws -> Session {
        try await call(
            "POST", ["sessions", sessionID, "feedback"], body: FeedbackRequest(text: text))
    }

    public func merge(_ sessionID: String, _ request: MergeRequest) async throws -> Session {
        try await call("POST", ["sessions", sessionID, "merge"], body: request)
    }

    public func refreshPR(_ sessionID: String) async throws -> Session {
        try await call("POST", ["sessions", sessionID, "pr", "refresh"])
    }

    // MARK: Search

    public func search(query: String, repo: String?, limit: Int) async throws -> SearchResults {
        var items = [URLQueryItem(name: "q", value: query)]
        if let repo {
            items.append(URLQueryItem(name: "repo", value: repo))
        }
        items.append(URLQueryItem(name: "limit", value: "\(limit)"))
        return try await call("GET", ["search"], query: items)
    }

    // MARK: Approvals

    public func approvals(status: ApprovalStatus?, project: String?) async throws -> [Approval] {
        var query: [URLQueryItem] = []
        if let status {
            query.append(URLQueryItem(name: "status", value: status.rawValue))
        }
        if let project {
            query.append(URLQueryItem(name: "project", value: project))
        }
        return try await call("GET", ["approvals"], query: query)
    }

    public func resolveApproval(_ id: String, _ request: ResolveApprovalRequest) async throws
        -> Approval
    {
        try await call("POST", ["approvals", id, "resolve"], body: request)
    }

    // MARK: Attachments

    public func uploadAttachment(filename: String, mediaType: String, data: Data) async throws
        -> Attachment
    {
        let form = MultipartForm(
            fieldName: "file", filename: filename, mediaType: mediaType, data: data)
        var request = makeRequest("POST", ["attachments"], query: [])
        request.setValue(form.contentType, forHTTPHeaderField: "Content-Type")
        request.httpBody = form.body
        return try decode(try await send(request))
    }

    // MARK: Account

    public func connectors() async throws -> [Connector] {
        try await get("connectors")
    }

    /// The period of that unit holding `date`.
    public func usagePeriod(unit: UsageUnit, date: CalendarDay) async throws -> UsagePeriod {
        let query = [
            URLQueryItem(name: "unit", value: unit.rawValue),
            URLQueryItem(name: "date", value: date.description),
        ]
        return try await call("GET", ["usage", "period"], query: query)
    }

    public func usageLimits() async throws -> UsageLimits {
        try await get("usage", "limits")
    }

    public func refreshUsage() async throws -> UsageLimits {
        try await call("POST", ["usage", "refresh"])
    }

    public func usageLimits(provider: String) async throws -> UsageLimits {
        try await call(
            "GET", ["usage", "limits"], query: [URLQueryItem(name: "provider", value: provider)])
    }

    public func refreshUsage(provider: String) async throws -> UsageLimits {
        try await call(
            "POST", ["usage", "refresh"], query: [URLQueryItem(name: "provider", value: provider)])
    }

    public func usageSettings() async throws -> UsageSettings {
        try await get("usage", "settings")
    }

    public func updateUsageSettings(_ settings: UsageSettings) async throws -> UsageSettings {
        try await call("PUT", ["usage", "settings"], body: settings)
    }

    public func stuckSettings() async throws -> StuckSettings {
        try await get("stuck", "settings")
    }

    public func updateStuckSettings(_ settings: StuckSettings) async throws -> StuckSettings {
        try await call("PUT", ["stuck", "settings"], body: settings)
    }

    public func reportVisibility(_ visible: Bool, client: String) async throws {
        try await perform(
            "POST", ["clients", "visibility"],
            body: VisibilityRequest(visible: visible, client: client))
    }

    public func models() async throws -> ModelList {
        try await get("models")
    }

    public func models(provider: String) async throws -> ModelList {
        try await call("GET", ["models"], query: [URLQueryItem(name: "provider", value: provider)])
    }

    public func providers(refresh: Bool) async throws -> ProviderList {
        let query = refresh ? [URLQueryItem(name: "refresh", value: "true")] : []
        return try await call("GET", ["providers"], query: query)
    }

    public func account() async throws -> ClaudeAccount {
        try await get("account")
    }

    public func agentDefaults() async throws -> AgentDefaults {
        try await get("agents", "defaults")
    }

    public func updateAgentDefaults(_ defaults: AgentDefaults) async throws -> AgentDefaults {
        try await call("PUT", ["agents", "defaults"], body: defaults)
    }

    public func createPairingCode() async throws -> PairingCode {
        try await call("POST", ["pairing", "codes"])
    }

    public func devices() async throws -> [Device] {
        try await get("devices")
    }

    public func revokeDevice(_ id: String) async throws {
        try await perform("DELETE", ["devices", id])
    }

    public func pushStatus() async throws -> PushStatus {
        try await get("push", "status")
    }

    // MARK: Settings (B81)

    public func repoBranches(_ name: String) async throws -> [String] {
        let list: BranchList = try await get("repos", name, "branches")
        return list.branches
    }

    public func repoBranchMap(_ name: String) async throws -> BranchMap {
        try await get("repos", name, "branch-map")
    }

    public func storage() async throws -> StorageUsage {
        try await get("storage")
    }

    public func storageSettings() async throws -> StorageSettings {
        try await get("storage", "settings")
    }

    public func updateStorageSettings(_ settings: StorageSettings) async throws
        -> StorageSettings
    {
        try await call("PUT", ["storage", "settings"], body: settings)
    }

    public func largeAttachments(limit: Int) async throws -> [LargeAttachment] {
        try await call(
            "GET", ["storage", "attachments"],
            query: [URLQueryItem(name: "limit", value: "\(limit)")])
    }

    public func deleteAttachment(_ id: String) async throws {
        try await perform("DELETE", ["attachments", id])
    }

    public func rebuildSearch() async throws {
        try await perform("POST", ["search", "rebuild"])
    }

    public func pixieSettings() async throws -> PixieSettings {
        try await get("pixie-settings")
    }

    public func updatePixieSettings(_ settings: PixieSettings) async throws -> PixieSettings {
        try await call("PUT", ["pixie-settings"], body: settings)
    }

    public func notificationRules() async throws -> NotificationRules {
        try await get("notifications", "settings")
    }

    public func updateNotificationRules(_ rules: NotificationRules) async throws
        -> NotificationRules
    {
        try await call("PUT", ["notifications", "settings"], body: rules)
    }

    public func githubAccount() async throws -> GitHubAccount {
        try await get("accounts", "github")
    }

    public func checkGitHubAccount() async throws -> GitHubAccount {
        try await call("POST", ["accounts", "github", "check"])
    }

    public func claudeLogin() async throws -> ClaudeLogin {
        try await get("accounts", "claude")
    }

    public func signInClaude() async throws {
        try await perform("POST", ["accounts", "claude", "login"])
    }

    public func signOutClaude() async throws -> ClaudeLogin {
        try await call("POST", ["accounts", "claude", "logout"])
    }

    public func codexLogin() async throws -> CodexLogin {
        try await get("accounts", "codex")
    }

    public func signInCodex() async throws -> CodexSignIn {
        try await call("POST", ["accounts", "codex", "login"])
    }

    public func cancelCodexSignIn() async throws {
        try await perform("POST", ["accounts", "codex", "login", "cancel"])
    }

    public func signOutCodex() async throws -> CodexLogin {
        try await call("POST", ["accounts", "codex", "logout"])
    }

    public func claudeCode() async throws -> ClaudeCodeStatus {
        try await get("claude-code")
    }

    public func installClaudeCode() async throws {
        try await perform("POST", ["claude-code", "install"])
    }

    // MARK: Extensions (B81)

    public func plugins() async throws -> [InstalledPlugin] {
        try await get("extensions", "plugins")
    }

    public func standaloneSkills() async throws -> [StandaloneSkill] {
        try await get("extensions", "skills")
    }

    public func marketplaces() async throws -> [PluginMarketplace] {
        try await get("extensions", "marketplaces")
    }

    public func addMarketplace(source: String) async throws {
        try await perform(
            "POST", ["extensions", "marketplaces"], body: MarketplaceRequest(source: source))
    }

    public func removeMarketplace(_ name: String) async throws {
        try await perform("DELETE", ["extensions", "marketplaces", name])
    }

    public func availablePlugins() async throws -> [AvailablePlugin] {
        try await get("extensions", "available")
    }

    public func pluginDetails(_ id: String) async throws -> PluginDetails {
        try await get("extensions", "plugins", id, "details")
    }

    public func installPlugin(_ id: String) async throws {
        try await perform("POST", ["extensions", "plugins", id, "install"])
    }

    public func uninstallPlugin(_ id: String) async throws {
        try await perform("POST", ["extensions", "plugins", id, "uninstall"])
    }

    public func setPluginEnabled(_ id: String, enabled: Bool) async throws {
        try await perform(
            "PUT", ["extensions", "plugins", id, "enabled"],
            body: PluginEnabledRequest(enabled: enabled))
    }

    // MARK: Configuration (B97)

    public func configuration() async throws -> ConfigurationPage {
        try await get("configuration")
    }

    public func configurationFile(path: String) async throws -> ConfigFile {
        try await call(
            "GET", ["configuration", "file"], query: [URLQueryItem(name: "path", value: path)])
    }

    public func saveConfigurationFile(path: String, text: String, expectedVersion: String?)
        async throws -> String
    {
        let answer: FileVersion = try await call(
            "PUT", ["configuration", "file"],
            body: WriteConfigFileRequest(path: path, text: text, expectedVersion: expectedVersion))
        return answer.version
    }

    public func setUsesShared(engine: String, item: SharedItem, on: Bool) async throws
        -> ConfigurationPage
    {
        try await call(
            "PUT", ["configuration", "uses-shared"],
            body: UsesSharedRequest(engine: engine, item: item, on: on))
    }

    public func createSkill(name: String, description: String) async throws
        -> ConfigurationPage
    {
        try await call(
            "POST", ["configuration", "skills"],
            body: NewSkillRequest(name: name, description: description))
    }

    public func deleteSkill(_ name: String) async throws -> ConfigurationPage {
        try await call("DELETE", ["configuration", "skills", name])
    }

    public func makeSkillShared(_ name: String, engine: String) async throws
        -> ConfigurationPage
    {
        try await call(
            "POST", ["configuration", "skills", name, "make-shared"],
            body: EngineRequest(engine: engine))
    }

    public func setSkillEnabled(_ name: String, codex enabled: Bool) async throws
        -> ConfigurationPage
    {
        try await call(
            "PUT", ["configuration", "skills", name, "engines", "codex"],
            body: PluginEnabledRequest(enabled: enabled))
    }

    public func saveMCPServer(_ name: String, _ spec: MCPServerSpec) async throws
        -> ConfigurationPage
    {
        try await call("PUT", ["configuration", "mcp-servers", name], body: spec)
    }

    public func deleteMCPServer(_ name: String) async throws -> ConfigurationPage {
        try await call("DELETE", ["configuration", "mcp-servers", name])
    }

    public func mcpServer(_ name: String) async throws -> MCPServerSpec {
        try await get("configuration", "mcp-servers", name)
    }

    public func copyPreview(engine: String) async throws -> CopyPreview {
        try await get("configuration", "copy", engine)
    }

    public func copyToShared(engine: String, instructions: Bool) async throws -> CopyResult {
        try await call(
            "POST", ["configuration", "copy", engine],
            body: CopyRequest(instructions: instructions))
    }

    public func undoCopy(_ id: String) async throws -> ConfigurationPage {
        try await call("POST", ["configuration", "copy", "undo", id])
    }

    public func repoConfiguration(_ repo: String) async throws -> RepoConfiguration {
        try await get("repos", repo, "configuration")
    }

    public func saveRepoMCPServer(_ repo: String, _ name: String, _ spec: MCPServerSpec)
        async throws
    {
        try await perform(
            "PUT", ["repos", repo, "configuration", "mcp-servers", name], body: spec)
    }

    public func deleteRepoMCPServer(_ repo: String, _ name: String) async throws {
        try await perform("DELETE", ["repos", repo, "configuration", "mcp-servers", name])
    }

    public func createRepoSkill(_ repo: String, name: String, description: String)
        async throws
    {
        try await perform(
            "POST", ["repos", repo, "configuration", "skills"],
            body: NewSkillRequest(name: name, description: description))
    }

    public func codexPlugins(query: String) async throws -> [CodexPlugin] {
        let trimmed = query.trimmingCharacters(in: .whitespaces)
        let list: CodexPluginList = try await call(
            "GET", ["configuration", "codex", "plugins"],
            query: trimmed.isEmpty ? [] : [URLQueryItem(name: "query", value: trimmed)])
        return list.plugins
    }

    public func installCodexPlugin(_ id: String) async throws {
        try await perform("POST", ["configuration", "codex", "plugins", id, "install"])
    }

    public func uninstallCodexPlugin(_ id: String) async throws {
        try await perform("POST", ["configuration", "codex", "plugins", id, "uninstall"])
    }

    public func codexMarketplaces() async throws -> [CodexMarketplace] {
        try await get("configuration", "codex", "marketplaces")
    }

    public func addCodexMarketplace(source: String) async throws {
        try await perform(
            "POST", ["configuration", "codex", "marketplaces"],
            body: MarketplaceRequest(source: source))
    }

    public func removeCodexMarketplace(_ name: String) async throws {
        try await perform("DELETE", ["configuration", "codex", "marketplaces", name])
    }

    // MARK: Pixies

    public func pixies() async throws -> [Pixie] {
        try await get("pixies")
    }

    public func pixieSkills() async throws -> [PixieSkillChoice] {
        try await get("pixies", "skills")
    }

    public func createPixie(_ request: CreatePixieRequest) async throws -> Pixie {
        try await call("POST", ["pixies"], body: request)
    }

    public func updatePixie(_ id: String, _ request: UpdatePixieRequest) async throws -> Pixie {
        try await call("PATCH", ["pixies", id], body: request)
    }

    public func reorderPixies(_ ids: [String]) async throws -> [Pixie] {
        try await call("PUT", ["pixies", "order"], body: ReorderPixiesRequest(ids: ids))
    }

    public func deletePixie(_ id: String) async throws {
        try await perform("DELETE", ["pixies", id])
    }

    public func sendToPixie(_ id: String, text: String) async throws -> SentMessage {
        try await call("POST", ["pixies", id, "messages"], body: FeedbackRequest(text: text))
    }

    public func resetPixie(_ id: String) async throws -> Pixie {
        try await call("POST", ["pixies", id, "reset"])
    }

    public func pixieFile(_ id: String, name: String) async throws -> PixieFile {
        try await call("GET", Self.filePath(id, name))
    }

    public func savePixieFile(_ id: String, name: String, text: String, hash: String?)
        async throws -> PixieFile
    {
        try await call(
            "PUT", Self.filePath(id, name), body: WritePixieFileRequest(text: text, hash: hash))
    }

    public func pixieNotes(_ id: String) async throws -> [String] {
        try await get("pixies", id, "notes")
    }

    public func searchPixie(_ id: String, query: String) async throws -> [PixieSearchHit] {
        try await call(
            "GET", ["pixies", id, "search"], query: [URLQueryItem(name: "q", value: query)])
    }

    public func pixieActivity(_ id: String) async throws -> [PixieActivityEntry] {
        try await get("pixies", id, "activity")
    }

    public func pixieHabits(_ id: String) async throws -> [PixieHabit] {
        try await get("pixies", id, "habits")
    }

    public func createHabit(_ pixie: String, _ request: CreateHabitRequest) async throws
        -> PixieHabit
    {
        try await call("POST", ["pixies", pixie, "habits"], body: request)
    }

    public func updateHabit(_ pixie: String, _ habit: String, _ request: UpdateHabitRequest)
        async throws -> PixieHabit
    {
        try await call("PATCH", ["pixies", pixie, "habits", habit], body: request)
    }

    public func deleteHabit(_ pixie: String, _ habit: String) async throws {
        try await perform("DELETE", ["pixies", pixie, "habits", habit])
    }

    public func runHabit(_ pixie: String, _ habit: String) async throws -> HabitRun {
        try await call("POST", ["pixies", pixie, "habits", habit, "run"])
    }

    public func habitRuns(_ pixie: String, _ habit: String) async throws -> [HabitRun] {
        try await get("pixies", pixie, "habits", habit, "runs")
    }

    public func pixieReports(unread: Bool) async throws -> [PixieReport] {
        try await call(
            "GET", ["pixie-reports"],
            query: [URLQueryItem(name: "unread", value: unread ? "true" : "false")])
    }

    public func markReportRead(_ id: String) async throws {
        try await perform("POST", ["pixie-reports", id, "read"])
    }

    public func markPixieReportsRead(_ id: String) async throws {
        try await perform("POST", ["pixies", id, "reports", "read"])
    }

    public func duplicatePixie(_ id: String) async throws -> Pixie {
        try await call("POST", ["pixies", id, "duplicate"])
    }

    public func pixieTeams() async throws -> [PixieTeam] {
        try await get("pixie-teams")
    }

    public func createPixieTeam(_ request: CreatePixieTeamRequest) async throws -> PixieTeam {
        try await call("POST", ["pixie-teams"], body: request)
    }

    public func updatePixieTeam(_ id: String, _ request: UpdatePixieTeamRequest) async throws
        -> PixieTeam
    {
        try await call("PATCH", ["pixie-teams", id], body: request)
    }

    public func deletePixieTeam(_ id: String) async throws {
        try await perform("DELETE", ["pixie-teams", id])
    }

    // MARK: Each chat's pixies and subagents (B46)

    public func pixieGroups() async throws -> [String: [ChatPixieEntry]] {
        try await get("pixie-groups")
    }

    public func chatPixies(_ id: String) async throws -> [ChatPixieEntry] {
        try await get("sessions", id, "pixies")
    }

    public func sendAway(_ id: String, _ request: SendAwayRequest) async throws
        -> [ChatPixieEntry]
    {
        try await call("POST", ["sessions", id, "pixies", "send-away"], body: request)
    }

    public func pixieCallWork(_ id: String, pixie: String) async throws -> [PixieCallWork] {
        try await get("sessions", id, "pixies", pixie, "calls")
    }

    public func agentTranscript(_ id: String, toolUseID: String) async throws -> AgentWork {
        try await get("sessions", id, "agents", toolUseID, "transcript")
    }

    // MARK: Artifacts (B79)

    public func artifacts(repo: String?, sessionID: String?, pixieID: String?) async throws
        -> [Artifact]
    {
        let filters = [("repo", repo), ("session_id", sessionID), ("pixie_id", pixieID)]
        return try await call(
            "GET", ["artifacts"],
            query: filters.compactMap { name, value in
                value.map { URLQueryItem(name: name, value: $0) }
            })
    }

    public func unseenArtifacts() async throws -> Int {
        let answer: UnseenArtifacts = try await get("artifacts", "unseen")
        return answer.unseen
    }

    public func artifact(_ id: String) async throws -> ArtifactDetail {
        try await get("artifacts", id)
    }

    public func artifactContent(_ id: String, version: Int) async throws -> ArtifactContent {
        try await get("artifacts", id, "versions", String(version))
    }

    public func markArtifactSeen(_ id: String) async throws -> Artifact {
        try await call("POST", ["artifacts", id, "seen"])
    }

    public func artifactStorage(_ id: String) async throws -> ArtifactStorage {
        try await get("artifacts", id, "storage")
    }

    public func writeArtifactStorage(_ id: String, set: [String: String], remove: [String])
        async throws -> Int
    {
        let answer: ArtifactStorageSize = try await call(
            "POST", ["artifacts", id, "storage"],
            body: ArtifactStorageWrite(set: set, remove: remove))
        return answer.size
    }

    public func askStatus(_ id: String) async throws -> ArtifactAskStatus {
        try await get("artifacts", id, "ask")
    }

    public func askArtifact(_ id: String, prompt: String, system: String?) async throws
        -> ArtifactAnswer
    {
        try await call(
            "POST", ["artifacts", id, "ask"],
            body: AskArtifactRequest(prompt: prompt, system: system))
    }

    public func clearArtifactStorage(_ id: String) async throws {
        try await perform("DELETE", ["artifacts", id, "storage"])
    }

    public func saveArtifactVersion(_ id: String, content: String, baseVersion: Int)
        async throws -> ArtifactVersion
    {
        try await call(
            "POST", ["artifacts", id, "versions"],
            body: SaveArtifactVersionRequest(content: content, baseVersion: baseVersion))
    }

    public func deleteArtifact(_ id: String) async throws {
        try await perform("DELETE", ["artifacts", id])
    }

    /// A name such as `notes/ideas` is one path segment per slash.
    private static func filePath(_ id: String, _ name: String) -> [String] {
        ["pixies", id, "files"] + name.split(separator: "/").map(String.init)
    }

    // MARK: Plumbing

    private func get<T: Decodable>(_ path: String...) async throws -> T {
        try await call("GET", path)
    }

    private func call<T: Decodable>(
        _ method: String, _ path: [String], query: [URLQueryItem] = [],
        body: (any Encodable)? = nil
    ) async throws -> T {
        try decode(try await send(try encodedRequest(method, path, query: query, body: body)))
    }

    /// For routes that answer 202 or 204 without a body worth reading.
    private func perform(
        _ method: String, _ path: [String], query: [URLQueryItem] = [],
        body: (any Encodable)? = nil
    ) async throws {
        _ = try await send(try encodedRequest(method, path, query: query, body: body))
    }

    private func encodedRequest(
        _ method: String, _ path: [String], query: [URLQueryItem], body: (any Encodable)?
    ) throws -> URLRequest {
        var request = makeRequest(method, path, query: query)
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try NestJSON.encoder.encode(body)
        }
        return request
    }

    func makeRequest(_ method: String, _ path: [String], query: [URLQueryItem]) -> URLRequest {
        var url = baseURL.appending(path: "api")
        for component in path {
            url.append(component: component)
        }
        if !query.isEmpty {
            url.append(queryItems: query)
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        return request
    }

    private func send(_ request: URLRequest) async throws -> HTTPResponse {
        let response: HTTPResponse
        do {
            response = try await transport.send(request)
        } catch {
            throw APIError.transport(error.localizedDescription)
        }
        guard (200..<300).contains(response.status) else {
            throw APIError.from(response)
        }
        return response
    }

    private func decode<T: Decodable>(_ response: HTTPResponse) throws -> T {
        do {
            return try NestJSON.decoder.decode(T.self, from: response.body)
        } catch {
            throw APIError.decoding(String(describing: error))
        }
    }
}
