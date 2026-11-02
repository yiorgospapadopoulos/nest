import Foundation

/// A Claude Code or Codex chat of a registered repo that Nest does not own yet: started in
/// the terminal, the desktop app or an editor. It opens read-only until it is adopted.
public struct ClaudeChat: Decodable, Sendable, Hashable, Identifiable {
    /// The engine the chat was started on (B113).
    public enum Engine: String, Sendable, Hashable {
        case claude, codex
    }

    /// Claude Code's session id, or Codex's thread id.
    public var id: String
    public var engine: Engine
    public var repo: String
    public var title: String
    /// The folder it ran in: the repo or one of Claude Code's worktrees in it.
    public var cwd: String
    /// The Claude Code worktree's name, if it ran in one.
    public var worktree: String?
    public var createdAt: Date
    public var lastActivityAt: Date
    public var messageCount: Int
    /// A Claude Code process has it open right now, so Nest may not send to it.
    public var openInClaudeCode: Bool
    /// Started by a script or tool rather than a person; hidden unless asked for.
    public var automated: Bool
    /// Archived in Nest: listed under Archived instead of Idle.
    public var archived: Bool

    public init(
        id: String, repo: String, title: String, cwd: String, worktree: String? = nil,
        createdAt: Date, lastActivityAt: Date, messageCount: Int,
        openInClaudeCode: Bool = false, automated: Bool = false, archived: Bool = false,
        engine: Engine = .claude
    ) {
        self.id = id
        self.engine = engine
        self.repo = repo
        self.title = title
        self.cwd = cwd
        self.worktree = worktree
        self.createdAt = createdAt
        self.lastActivityAt = lastActivityAt
        self.messageCount = messageCount
        self.openInClaudeCode = openInClaudeCode
        self.automated = automated
        self.archived = archived
    }

    enum CodingKeys: String, CodingKey {
        case id, repo, title, cwd, worktree, automated, archived, engine
        case createdAt = "created_at"
        case lastActivityAt = "last_activity_at"
        case messageCount = "message_count"
        case openInClaudeCode = "open_in_claude_code"
    }

    /// `automated`, `archived` and `engine` are optional, since older daemons do not send
    /// them; a chat without an engine is Claude Code's.
    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.init(
            id: try container.decode(String.self, forKey: .id),
            repo: try container.decode(String.self, forKey: .repo),
            title: try container.decode(String.self, forKey: .title),
            cwd: try container.decode(String.self, forKey: .cwd),
            worktree: try container.decodeIfPresent(String.self, forKey: .worktree),
            createdAt: try container.decode(Date.self, forKey: .createdAt),
            lastActivityAt: try container.decode(Date.self, forKey: .lastActivityAt),
            messageCount: try container.decode(Int.self, forKey: .messageCount),
            openInClaudeCode: try container.decode(Bool.self, forKey: .openInClaudeCode),
            automated: try container.decodeIfPresent(Bool.self, forKey: .automated) ?? false,
            archived: try container.decodeIfPresent(Bool.self, forKey: .archived) ?? false,
            engine: try container.decodeIfPresent(String.self, forKey: .engine)
                .flatMap(Engine.init(rawValue:)) ?? .claude)
    }

    /// "Claude Code" or "Codex", wherever the chat's engine is named.
    public var engineName: String {
        switch engine {
        case .claude: "Claude Code"
        case .codex: "Codex"
        }
    }

    /// The engine named on the sidebar row's second line: only Codex's (B113).
    public var rowLabel: String? { engine == .codex ? engineName : nil }

    /// Claude Code has it open right now; never so for a Codex chat.
    public var isOpenInClaudeCode: Bool { engine == .claude && openInClaudeCode }

    /// The sidebar row's tooltip.
    public var help: String {
        isOpenInClaudeCode ? "Open in Claude Code right now" : "Started in \(engineName)"
    }

    /// The read-only pane's line beside Continue in Nest.
    public var readOnlyNote: String {
        "Started in \(engineName). Read-only until you continue it here."
    }

    /// The workspace pane id of this chat; it cannot clash with session or draft ids.
    public var paneID: String { Self.panePrefix + id }

    static let panePrefix = "claude-code:"

    /// The Claude Code chat a pane shows, or nil for a Nest session or draft pane.
    public static func chatID(ofPane pane: String) -> String? {
        pane.hasPrefix(panePrefix) ? String(pane.dropFirst(panePrefix.count)) : nil
    }
}
