import Foundation

/// The daemon's HTTP API with the device's bearer token.
public struct APIClient: HarnessAPI {
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

    public func createSession(_ request: CreateSessionRequest) async throws -> Session {
        try await call("POST", ["sessions"], body: request)
    }

    public func updateSession(_ id: String, _ request: UpdateSessionRequest) async throws
        -> Session
    {
        try await call("PATCH", ["sessions", id], body: request)
    }

    /// Deletes the session for good, with its worktree, branch and history.
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

    public func interrupt(_ id: String) async throws {
        try await perform("POST", ["sessions", id, "interrupt"])
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

    public func rewindPreview(_ id: String, message: Int) async throws -> RewindPreview {
        try await call(
            "GET", ["sessions", id, "rewind"],
            query: [URLQueryItem(name: "message", value: "\(message)")])
    }

    public func rewind(_ id: String, message: Int) async throws {
        try await perform(
            "POST", ["sessions", id, "rewind"], body: RewindRequest(message: message))
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

    public func reject(_ sessionID: String) async throws -> Session {
        try await call("POST", ["sessions", sessionID, "reject"])
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

    public func usageMonth(year: Int, month: Int) async throws -> UsageMonth {
        let query = [
            URLQueryItem(name: "year", value: "\(year)"),
            URLQueryItem(name: "month", value: "\(month)"),
        ]
        return try await call("GET", ["usage", "month"], query: query)
    }

    public func usageLimits() async throws -> UsageLimits {
        try await get("usage", "limits")
    }

    public func refreshUsage() async throws -> UsageLimits {
        try await call("POST", ["usage", "refresh"])
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

    // MARK: Pixies

    public func pixies() async throws -> [Pixie] {
        try await get("pixies")
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
            request.httpBody = try HarnessJSON.encoder.encode(body)
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
            return try HarnessJSON.decoder.decode(T.self, from: response.body)
        } catch {
            throw APIError.decoding(String(describing: error))
        }
    }
}
