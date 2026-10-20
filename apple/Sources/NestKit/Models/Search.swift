import Foundation

/// What a search hit matched (D035).
public enum SearchHitKind: String, UnknownSafeEnum {
    case title
    case user
    case assistant
    case tool
    case toolResult = "tool_result"
    /// The title of a Claude Code chat Nest does not own.
    case claudeChat = "claude_chat"
    case unknown

    /// The palette's words for where the match is, in a chat on Claude.
    public var label: String { label(agent: "Claude") }

    /// The palette's words for where the match is; an answer is `agent`'s, the chat's
    /// engine (B91).
    public func label(agent: String) -> String {
        switch self {
        case .title: "Title"
        case .user: "You"
        case .assistant: agent
        case .tool: "Tool call"
        case .toolResult: "Tool output"
        case .claudeChat: "Claude Code chat"
        case .unknown: "Message"
        }
    }
}

/// One match of `GET /api/search`.
public struct SearchHit: Decodable, Sendable, Hashable {
    /// The Nest session, or the Claude Code chat id for `claudeChat` hits.
    public var sessionID: String
    public var repo: String
    /// The chat's current title.
    public var title: String
    /// The event to scroll to; nil for title and Claude Code chat hits.
    public var eventID: Int?
    public var ts: Date
    public var kind: SearchHitKind
    /// Matched words wrapped in `[[` and `]]`.
    public var snippet: String

    enum CodingKeys: String, CodingKey {
        case repo, title, ts, kind, snippet
        case sessionID = "session_id"
        case eventID = "event_id"
    }

    /// The pane that shows the hit's chat.
    public var pane: String {
        kind == .claudeChat ? ClaudeChat.panePrefix + sessionID : sessionID
    }
}

public struct SearchResults: Decodable, Sendable, Hashable {
    /// Best match first.
    public var hits: [SearchHit]
    /// True while the daemon still indexes the stored history for the first time.
    public var indexing: Bool

    public init(hits: [SearchHit], indexing: Bool) {
        self.hits = hits
        self.indexing = indexing
    }
}

/// A stretch of a snippet, matched or not.
public struct SnippetPart: Sendable, Hashable {
    public let text: String
    public let matched: Bool
}

public enum Snippet {
    /// Splits a snippet at its `[[` and `]]` markers; an unclosed `[[` marks the rest.
    public static func parts(_ snippet: String) -> [SnippetPart] {
        var parts: [SnippetPart] = []
        var rest = Substring(snippet)
        while let open = rest.range(of: "[[") {
            parts.append(SnippetPart(text: String(rest[..<open.lowerBound]), matched: false))
            rest = rest[open.upperBound...]
            let close = rest.range(of: "]]")
            parts.append(
                SnippetPart(
                    text: String(rest[..<(close?.lowerBound ?? rest.endIndex)]), matched: true))
            rest = close.map { rest[$0.upperBound...] } ?? ""
        }
        parts.append(SnippetPart(text: String(rest), matched: false))
        return parts.filter { !$0.text.isEmpty }
    }
}
