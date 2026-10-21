import Foundation

/// A new chat started from an issue (B101): the issue is its first message, so it may be
/// sent without text.
public enum IssueDraft {
    /// The quiet line by the composer.
    public static func note(_ issue: IssueRef) -> String {
        "Issue #\(issue.number) will be the first message. Add anything, or press send"
    }

    public static func canSend(text: String, issue: IssueRef?) -> Bool {
        issue != nil || !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}

/// A user message Nest wrote from GitHub, shown as its own bubble (B101).
public enum GitHubMessage: Sendable, Hashable {
    case issue(IssueBubble)
    case reviewFeedback(ReviewFeedbackBubble)

    public static func of(_ message: UserMessage) -> GitHubMessage? {
        if let info = message.issue {
            return .issue(IssueBubble(text: message.text, info: info))
        }
        return message.reviewFeedback.map {
            .reviewFeedback(ReviewFeedbackBubble(text: message.text, info: $0))
        }
    }

    /// The user's own words in the message, before what Nest added.
    public var own: String {
        switch self {
        case .issue(let bubble): bubble.own
        case .reviewFeedback: ""
        }
    }
}

/// An issue message's bubble: the user's own text, a grey line, the issue's title, a few
/// lines of its body and how many comments came with it.
public struct IssueBubble: Sendable, Hashable {
    /// How much of the body the bubble shows, in lines and characters.
    public static let excerptLines = 3
    public static let excerptLimit = 240

    public let own: String
    /// "Issue #118 from GitHub · bug, ui".
    public let header: String
    public let title: String
    public let excerpt: String
    /// "3 comments included"; nil without any.
    public let comments: String?
    public let url: String

    /// The daemon writes the user's text, then the issue from its line
    /// "Issue #118 from GitHub, fetched by Nest: <title>", with the body as the first
    /// fenced block after it.
    public init(text: String, info: IssueMessageInfo) {
        let lines = text.components(separatedBy: "\n")
        let marker = "Issue #\(info.number) from GitHub"
        let start = lines.firstIndex { $0.hasPrefix(marker) } ?? lines.count
        own = lines[..<start].joined(separator: "\n")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        header = ([marker] + (info.labels.isEmpty ? [] : [info.labels.joined(separator: ", ")]))
            .joined(separator: " \u{00B7} ")
        title = info.title
        url = info.url
        let body = Fences.blocks(in: Array(lines[start...])).first?.text ?? ""
        let kept = body.components(separatedBy: "\n")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
            .prefix(Self.excerptLines)
            .joined(separator: "\n")
        excerpt =
            kept.count > Self.excerptLimit
            ? String(kept.prefix(Self.excerptLimit)) + "\u{2026}" : kept
        comments =
            info.comments == 0
            ? nil : "\(info.comments) comment\(info.comments == 1 ? "" : "s") included"
    }
}

/// A review feedback message's bubble: the grey line, then each comment's place and text.
public struct ReviewFeedbackBubble: Sendable, Hashable {
    public struct Item: Sendable, Hashable {
        /// Such as "src/a.py:12, octo": the line before the comment's fenced text.
        public let location: String
        public let text: String

        public init(location: String, text: String) {
            self.location = location
            self.text = text
        }
    }

    public let header: String
    public let items: [Item]

    public init(text: String, info: ReviewFeedbackInfo) {
        header = "Review feedback on #\(info.number), sent by Nest"
        items = Fences.blocks(in: text.components(separatedBy: "\n")).map { block in
            var location = block.before.trimmingCharacters(in: .whitespaces)
            if location.hasSuffix(":") {
                location.removeLast()
            }
            return Item(location: location, text: block.text)
        }
    }
}

/// The fenced blocks Nest wraps GitHub's text in: a line of three or more backticks, closed
/// by the same line, so the text inside cannot end it early.
enum Fences {
    struct Block {
        /// The last line with text before the fence.
        var before: String
        var text: String
    }

    static func blocks(in lines: [String]) -> [Block] {
        var blocks: [Block] = []
        var before = ""
        var index = 0
        while index < lines.count {
            let line = lines[index]
            index += 1
            guard isFence(line) else {
                if !line.trimmingCharacters(in: .whitespaces).isEmpty {
                    before = line
                }
                continue
            }
            let end = lines[index...].firstIndex(of: line) ?? lines.count
            blocks.append(Block(before: before, text: lines[index..<end].joined(separator: "\n")))
            before = ""
            index = end + 1
        }
        return blocks
    }

    private static func isFence(_ line: String) -> Bool {
        line.count >= 3 && line.allSatisfy { $0 == "`" }
    }
}
