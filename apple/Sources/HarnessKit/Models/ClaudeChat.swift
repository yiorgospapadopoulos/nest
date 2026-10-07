import Foundation

/// A Claude Code chat of a registered repo that harness does not own yet: started in the
/// terminal, the desktop app or an editor. It opens read-only until it is adopted.
public struct ClaudeChat: Decodable, Sendable, Hashable, Identifiable {
    /// Claude Code's session id.
    public var id: String
    public var repo: String
    public var title: String
    /// The folder it ran in: the repo or one of Claude Code's worktrees in it.
    public var cwd: String
    /// The Claude Code worktree's name, if it ran in one.
    public var worktree: String?
    public var createdAt: Date
    public var lastActivityAt: Date
    public var messageCount: Int
    /// A Claude Code process has it open right now, so harness may not send to it.
    public var openInClaudeCode: Bool
    /// Started by a script or tool rather than a person; hidden unless asked for.
    public var automated: Bool

    public init(
        id: String, repo: String, title: String, cwd: String, worktree: String? = nil,
        createdAt: Date, lastActivityAt: Date, messageCount: Int,
        openInClaudeCode: Bool = false, automated: Bool = false
    ) {
        self.id = id
        self.repo = repo
        self.title = title
        self.cwd = cwd
        self.worktree = worktree
        self.createdAt = createdAt
        self.lastActivityAt = lastActivityAt
        self.messageCount = messageCount
        self.openInClaudeCode = openInClaudeCode
        self.automated = automated
    }

    enum CodingKeys: String, CodingKey {
        case id, repo, title, cwd, worktree, automated
        case createdAt = "created_at"
        case lastActivityAt = "last_activity_at"
        case messageCount = "message_count"
        case openInClaudeCode = "open_in_claude_code"
    }

    /// `automated` is optional, since older daemons do not send it.
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
            automated: try container.decodeIfPresent(Bool.self, forKey: .automated) ?? false)
    }

    /// The workspace pane id of this chat; it cannot clash with session or draft ids.
    public var paneID: String { Self.panePrefix + id }

    static let panePrefix = "claude-code:"

    /// The Claude Code chat a pane shows, or nil for a harness session or draft pane.
    public static func chatID(ofPane pane: String) -> String? {
        pane.hasPrefix(panePrefix) ? String(pane.dropFirst(panePrefix.count)) : nil
    }
}
