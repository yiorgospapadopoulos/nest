#if DEBUG
    import Foundation
    import HarnessKit

    /// A daemon with realistic sample projects, for snapshots and previews. Writes only
    /// change its memory.
    final class SampleAPI: HarnessAPI, @unchecked Sendable {
        private let lock = NSLock()
        private let now: Date
        private var sessionList: [Session]
        private let details: [String: Session]
        private let events: [String: [Event]]
        private let approvalList: [Approval]
        private var chatList: [ClaudeChat]
        private let chatEvents: [String: [Event]]
        /// History of adopted chats, by their new session id.
        private var adoptedEvents: [String: [Event]] = [:]
        /// Sessions whose chat Claude Code still has open, so sending is refused.
        private var openElsewhere: Set<String> = []
        /// Manual usage refreshes so far; the daemon refuses one within 20 s of another.
        private var refreshes = 0
        private var refreshMinutes = 3
        private var stuck = StuckSettings(
            waitingMinutes: 15, silentMinutes: 10, repeatedCalls: 4, turnMinutes: 60)
        /// What searches answer for `indexing`.
        private var searchIndexing = false
        private var agentDefaults = AgentDefaults(
            model: "opus", effort: .high, permissionMode: .default, mode: .inPlace)
        /// What approving answers instead of the failed push, when set.
        private var approveRefusal: APIError?

        init(now: Date = Date()) {
            self.now = now
            let data = SampleData(now: now)
            sessionList = data.sessions
            details = data.details
            events = data.events
            approvalList = data.approvals
            chatList = data.claudeChats
            chatEvents = data.claudeEvents
        }

        /// Four git repositories and a plain folder, "recipes".
        func repos() async throws -> [Repo] {
            try ["todo-ui", "weather-forecast", "map-viewer", "harness", "recipes"].map { name in
                let git = name != "recipes"
                return try decode([
                    "name": name, "path": "/Users/me/Projects/\(name)",
                    "default_branch": git ? "main" : NSNull(), "git": git,
                    "worktree": [
                        "default": true, "link": [], "setup": [], "setup_timeout_seconds": 900,
                    ],
                ])
            }
        }

        func registerRepo(path: String, name: String?) async throws -> Repo {
            try await repos()[0]
        }

        func openRepo(_ name: String, in app: RepoApp) async throws {}

        func removeRepo(_ name: String, purgeSessions: Bool) async throws {}

        func updateWorktree(_ name: String, _ config: WorktreeConfig) async throws -> Repo {
            let all = try await repos()
            var repo = all.first { $0.name == name } ?? all[0]
            repo.worktree = config
            return repo
        }

        func linkSuggestions(_ name: String) async throws -> [String] {
            [".env", "node_modules/"]
        }

        func sessions(repo: String?, archived: Bool) async throws -> [Session] {
            lock.withLock { sessionList }.filter {
                $0.isArchived == archived && (repo == nil || $0.repo == repo)
            }
        }

        func session(_ id: String) async throws -> Session {
            guard let detail = details[id] ?? lock.withLock({ sessionList.first { $0.id == id } })
            else { throw APIError.notFound("No session \(id)") }
            return detail
        }

        func createSession(_ request: CreateSessionRequest) async throws -> Session {
            throw APIError.invalidInput("Sample data is read-only")
        }

        func updateSession(_ id: String, _ request: UpdateSessionRequest) async throws -> Session {
            try lock.withLock {
                guard let index = sessionList.firstIndex(where: { $0.id == id }) else {
                    throw APIError.notFound(id)
                }
                if let pinned = request.pinned {
                    sessionList[index].pinned = pinned
                }
                if let title = request.title {
                    sessionList[index].title = title
                }
                if let effort = request.effort {
                    sessionList[index].effort = effort
                }
                return sessionList[index]
            }
        }

        func deleteSession(_ id: String) async throws {
            lock.withLock { sessionList.removeAll { $0.id == id } }
        }

        /// As the daemon pages: `after < id < before`, the ones nearest `before` when it
        /// is given, else nearest `after`.
        func sessionEvents(_ id: String, after: Int, before: Int?, limit: Int?) async throws
            -> [Event]
        {
            let range = (events[id] ?? lock.withLock { adoptedEvents[id] } ?? []).filter {
                ($0.id ?? 0) > after && ($0.id ?? 0) < (before ?? .max)
            }
            guard let limit else { return range }
            return before == nil ? Array(range.prefix(limit)) : Array(range.suffix(limit))
        }

        /// Queued while the chat works, as the daemon does; a nudge is queued first.
        func sendMessage(
            _ id: String, text: String, attachmentIDs: [String], interrupt: Bool
        ) async throws -> SentMessage {
            if lock.withLock({ openElsewhere.contains(id) }) {
                throw APIError.openInClaudeCode(
                    "This chat is open in Claude Code right now. Close it there first.")
            }
            let session = try await session(id)
            let queued =
                session.state.isInFlight
                ? QueuedMessage(id: UUID().uuidString, text: text, createdAt: Date()) : nil
            return SentMessage(session: session, queuedMessage: queued)
        }

        func cancelQueued(_ id: String, queuedID: String) async throws {}

        func sessionCommands(_ id: String) async throws -> CommandList {
            CommandList(source: .session, commands: SampleData.commands)
        }

        func repoCommands(_ repo: String) async throws -> CommandList {
            CommandList(source: .repo, commands: SampleData.commands)
        }

        /// The sample repo's files whose path contains the query, shortest first.
        func sessionFiles(_ id: String, query: String) async throws -> [String] {
            let lowered = query.lowercased()
            return SampleData.files.filter { lowered.isEmpty || $0.lowercased().contains(lowered) }
                .sorted { ($0.count, $0) < ($1.count, $1) }
        }

        func claudeChats(repo: String?, includeAutomated: Bool) async throws -> [ClaudeChat] {
            lock.withLock { chatList }.filter {
                (repo == nil || $0.repo == repo) && (includeAutomated || !$0.automated)
            }
        }

        func claudeChat(_ id: String) async throws -> ClaudeChat {
            guard let chat = lock.withLock({ chatList.first { $0.id == id } }) else {
                throw APIError.notFound("No Claude Code chat \(id)")
            }
            return chat
        }

        func claudeChatEvents(_ id: String) async throws -> [Event] {
            chatEvents[id] ?? []
        }

        func setClaudeChatArchived(_ id: String, archived: Bool) async throws -> ClaudeChat {
            try lock.withLock {
                guard let index = chatList.firstIndex(where: { $0.id == id }) else {
                    throw APIError.notFound("No Claude Code chat \(id)")
                }
                chatList[index].archived = archived
                return chatList[index]
            }
        }

        /// An idle in-place session in the chat's folder, with the chat's history.
        func adoptClaudeChat(_ id: String) async throws -> Session {
            let chat = try await claudeChat(id)
            let session: Session = try decode([
                "id": "adopted-\(id)", "repo": chat.repo, "title": chat.title,
                "prompt": chat.title, "mode": "in_place", "cwd": chat.cwd, "model": "opus",
                "effort": "high", "permission_mode": "default", "provider": "claude",
                "state": "idle", "provider_session_id": id, "git_violation": false,
                "created_at": SampleData.iso(chat.createdAt),
                "updated_at": SampleData.iso(chat.lastActivityAt), "allowed_tools": [],
                "pinned": false,
            ])
            lock.withLock {
                chatList.removeAll { $0.id == id }
                sessionList.append(session)
                adoptedEvents[session.id] = chatEvents[id] ?? []
                if chat.openInClaudeCode {
                    openElsewhere.insert(session.id)
                }
            }
            return session
        }

        func interrupt(_ id: String) async throws {}

        func rewindPreview(_ id: String, message: Int) async throws -> RewindPreview {
            RewindPreview(
                canRewind: true, files: ["src/App.tsx", "src/styles.css"], insertions: 12,
                deletions: 4)
        }

        func rewind(_ id: String, message: Int) async throws {}

        func ciFeedback(_ id: String) async throws {}

        func openInClaudeCode(_ id: String) async throws -> ClaudeCodeLaunch {
            try decode(["launcher": "/tmp/claude.command"])
        }

        func diff(_ sessionID: String) async throws -> SessionDiff {
            try SampleData.diff()
        }

        /// Approving answers this refusal from now on, as when origin's address changed.
        func refuseApprove(with error: APIError) {
            lock.withLock { approveRefusal = error }
        }

        /// Pushing fails, so snapshots show a failed step with git's output.
        func approve(_ sessionID: String, _ request: ApproveRequest) async throws -> Session {
            if let refusal = lock.withLock({ approveRefusal }) {
                throw refusal
            }
            throw APIError.gitFailed(
                "git push failed", step: "push",
                stderr:
                    "remote: Permission to me/todo-ui.git denied to me.\nfatal: unable to access 'https://github.com/me/todo-ui.git/': The requested URL returned error: 403"
            )
        }

        func reject(_ sessionID: String) async throws -> Session { try await session(sessionID) }

        func feedback(_ sessionID: String, text: String) async throws -> Session {
            try await session(sessionID)
        }

        /// Merges like the daemon: the session closes and its pull request shows merged.
        func merge(_ sessionID: String, _ request: MergeRequest) async throws -> Session {
            try lock.withLock {
                guard let index = sessionList.firstIndex(where: { $0.id == sessionID }) else {
                    throw APIError.notFound(sessionID)
                }
                sessionList[index].state = .closed
                sessionList[index].pr?.state = .merged
                return sessionList[index]
            }
        }

        func refreshPR(_ sessionID: String) async throws -> Session {
            try await session(sessionID)
        }

        func approvals(status: ApprovalStatus?, project: String?) async throws -> [Approval] {
            approvalList.filter { project == nil || $0.repo == project }
        }

        func resolveApproval(_ id: String, _ request: ResolveApprovalRequest) async throws
            -> Approval
        {
            approvalList.first { $0.id == id }!
        }

        func uploadAttachment(filename: String, mediaType: String, data: Data) async throws
            -> Attachment
        {
            try decode([
                "id": UUID().uuidString, "filename": filename, "media_type": mediaType,
                "size": data.count,
            ])
        }

        func connectors() async throws -> [Connector] {
            let list: [(String, String, String, String?)] = [
                ("Gmail", "claude.ai", "connected", nil),
                ("Google Calendar", "claude.ai", "connected", nil),
                ("Google Drive", "claude.ai", "needs-auth", nil),
                ("Notion", "claude.ai", "connected", nil),
                ("Slack", "claude.ai", "needs-auth", nil),
                ("github", "plugin", "needs-auth", nil),
                ("context7", "plugin", "connected", nil),
                ("serena", "local", "connected", nil),
                ("pdf-viewer", "plugin", "pending", nil),
                ("linear", "plugin", "failed", "spawn npx ENOENT"),
            ]
            return try list.map { name, group, status, error in
                var object: [String: Any] = [
                    "name": name, "display_name": name, "group": group, "status": status,
                    "manage_hint": group == "claude.ai" ? "claude.ai" : "claude_code",
                    "source": "c1", "last_seen_at": SampleData.iso(now),
                ]
                object["error"] = error
                return try decode(object)
            }
        }

        func usageMonth(year: Int, month: Int) async throws -> UsageMonth {
            try decode([
                "year": year, "month": month, "sessions": 41,
                "tokens": [
                    "input_tokens": 1_200_000, "output_tokens": 300_000,
                    "cache_creation_input_tokens": 400_000, "cache_read_input_tokens": 9_000_000,
                    "total": 10_900_000,
                ],
                "days": SampleData.days(year: year, month: month, now: now),
                "probes": ["count": 96, "tokens": 38_400],
            ])
        }

        /// Reported 25 minutes before the sample's now: stale.
        func usageLimits() async throws -> UsageLimits {
            try limits(asOf: now - 25 * 60)
        }

        /// Fresh limits the first time, then too soon.
        func refreshUsage() async throws -> UsageLimits {
            let count = lock.withLock {
                refreshes += 1
                return refreshes
            }
            guard count == 1 else {
                throw APIError.rateLimited("usage was refreshed moments ago", retryAfter: 14)
            }
            return try limits(asOf: Date() - 60)
        }

        func usageSettings() async throws -> UsageSettings {
            UsageSettings(refreshMinutes: lock.withLock { refreshMinutes })
        }

        func updateUsageSettings(_ settings: UsageSettings) async throws -> UsageSettings {
            lock.withLock { refreshMinutes = settings.refreshMinutes }
            return settings
        }

        func reportVisibility(_ visible: Bool, client: String) async throws {}

        func stuckSettings() async throws -> StuckSettings {
            lock.withLock { stuck }
        }

        func updateStuckSettings(_ settings: StuckSettings) async throws -> StuckSettings {
            lock.withLock { stuck = settings }
            return settings
        }

        /// Searches answer as if the daemon still indexed the history.
        func setSearchIndexing(_ indexing: Bool) {
            lock.withLock { searchIndexing = indexing }
        }

        /// Every word in titles, messages, tool calls and tool output, titles first, then
        /// newest; Claude Code chats by title.
        func search(query: String, repo: String?, limit: Int) async throws -> SearchResults {
            let words = query.lowercased().split(separator: " ").map(String.init)
            func matches(_ text: String) -> Bool {
                let lowered = text.lowercased()
                return words.allSatisfy { lowered.contains($0) }
            }
            func hit(
                _ session: String, _ repo: String, _ title: String, _ event: Int?, _ ts: Date,
                _ kind: String, _ text: String
            ) throws -> SearchHit {
                var object: [String: Any] = [
                    "session_id": session, "repo": repo, "title": title,
                    "ts": SampleData.iso(ts), "kind": kind,
                    "snippet": SampleData.snippet(text, words: words),
                ]
                object["event_id"] = event
                return try decode(object)
            }
            var titles: [SearchHit] = []
            var messages: [SearchHit] = []
            let sessions = lock.withLock { sessionList }
            for session in sessions where repo == nil || session.repo == repo {
                if matches(session.title) {
                    titles.append(
                        try hit(
                            session.id, session.repo, session.title, nil, session.updatedAt,
                            "title", session.title))
                }
                for event in events[session.id] ?? [] {
                    for (kind, text) in SampleData.searchable(event) where matches(text) {
                        messages.append(
                            try hit(
                                session.id, session.repo, session.title, event.id, event.ts, kind,
                                text))
                    }
                }
            }
            for chat in lock.withLock({ chatList })
            where !chat.automated && matches(chat.title) && (repo == nil || chat.repo == repo) {
                titles.append(
                    try hit(
                        chat.id, chat.repo, chat.title, nil, chat.lastActivityAt, "claude_chat",
                        chat.title))
            }
            let hits = titles + messages.sorted { ($0.eventID ?? 0) > ($1.eventID ?? 0) }
            return SearchResults(
                hits: Array(hits.prefix(limit)), indexing: lock.withLock { searchIndexing })
        }

        private func limits(asOf updated: Date) throws -> UsageLimits {
            try decode([
                "five_hour": [
                    "utilization": 0.3, "resets_at": SampleData.iso(now + 7200),
                    "updated_at": SampleData.iso(updated),
                ],
                "seven_day": [
                    "utilization": 0.06, "resets_at": SampleData.iso(now + 4 * 86_400),
                    "updated_at": SampleData.iso(updated),
                ],
            ])
        }

        /// Claude Code's /model list as of Opus 5.5.
        func models() async throws -> ModelList {
            let all = ["low", "medium", "high", "xhigh", "max"]
            let rows: [(String, String, String, [String])] = [
                (
                    "default", "Default (recommended)",
                    "Opus 5.5 for up to 50% of usage limits, then Sonnet 5.5", all
                ),
                ("opus", "Opus 5.5", "Most capable for complex work", all),
                (
                    "claude-fable-5-1", "Fable 5.1", "Long-form writing and storytelling",
                    ["low", "medium", "high"]
                ),
                (
                    "sonnet", "Sonnet 5.5", "Best for everyday tasks",
                    ["low", "medium", "high", "xhigh"]
                ),
                ("haiku", "Haiku 4.5", "Fastest for quick answers", []),
                ("claude-opus-5", "Opus 5", "Previous Opus", all),
                ("claude-fable-5", "Fable 5", "Previous Fable", ["low", "medium", "high"]),
                ("claude-opus-4-8", "Opus 4.8", "Earlier Opus", ["low", "medium", "high", "max"]),
                ("claude-opus-4-7", "Opus 4.7", "Earlier Opus", ["low", "medium", "high", "max"]),
                ("claude-opus-4-6", "Opus 4.6", "Earlier Opus", ["low", "medium", "high"]),
                ("claude-sonnet-4-6", "Sonnet 4.6", "Earlier Sonnet", ["low", "medium", "high"]),
            ]
            return try decode([
                "models": rows.map { value, name, description, levels in
                    [
                        "value": value, "display_name": name, "description": description,
                        "effort_levels": levels, "supports_effort": !levels.isEmpty,
                        "supports_auto_mode": value == "default" || value == "opus",
                        "claude_code_effort": value == "default" ? "high" : NSNull(),
                    ] as [String: Any]
                },
                "updated_at": SampleData.iso(now),
            ])
        }

        func account() async throws -> ClaudeAccount {
            ClaudeAccount(
                displayName: "Sam Rivera", email: "sam@example.com",
                plan: "Claude Max")
        }

        func agentDefaults() async throws -> AgentDefaults {
            lock.withLock { agentDefaults }
        }

        func updateAgentDefaults(_ defaults: AgentDefaults) async throws -> AgentDefaults {
            lock.withLock { agentDefaults = defaults }
            return defaults
        }

        func createPairingCode() async throws -> PairingCode {
            try decode(["code": "K7Q4-M2XD", "expires_at": SampleData.iso(Date() + 299)])
        }

        func devices() async throws -> [Device] {
            try decode([
                [
                    "id": "mac", "name": "MacBook Air", "is_local": true,
                    "created_at": SampleData.iso(now - 86_400 * 3),
                    "last_seen_at": SampleData.iso(now),
                ],
                [
                    "id": "phone", "name": "iPhone 12 Pro Max", "is_local": false,
                    "created_at": SampleData.iso(now - 86_400),
                    "last_seen_at": SampleData.iso(now - 180),
                ],
            ])
        }

        func revokeDevice(_ id: String) async throws {}

        private func decode<T: Decodable>(_ object: Any) throws -> T {
            try SampleData.decode(object)
        }
    }

    /// Sessions, transcripts and approvals that mirror the locked mockup's projects.
    struct SampleData {
        let now: Date
        private(set) var sessions: [Session] = []
        private(set) var details: [String: Session] = [:]
        private(set) var events: [String: [Event]] = [:]
        private(set) var approvals: [Approval] = []
        private(set) var claudeChats: [ClaudeChat] = []
        private(set) var claudeEvents: [String: [Event]] = [:]
        private var nextEvent = 1

        static let commands: [SlashCommand] = [
            SlashCommand(name: "add-dir", description: "Add a new working directory"),
            SlashCommand(name: "agents", description: "Manage agent configurations"),
            SlashCommand(
                name: "clear", description: "Clear conversation history and free up context"),
            SlashCommand(
                name: "compact",
                description: "Clear history but keep a summary of it in context",
                argumentHint: "<optional custom summarization instructions>"),
            SlashCommand(
                name: "context", description: "Visualize current context usage as a grid"),
            SlashCommand(name: "cost", description: "Show the cost and duration of this chat"),
            SlashCommand(name: "init", description: "Initialize a CLAUDE.md file"),
            SlashCommand(
                name: "review", description: "Review a pull request", argumentHint: "[pr number]"),
            SlashCommand(
                name: "security-review",
                description: "Complete a security review of the pending changes"),
            SlashCommand(
                name: "simplify", description: "Review the changed code for reuse and quality"),
        ]

        static let files = [
            "app/layout.tsx", "app/page.tsx", "app/globals.css", "app/contact/page.tsx",
            "app/api/contact/route.ts", "app/publications/page.tsx", "components/Nav.tsx",
            "components/ContactForm.tsx", "components/Hero.tsx", "components/ThemeToggle.tsx",
            "content/refs.bib", "lib/bibtex.ts", "lib/contact-schema.ts", "package.json",
            "README.md",
        ]

        static func iso(_ date: Date) -> String {
            date.formatted(.iso8601)
        }

        /// What the daemon indexes of an event, by hit kind.
        static func searchable(_ event: Event) -> [(String, String)] {
            switch event.body {
            case .userMessage(let message):
                return [("user", message.text)]
            case .message(let message) where message.parentToolUseID == nil:
                return message.blocks.compactMap { block in
                    switch block {
                    case .text(let text): ("assistant", text)
                    case .toolUse(_, let name, let input):
                        ("tool", "\(name) \(ToolSummary.argument(tool: name, input: input))")
                    case .toolResult(_, let content, _): ("tool_result", content)
                    default: nil
                    }
                }
            default:
                return []
            }
        }

        /// About 120 characters around the first match, every word marked as the daemon
        /// marks them.
        static func snippet(_ text: String, words: [String]) -> String {
            let flat = text.split(whereSeparator: \.isWhitespace).joined(separator: " ")
            let lowered = flat.lowercased()
            let first = words.compactMap { lowered.range(of: $0)?.lowerBound }.min()
            let offset = first.map { lowered.distance(from: lowered.startIndex, to: $0) } ?? 0
            let start = max(0, offset - 40)
            var window = String(flat.dropFirst(start).prefix(120))
            if start > 0 {
                window = "…" + window
            }
            if start + 120 < flat.count {
                window += "…"
            }
            let pattern = words.map(NSRegularExpression.escapedPattern(for:))
                .joined(separator: "|")
            guard let regex = try? NSRegularExpression(pattern: pattern, options: .caseInsensitive)
            else { return window }
            return regex.stringByReplacingMatches(
                in: window, range: NSRange(window.startIndex..., in: window),
                withTemplate: "[[$0]]")
        }

        static func decode<T: Decodable>(_ object: Any) throws -> T {
            let data = try JSONSerialization.data(withJSONObject: object)
            return try HarnessJSON.decoder.decode(T.self, from: data)
        }

        /// Every day of a month with made-up but stable token counts up to today.
        static func days(year: Int, month: Int, now: Date) -> [[String: Any]] {
            let calendar = Calendar.current
            let first = calendar.date(from: DateComponents(year: year, month: month, day: 1))!
            let count = calendar.range(of: .day, in: .month, for: first)!.count
            return (1...count).map { day in
                let date = calendar.date(byAdding: .day, value: day - 1, to: first)!
                let weekend = calendar.isDateInWeekend(date)
                let seed = abs(sin(Double(year * 373 + month * 97 + day * 13)) * 10_000)
                let x = seed - seed.rounded(.down)
                let quiet = x < (weekend ? 0.5 : 0.13) || date > now
                let tokens =
                    quiet ? 0 : Int((weekend ? 120_000 : 260_000) + x * x * 2_900_000)
                return [
                    "date": String(format: "%04d-%02d-%02d", year, month, day),
                    "tokens": tokens, "sessions": tokens == 0 ? 0 : max(1, tokens / 380_000),
                ]
            }
        }

        /// The dark mode review's changes, with a binary file and a long one cut short.
        static func diff() throws -> SessionDiff {
            func line(_ kind: String, _ text: String, _ old: Int?, _ new: Int?) -> [String: Any] {
                var object: [String: Any] = ["kind": kind, "text": text]
                object["old_line"] = old
                object["new_line"] = new
                return object
            }
            let css: [[String: Any]] = [
                line("context", ":root {", 18, 18),
                line("context", "  --bg: #ffffff;", 19, 19),
                line("delete", "  --muted: #6b6f7a;", 20, nil),
                line("add", "  --muted: #a1a6b3;", nil, 20),
                line("add", "  color-scheme: light dark;", nil, 21),
                line("context", "}", 21, 22),
                line("context", "", 22, 23),
                line("context", "@media (prefers-color-scheme: dark) {", 23, 24),
                line("delete", "  .toggle:focus { outline: none; }", 24, nil),
                line("add", "  .toggle:focus-visible {", nil, 25),
                line("add", "    outline: 2px solid var(--accent);", nil, 26),
                line("add", "  }", nil, 27),
                line("context", "}", 25, 28),
            ]
            let layout: [[String: Any]] = [
                line("context", "export default function RootLayout({ children }) {", 8, 8),
                line("context", "  return (", 9, 9),
                line("delete", "    <html lang=\"en\">", 10, nil),
                line("add", "    <html lang=\"en\" suppressHydrationWarning>", nil, 10),
                line(
                    "add", "      <script dangerouslySetInnerHTML={{ __html: themeInit }} />", nil,
                    11),
                line("context", "      <body>{children}</body>", 11, 12),
            ]
            func file(
                _ path: String, _ add: Int, _ del: Int, truncated: Bool = false,
                hunks: [[String: Any]], status: String = "modified", binary: Bool = false
            ) -> [String: Any] {
                [
                    "path": path, "old_path": NSNull(), "status": status, "additions": add,
                    "deletions": del, "binary": binary, "truncated": truncated, "hunks": hunks,
                ]
            }
            return try decode([
                "base": "main",
                "head": ["commit": "9f3c2e1a7b", "branch": "agent/dark-mode-contrast-3f2a"],
                "commits": [["sha": "4d5e6f7a8b9c", "subject": "Add a release workflow"]],
                "stats": ["files": 4, "additions": 48, "deletions": 19],
                "files": [
                    file(
                        "app/globals.css", 30, 11, truncated: true,
                        hunks: [
                            [
                                "old_start": 18, "old_lines": 8, "new_start": 18, "new_lines": 11,
                                "header": "", "lines": css,
                            ]
                        ]),
                    file(
                        "app/layout.tsx", 4, 2,
                        hunks: [
                            [
                                "old_start": 8, "old_lines": 4, "new_start": 8, "new_lines": 5,
                                "header": "RootLayout", "lines": layout,
                            ]
                        ]),
                    file("components/ThemeToggle.tsx", 14, 6, hunks: []),
                    file("public/og-dark.png", 0, 0, hunks: [], status: "added", binary: true),
                ],
            ])
        }

        init(now: Date) {
            self.now = now
            buildTodoUi()
            buildWeatherForecast()
            buildMapViewer()
            buildClaudeChats()
        }

        private func ago(_ minutes: Double) -> String {
            Self.iso(now.addingTimeInterval(-minutes * 60))
        }

        private mutating func session(
            _ id: String, repo: String, title: String, state: String, minutes: Double,
            model: String = "sonnet", effort: String = "medium",
            permission: String = "acceptEdits", branch: String, pinned: Bool = false,
            archived: Bool = false, tasks: [[String: Any]] = [], agents: [[String: Any]] = [],
            background: [[String: Any]] = [], context: Double? = nil, queued: [String] = [],
            pr: [String: Any]? = nil, stuck: [String: Any]? = nil
        ) {
            var object: [String: Any] = [
                "id": id, "repo": repo, "title": title, "prompt": title, "mode": "worktree",
                "model": model, "effort": effort, "permission_mode": permission,
                "provider": "claude", "state": state, "branch": branch,
                "git_violation": false, "created_at": ago(minutes + 30),
                "updated_at": ago(minutes), "allowed_tools": [], "pinned": pinned,
            ]
            if archived {
                object["archived_at"] = ago(minutes)
            }
            if let pr {
                object["pr"] = pr
                object["pr_url"] = pr["url"]
            }
            object["stuck"] = stuck
            if let context {
                object["context"] = [
                    "percent": context, "used": Int(context * 2_000), "limit": 200_000,
                ]
            }
            let summary: Session = try! Self.decode(object)
            sessions.append(summary)
            object["tasks"] = tasks
            object["agents"] = agents
            let running = background.count { $0["status"] as? String == "running" }
            object["background"] = [
                "running": running, "completed": background.count - running, "items": background,
            ]
            object["queued"] = queued.enumerated().map { index, text in
                [
                    "id": "\(id)-queued-\(index)", "text": text, "attachments": [],
                    "created_at": ago(1),
                ]
            }
            details[id] = try! Self.decode(object)
        }

        /// A pull request's stored status; checks are (name, state) pairs.
        private func pullRequest(
            _ number: Int, _ title: String, state: String = "open", checks: [(String, String)],
            mergeable: Bool? = true
        ) -> [String: Any] {
            let count = { (wanted: [String]) in checks.count { wanted.contains($0.1) } }
            let failed = count(["failure"])
            let pending = count(["pending"])
            let running = pending > 0 ? "pending" : "success"
            let summary = checks.isEmpty ? "none" : failed > 0 ? "failure" : running
            return [
                "number": number, "url": "https://github.com/me/todo-ui/pull/\(number)",
                "title": title, "state": state,
                "checks": [
                    "state": summary, "passed": count(["success", "skipped"]), "failed": failed,
                    "pending": pending,
                    "items": checks.map { name, state in
                        [
                            "name": name, "state": state,
                            "url": "https://github.com/me/todo-ui/actions/runs/\(number)",
                        ]
                    },
                ],
                "mergeable": mergeable as Any,
                "merge_state": mergeable == true ? "clean" : "blocked",
                "review_decision": NSNull(), "head_sha": "9f2c4e1", "created_at": ago(240),
                "changed_at": ago(30), "updated_at": ago(1),
            ]
        }

        private mutating func transcript(_ session: String, _ bodies: [(String, [String: Any])]) {
            events[session] = bodies.map { type, payload in
                defer { nextEvent += 1 }
                return try! Self.decode([
                    "id": nextEvent, "type": type, "ts": ago(10), "session_id": session,
                    "payload": payload,
                ])
            }
        }

        private mutating func approval(
            _ id: String, session: String, repo: String, title: String, kind: String,
            payload: [String: Any]
        ) {
            approvals.append(
                try! Self.decode([
                    "id": id, "session_id": session, "repo": repo, "title": title, "kind": kind,
                    "status": "pending", "payload": payload, "created_at": ago(2),
                ]))
        }

        private static func user(_ text: String) -> (String, [String: Any]) {
            ("session.user_message", ["text": text, "attachments": []])
        }

        private static func text(_ text: String) -> (String, [String: Any]) {
            ("session.message", ["blocks": [["type": "text", "text": text]]])
        }

        private static func tool(
            _ id: String, _ name: String, _ input: [String: Any], result: String? = nil
        ) -> [(String, [String: Any])] {
            var list: [(String, [String: Any])] = [
                (
                    "session.message",
                    ["blocks": [["type": "tool_use", "id": id, "name": name, "input": input]]]
                )
            ]
            if let result {
                list.append(
                    (
                        "session.message",
                        [
                            "blocks": [
                                [
                                    "type": "tool_result", "tool_use_id": id, "content": result,
                                    "is_error": false,
                                ]
                            ]
                        ]
                    ))
            }
            return list
        }

        private static func approvalEvent(_ id: String, kind: String) -> (String, [String: Any]) {
            (
                "approval.created",
                [
                    "approval": [
                        "id": id, "session_id": "", "repo": "", "title": "", "kind": kind,
                        "status": "pending", "payload": [:], "created_at": "2026-10-06T09:00:00Z",
                    ]
                ]
            )
        }

        private static func task(
            _ id: String, _ subject: String, _ status: String, active: String? = nil
        )
            -> [String: Any]
        {
            var task: [String: Any] = ["id": id, "subject": subject, "status": status]
            task["active_form"] = active
            return task
        }

        private func agent(
            _ id: String, _ name: String, status: String, activity: String?, minutes: Double,
            steps: [(String, String, String?)]
        ) -> [String: Any] {
            var agent: [String: Any] = [
                "id": id, "name": name, "status": status, "started_at": ago(minutes),
                "steps": steps.enumerated().map { index, step in
                    var object: [String: Any] = [
                        "id": "\(id)-\(index)", "tool": step.0, "arg": step.1,
                    ]
                    object["result"] = step.2
                    return object
                },
            ]
            agent["activity"] = activity
            return agent
        }

        /// A subagent or background command for the bar above the composer.
        private func backgroundItem(
            _ id: String, _ kind: String, _ name: String, _ description: String?,
            status: String, started: Double, finished: Double? = nil
        ) -> [String: Any] {
            var item: [String: Any] = [
                "id": id, "kind": kind, "name": name, "status": status,
                "started_at": ago(started),
            ]
            item["description"] = description
            item["finished_at"] = finished.map(ago)
            return item
        }

        private mutating func buildTodoUi() {
            let repo = "todo-ui"
            session(
                "c1", repo: repo, title: "Validate contact form with zod", state: "waiting",
                minutes: 2, permission: "default", branch: "agent/contact-zod",
                tasks: [
                    Self.task("1", "Read the route and the form", "completed"),
                    Self.task("2", "Install zod", "in_progress", active: "Installing zod"),
                    Self.task("3", "Write lib/contact-schema.ts", "pending"),
                    Self.task("4", "Show inline errors in ContactForm", "pending"),
                ],
                agents: [
                    agent(
                        "main", "main", status: "running",
                        activity: "Bash npm install zod (needs approval)", minutes: 2,
                        steps: [
                            ("Read", "app/api/contact/route.ts", "31 lines"),
                            ("Read", "components/ContactForm.tsx", "88 lines"),
                            ("Read", "package.json", "zod not installed"),
                            ("Bash", "npm install zod", nil),
                        ])
                ],
                context: 41)
            transcript(
                "c1",
                [
                    Self.user(
                        "Validate the contact form on the server with zod and show inline errors under each field."
                    ),
                    Self.text(
                        "The form posts to `app/api/contact/route.ts` with no validation at all. I will add one zod schema shared by the form and the route."
                    ),
                ]
                    + Self.tool(
                        "t1", "Read", ["file_path": "app/api/contact/route.ts"],
                        result: Array(repeating: "line", count: 31).joined(separator: "\n"))
                    + Self.tool(
                        "t2", "Read", ["file_path": "components/ContactForm.tsx"],
                        result: Array(repeating: "line", count: 88).joined(separator: "\n"))
                    + Self.tool(
                        "t3", "Bash", ["command": "npm ls zod"], result: "zod not installed")
                    + [Self.approvalEvent("q1", kind: "permission")])
            approval(
                "q1", session: "c1", repo: repo, title: "Validate contact form with zod",
                kind: "permission",
                payload: [
                    "tool": "Bash", "input": ["command": "npm install zod"],
                    "title": "Adds zod so one schema is shared by the form and the API route.",
                    "always_rule": "Bash(npm install:*)",
                ])

            session(
                "c2", repo: repo, title: "Update publications from BibTeX", state: "running",
                minutes: 9, effort: "low", branch: "agent/bibtex",
                tasks: [
                    Self.task("1", "Parse refs.bib into entries", "completed"),
                    Self.task("2", "Map fields to the Publication type", "completed"),
                    Self.task("3", "Render the list grouped by year", "completed"),
                    Self.task(
                        "4", "Add DOI and PDF links", "in_progress", active: "Adding DOI links"),
                    Self.task("5", "Sort by year, then venue", "pending"),
                    Self.task("6", "Snapshot test for /publications", "pending"),
                ],
                agents: [
                    agent(
                        "main", "main", status: "running",
                        activity: "Read app/publications/page.tsx", minutes: 9,
                        steps: [
                            ("Read", "content/refs.bib", "14 entries"),
                            ("Write", "lib/bibtex.ts", "+64"),
                            ("Edit", "app/publications/page.tsx", "+38 -52"),
                            ("Bash", "npm run build", "compiled"),
                        ]),
                    agent(
                        "toolu_explore", "Explore", status: "running",
                        activity: "Grep \"doi\" content/refs.bib", minutes: 1,
                        steps: [
                            ("Glob", "content/**/*.bib", "1 file"),
                            ("Grep", "\"doi\" content/refs.bib", nil),
                        ]),
                ],
                background: [
                    backgroundItem(
                        "toolu_check", "agent", "general-purpose", "Check BibTeX field names",
                        status: "done", started: 7, finished: 5.6),
                    backgroundItem(
                        "toolu_dev", "bash", "npm run dev", "Dev server for /publications",
                        status: "running", started: 6.2),
                    backgroundItem(
                        "toolu_test", "bash", "npm test -- publications", "Publication tests",
                        status: "failed", started: 4, finished: 3.4),
                    backgroundItem(
                        "toolu_explore", "agent", "Explore", "Find entries with a DOI",
                        status: "running", started: 1.1),
                ],
                context: 86,
                queued: [
                    "Also show the venue in italics after the title",
                    "Then run the snapshot test and fix anything it finds",
                ])
            transcript(
                "c2",
                [
                    Self.user(
                        "Regenerate the publications page from content/refs.bib. Group by year, newest first, and link DOIs."
                    ),
                    Self.text(
                        "Plan: parse `refs.bib`, map entries to the `Publication` type, then render the list grouped by year. After that: links, sorting and a snapshot test."
                    ),
                ]
                    + Self.tool(
                        "t4", "Read", ["file_path": "content/refs.bib"],
                        result: Array(repeating: "@article{}", count: 14).joined(separator: "\n"))
                    + Self.tool(
                        "t5", "Write", ["file_path": "lib/bibtex.ts"],
                        result:
                            "+export function parseBib(src: string): Publication[] {\n+  return entries(src).map(toPublication);\n+}"
                    )
                    + Self.tool(
                        "t6", "Edit", ["file_path": "app/publications/page.tsx"],
                        result: "+38 -52")
                    + Self.tool("t7", "Bash", ["command": "npm run build"], result: "compiled")
                    + [
                        Self.text(
                            "The list renders 14 entries grouped under **2026**, **2025** and **2024**. First batch is done. I asked `Explore` to find which entries carry a DOI before I add links."
                        ),
                        Self.text(
                            """
                            ## Next steps
                            DOIs link to [doi.org](https://doi.org) and PDFs open in a new tab.

                            - Add `doi` and `pdf` to the *Publication* type
                            - Sort by year, then venue
                              - ties keep the BibTeX order
                            1. Snapshot test for **/publications**

                            ```ts
                            export const doiURL = (doi: string) =>
                              `https://doi.org/${doi}`;
                            ```
                            See https://www.bibtex.org/Format for the field list.
                            """
                        ),
                    ])

            session(
                "c3", repo: repo, title: "Dark mode polish", state: "idle", minutes: 27,
                model: "opus", branch: "agent/dark-polish",
                tasks: [
                    Self.task("1", "Raise muted text contrast", "completed"),
                    Self.task("2", "Restore the toggle focus ring", "completed"),
                    Self.task("3", "Set the theme before first paint", "completed"),
                ],
                background: [
                    backgroundItem(
                        "toolu_find", "agent", "Explore", "Find theme toggles", status: "done",
                        started: 40, finished: 38.5),
                    backgroundItem(
                        "toolu_watch", "bash", "npm run build -- --watch", "Rebuild on change",
                        status: "running", started: 31),
                ])
            transcript(
                "c3",
                [
                    Self.user(
                        "Polish dark mode: muted text is too faint, the toggle loses its focus ring, and the page flashes white on load."
                    )
                ]
                    + Self.tool(
                        "t8", "Edit", ["file_path": "app/globals.css"],
                        result:
                            "-  --muted: #6b6f7a;\n+  --muted: #a1a6b3;\n+  color-scheme: light dark;"
                    )
                    + Self.tool("t9", "Bash", ["command": "npm test"], result: "9 passed")
                    + [
                        Self.text(
                            "Done. Muted text now passes 4.5:1 in dark mode, the toggle keeps its focus ring, and the theme is set before first paint, so there is no white flash."
                        ),
                        Self.text(
                            """
                            To check it yourself, start the dev server and open the page in dark mode:

                            ```bash
                            npm run dev
                            ```

                            The theme tests run with:

                            ```
                            npm test -- theme
                            ```

                            The tokens live in:

                            ```css
                            :root { color-scheme: light dark; }
                            ```
                            """
                        ),
                        Self.approvalEvent("q2", kind: "review"),
                    ])
            approval(
                "q2", session: "c3", repo: repo, title: "Dark mode polish", kind: "review",
                payload: [
                    "base": "main", "files": 3, "additions": 48, "deletions": 19,
                    "paths": ["app/globals.css", "components/ThemeToggle.tsx", "app/layout.tsx"],
                    "summary":
                        "Raised contrast for muted text, kept the toggle focus ring, removed the white flash on load.",
                ])

            session(
                "c4", repo: repo, title: "Fix mobile nav overflow", state: "waiting", minutes: 5,
                model: "haiku", effort: "low", permission: "default", branch: "agent/mobile-nav")
            approval(
                "q5", session: "c4", repo: repo, title: "Fix mobile nav overflow", kind: "question",
                payload: [
                    "tool_use_id": "tq5",
                    "questions": [
                        [
                            "question": "Collapse the links into a menu, or let them wrap?",
                            "multi_select": false,
                            "options": [
                                [
                                    "label": "Menu button under 480px",
                                    "description":
                                        "One tap opens the links; the bar stays one line.",
                                    "recommended": true,
                                ],
                                [
                                    "label": "Let the links wrap",
                                    "description": "Simplest, but the bar grows to two lines.",
                                    "recommended": false,
                                ],
                            ],
                        ]
                    ],
                ])
            transcript(
                "c4",
                [Self.user("The nav overflows on 360px wide phones. Fix it.")]
                    + Self.tool(
                        "t10", "Read", ["file_path": "components/Nav.tsx"],
                        result: Array(repeating: "x", count: 64).joined(separator: "\n"))
                    + [
                        Self.text(
                            "I can reproduce it at 360px: the link row never wraps. Paused here, as you asked, before changing anything."
                        ),
                        Self.approvalEvent("q5", kind: "question"),
                    ])

            session(
                "c8", repo: repo, title: "Plan the search page", state: "waiting", minutes: 3,
                model: "opus", effort: "high", permission: "plan", branch: "agent/search",
                context: 23)
            transcript(
                "c8",
                [
                    Self.user(
                        "Plan a search page for projects and publications. Do not change anything yet."
                    ),
                    Self.text(
                        "I read the routes and the content loaders. Here is the plan."),
                    Self.approvalEvent("q6", kind: "plan"),
                ])
            approval(
                "q6", session: "c8", repo: repo, title: "Plan the search page", kind: "plan",
                payload: [
                    "tool_use_id": "tp6",
                    "plan": """
                    ## Search page

                    Search projects and publications from one field, on the client.

                    1. Build an index in `lib/search.ts` from the content loaders
                    2. Add `app/search/page.tsx` with a field and grouped results
                    3. Link it from the nav with **⌘K**

                    - No new dependencies
                    - A test for ranking in `lib/search.test.ts`
                    """,
                ])

            session(
                "c5", repo: repo, title: "Add project thumbnails", state: "closed",
                minutes: 2880, branch: "agent/thumbnails",
                pr: pullRequest(
                    18, "Add project thumbnails", state: "merged",
                    checks: [("lint", "success"), ("test", "success")]))
            session(
                "c6", repo: repo, title: "Rewrite the about section", state: "idle",
                minutes: 1500, model: "opus", branch: "agent/about", pinned: true,
                pr: pullRequest(
                    21, "Rewrite the about section",
                    checks: [
                        ("lint", "success"), ("test (node 22)", "failure"),
                        ("e2e / chromium", "failure"), ("build", "success"),
                    ], mergeable: false))
            let rss = pullRequest(
                23, "Add an RSS feed for publications",
                checks: [("lint", "success"), ("test", "success"), ("build", "success")])
            session(
                "c9", repo: repo, title: "Add an RSS feed", state: "idle", minutes: 40,
                branch: "agent/rss-feed", pr: rss)
            transcript(
                "c6",
                [
                    Self.user("Rewrite the about section in a warmer first person voice."),
                    Self.text(
                        "Rewrote `content/about.md` and opened pull request #21. CI reports two failing checks: `test (node 22)` and `e2e / chromium`."
                    ),
                ])
            transcript(
                "c9",
                [
                    Self.user("Add an RSS feed for the publications page."),
                    Self.text(
                        "Added `app/feed.xml/route.ts`, which builds the feed from the BibTeX loader, and linked it from the page head. Checks passed on pull request #23."
                    ),
                ])
            approval(
                "q7", session: "c9", repo: repo, title: "Add an RSS feed", kind: "merge",
                payload: [
                    "number": 23, "title": rss["title"]!, "url": rss["url"]!,
                    "head_sha": "9f2c4e1", "checks": rss["checks"]!,
                ])
            session(
                "c7", repo: repo, title: "Try a serif headline font", state: "closed",
                minutes: 8000, branch: "agent/serif", archived: true)
        }

        /// Chats started in Claude Code itself: one still open there, one in a Claude Code
        /// worktree, an older one and a scheduled (automated) one.
        private mutating func buildClaudeChats() {
            func chat(
                _ id: String, _ title: String, minutes: Double, count: Int,
                worktree: String? = nil, open: Bool = false, automated: Bool = false
            ) -> ClaudeChat {
                let folder = "/Users/me/Projects/todo-ui"
                return ClaudeChat(
                    id: id, repo: "todo-ui", title: title,
                    cwd: worktree.map { "\(folder)/.claude/worktrees/\($0)" } ?? folder,
                    worktree: worktree, createdAt: now.addingTimeInterval(-(minutes + 40) * 60),
                    lastActivityAt: now.addingTimeInterval(-minutes * 60), messageCount: count,
                    openInClaudeCode: open, automated: automated)
            }
            claudeChats = [
                chat("cc-hero", "Fix the hero image on mobile", minutes: 12, count: 9, open: true),
                chat(
                    "cc-pipeline", "Explain the build pipeline", minutes: 95, count: 4,
                    worktree: "pipeline"),
                chat("cc-next", "Bump Next.js to 16", minutes: 60 * 50, count: 22),
                chat(
                    "cc-links", "Nightly broken link check", minutes: 300, count: 2,
                    automated: true),
            ]
            let hero: [(String, [String: Any])] =
                [
                    Self.user(
                        "The hero image is cut off on phones. Can you fix it without changing the desktop layout?"
                    ),
                    Self.text(
                        "The image uses a fixed height of 520px. On narrow screens that crops the portrait. I will switch it to an aspect ratio with `object-fit: cover`."
                    ),
                ]
                + Self.tool(
                    "cc-t1", "Read", ["file_path": "components/Hero.tsx"],
                    result: Array(repeating: "line", count: 64).joined(separator: "\n"))
                + Self.tool(
                    "cc-t2", "Edit", ["file_path": "components/Hero.tsx"], result: "Updated")
                + [
                    Self.text(
                        "Done. `Hero.tsx` now uses `aspect-ratio: 4 / 5` below 640px and keeps the 520px height on desktop."
                    ),
                    Self.user("Looks right. Also check the About page portrait."),
                ]
            let pipeline: [(String, [String: Any])] = [
                Self.user(
                    "Explain how the build pipeline turns BibTeX into the publications page."),
                Self.text(
                    "`scripts/bib.ts` parses `content/papers.bib` at build time, sorts entries by year and writes `generated/publications.json`, which `app/publications/page.tsx` imports."
                ),
            ]
            for (id, bodies) in [("cc-hero", hero), ("cc-pipeline", pipeline)] {
                claudeEvents[id] = bodies.enumerated().map { index, body in
                    try! Self.decode([
                        "id": index + 1, "type": body.0, "ts": ago(20), "session_id": id,
                        "payload": body.1,
                    ])
                }
            }
        }

        private mutating func buildWeatherForecast() {
            let repo = "weather-forecast"
            session(
                "n1", repo: repo, title: "Scene graph engine (plan B01 to B10)", state: "running",
                minutes: 72, model: "opus", effort: "high", branch: "agent/scene-graph")
            session(
                "n2", repo: repo, title: "Dialogue tree parser", state: "waiting", minutes: 14,
                permission: "plan", branch: "agent/dialogue-parser")
            approval(
                "q3", session: "n2", repo: repo, title: "Dialogue tree parser", kind: "question",
                payload: [
                    "tool_use_id": "tq",
                    "questions": [
                        [
                            "question": "Store branches as a DAG or a tree?", "multi_select": false,
                            "options": [
                                ["label": "DAG", "recommended": true],
                                ["label": "Tree", "recommended": false],
                            ],
                        ]
                    ],
                ])
            session(
                "n3", repo: repo, title: "Save-game format migration", state: "idle", minutes: 48,
                model: "opus", branch: "agent/save-v3")
            approval(
                "q4", session: "n3", repo: repo, title: "Save-game format migration",
                kind: "review",
                payload: [
                    "files": 7, "additions": 212, "deletions": 64, "paths": ["src/save/v3.ts"],
                ])
        }

        /// h1 repeats the same failing test run, so it looks stuck; h2 has a long history
        /// for paging around a search hit.
        private mutating func buildMapViewer() {
            let repo = "map-viewer"
            let pytest = ["command": "pytest tests/test_fetch.py -x"]
            session(
                "h1", repo: repo, title: "Add retry with backoff to the scraper",
                state: "running", minutes: 12, branch: "agent/scraper-retry",
                agents: [
                    agent(
                        "main", "main", status: "running",
                        activity: "Bash pytest tests/test_fetch.py -x", minutes: 12,
                        steps: [
                            ("Edit", "scraper/fetch.py", "+31 -4"),
                            ("Bash", "pytest tests/test_fetch.py -x", "1 failed"),
                            ("Bash", "pytest tests/test_fetch.py -x", "1 failed"),
                        ])
                ],
                stuck: [
                    "reason": "repeating", "since": ago(6),
                    "details": "Called Bash 5 times in a row with the same input",
                ])
            transcript(
                "h1",
                [
                    Self.user(
                        "Add retry with exponential backoff to fetch_page, capped at 30 s, and make the tests pass."
                    ),
                    Self.text(
                        "I'll wrap `fetch_page` in a retry loop with jittered exponential backoff and a 30 s cap."
                    ),
                ]
                    + Self.tool(
                        "h1t1", "Edit", ["file_path": "scraper/fetch.py"], result: "+31 -4")
                    + (2...6).flatMap { index in
                        Self.tool(
                            "h1t\(index)", "Bash", pytest,
                            result: "FAILED tests/test_fetch.py::test_backoff_caps_at_30s\n"
                                + "1 failed, 11 passed"
                        )
                    })
            session(
                "h2", repo: repo, title: "Benchmark the parser on 200 pages", state: "idle",
                minutes: 180, model: "opus", branch: "agent/parser-bench")
            transcript(
                "h2",
                (1...120).flatMap { round in
                    round == 61
                        ? [
                            Self.user(
                                "Page 412 times out on a 429. Add a retry for rate limits and keep the 10 s timeout."
                            ),
                            Self.text(
                                "Added a retry with backoff for 429 responses only. Page 412 now parses in 640 ms, and the 10 s timeout still applies to each attempt."
                            ),
                        ]
                        : [
                            Self.user("Run page batch \(round) and report the slowest file."),
                            Self.text(
                                "Batch \(round): 20 pages parsed in \(10 + round % 7).\(round % 10) s. Slowest: page-\(round * 7).html at \(300 + round * 3) ms."
                            ),
                        ]
                })
        }
    }
#endif
