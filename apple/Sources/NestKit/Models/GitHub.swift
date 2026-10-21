import Foundation

/// The GitHub issue a chat was started from (B101); Nest only reads issues.
public struct IssueRef: Codable, Sendable, Hashable {
    public var number: Int
    public var title: String
    public var url: String

    public init(number: Int, title: String, url: String) {
        self.number = number
        self.title = title
        self.url = url
    }
}

/// Which issues a repo lists: all open ones, or those assigned to the user.
public enum IssueShow: String, UnknownSafeEnum {
    case all, mine
    case unknown
}

/// A pull request that refers to an issue.
public struct IssuePR: Decodable, Sendable, Hashable {
    public var number: Int
    public var url: String

    public init(number: Int, url: String) {
        self.number = number
        self.url = url
    }
}

/// What a click on a start screen issue row does.
public enum IssueClick: Sendable, Hashable {
    /// Opens the Nest chat already working on the issue.
    case open(chat: String)
    /// Starts a new chat from the issue.
    case start
}

/// An open issue, as `GET /api/repos/{name}/issues` lists it.
public struct IssueSummary: Decodable, Sendable, Hashable, Identifiable {
    public var number: Int
    public var title: String
    public var url: String
    public var labels: [String]
    /// Comments by people, not bots.
    public var comments: Int
    public var updatedAt: Date
    /// Pull requests that refer to it; none from older daemons.
    public var prs: [IssuePR]
    /// An open Nest chat started from it.
    public var chat: String?

    public init(
        number: Int, title: String, url: String, labels: [String], comments: Int,
        updatedAt: Date, prs: [IssuePR] = [], chat: String? = nil
    ) {
        self.number = number
        self.title = title
        self.url = url
        self.labels = labels
        self.comments = comments
        self.updatedAt = updatedAt
        self.prs = prs
        self.chat = chat
    }

    enum CodingKeys: String, CodingKey {
        case number, title, url, labels, comments, prs, chat
        case updatedAt = "updated_at"
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        number = try container.decode(Int.self, forKey: .number)
        title = try container.decode(String.self, forKey: .title)
        url = try container.decode(String.self, forKey: .url)
        labels = try container.decode([String].self, forKey: .labels)
        comments = try container.decode(Int.self, forKey: .comments)
        updatedAt = try container.decode(Date.self, forKey: .updatedAt)
        prs = try container.decodeIfPresent([IssuePR].self, forKey: .prs) ?? []
        chat = try container.decodeIfPresent(String.self, forKey: .chat)
    }

    public var id: Int { number }

    public var ref: IssueRef { IssueRef(number: number, title: title, url: url) }

    /// The start screen row's grey line: "#118 · PR #120 · bug, ui · 3 comments".
    public var line: String {
        (["#\(number)"] + [prsText, lineAfterPRs].compactMap { $0 })
            .joined(separator: " \u{00B7} ")
    }

    /// "PR #10, #12", after which the row draws its part; nil without any.
    public var prsText: String? {
        prs.isEmpty ? nil : "PR " + prs.map { "#\($0.number)" }.joined(separator: ", ")
    }

    /// The labels and the comment count.
    public var lineAfterPRs: String? {
        var parts: [String] = []
        if !labels.isEmpty {
            parts.append(labels.joined(separator: ", "))
        }
        if comments > 0 {
            parts.append(comments == 1 ? "1 comment" : "\(comments) comments")
        }
        return parts.isEmpty ? nil : parts.joined(separator: " \u{00B7} ")
    }

    /// Opens its chat when it has one; Option-click always starts a new one.
    public func click(option: Bool) -> IssueClick {
        if let chat, !option {
            return .open(chat: chat)
        }
        return .start
    }

    /// The row's help.
    public var help: String {
        chat == nil
            ? "Start a chat from #\(number)"
            : "Open the chat for #\(number); Option-click starts a new one"
    }
}

/// A repo's open issues; `available` is false without a GitHub remote.
public struct IssueList: Decodable, Sendable, Hashable {
    public var available: Bool
    public var show: IssueShow
    public var issues: [IssueSummary]

    public init(available: Bool, show: IssueShow, issues: [IssueSummary]) {
        self.available = available
        self.show = show
        self.issues = issues
    }
}

public enum ReviewCommentKind: String, UnknownSafeEnum {
    /// An unresolved review thread on a line.
    case thread
    /// A review's own text.
    case review
    case unknown
}

/// One piece of review feedback on a chat's pull request: an unresolved thread, or a
/// review's general comment.
public struct ReviewComment: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var kind: ReviewCommentKind
    public var path: String?
    /// The line, or the line it was on once outdated.
    public var line: Int?
    public var outdated: Bool
    public var author: String
    public var body: String
    public var url: String
    public var createdAt: Date

    enum CodingKeys: String, CodingKey {
        case id, kind, path, line, outdated, author, body, url
        case createdAt = "created_at"
    }

    /// "src/a.py:12", "src/a.py (outdated, was line 12)" or "General review comment".
    public var location: String {
        path.map(place) ?? "General review comment"
    }

    /// As `location`, with the file's name only.
    public var shortLocation: String {
        path.map { place(URL(fileURLWithPath: $0).lastPathComponent) }
            ?? "General review comment"
    }

    private func place(_ file: String) -> String {
        guard let line else { return file }
        return outdated ? "\(file) (outdated, was line \(line))" : "\(file):\(line)"
    }
}

/// The review feedback Nest keeps for a chat's open pull request.
public struct PRReview: Codable, Sendable, Hashable {
    public var items: [ReviewComment]
    /// Ids of the items already sent to the agent.
    public var sent: [String]
    public var changesRequested: Bool
    /// New comments go to the agent as they arrive, without waiting in Needs you.
    public var autoSend: Bool
    /// Thread item ids (`<thread>:<comment>`) Nest replied on with the commit that
    /// addressed them; none from older daemons.
    public var replied: [String]

    enum CodingKeys: String, CodingKey {
        case items, sent, replied
        case changesRequested = "changes_requested"
        case autoSend = "auto_send"
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        items = try container.decode([ReviewComment].self, forKey: .items)
        sent = try container.decode([String].self, forKey: .sent)
        changesRequested = try container.decode(Bool.self, forKey: .changesRequested)
        autoSend = try container.decode(Bool.self, forKey: .autoSend)
        replied = try container.decodeIfPresent([String].self, forKey: .replied) ?? []
    }

    /// The items not sent yet.
    public var pending: [ReviewComment] {
        let sent = Set(sent)
        return items.filter { !sent.contains($0.id) }
    }

    /// Threads sent to the agent that Nest has not replied on yet: the next push to the
    /// pull request replies on each. A thread's item id names its latest comment, so a
    /// thread someone answered after Nest's reply waits for one again.
    public var threadsToReply: Int {
        let sent = Set(sent)
        let replied = Set(replied)
        return items.count { item in
            item.kind == .thread && sent.contains(item.id) && !replied.contains(item.id)
        }
    }
}

/// A review comments approval's payload: the pending comments on the pull request.
public struct ReviewCommentsRequest: Decodable, Sendable, Hashable {
    public var number: Int
    public var url: String
    public var changesRequested: Bool
    public var comments: [ReviewComment]

    enum CodingKeys: String, CodingKey {
        case number, url, comments
        case changesRequested = "changes_requested"
    }

    /// "3 review comments on #131".
    public var summary: String {
        let count = comments.count
        return "\(count) review comment\(count == 1 ? "" : "s") on #\(number)"
    }

    /// The grey line under a chat's latest reply while the comments wait.
    public var chatLine: String {
        let count = comments.count
        let comments = "\(count) comment\(count == 1 ? "" : "s")"
        let what = changesRequested ? "changes requested, \(comments)" : comments
        return "Review on #\(number): \(what). See Needs you"
    }
}

/// The issue a user message was written from, on its `session.user_message` event.
public struct IssueMessageInfo: Codable, Sendable, Hashable {
    public var number: Int
    public var title: String
    public var url: String
    public var labels: [String]
    /// How many comments came with it.
    public var comments: Int

    public init(number: Int, title: String, url: String, labels: [String], comments: Int) {
        self.number = number
        self.title = title
        self.url = url
        self.labels = labels
        self.comments = comments
    }
}

/// The review comments a user message carries, on its `session.user_message` event.
public struct ReviewFeedbackInfo: Codable, Sendable, Hashable {
    public var number: Int
    public var count: Int

    public init(number: Int, count: Int) {
        self.number = number
        self.count = count
    }
}

/// `POST /api/sessions/{id}/pr/review-feedback` for some comments only.
struct ReviewFeedbackRequest: Encodable {
    var ids: [String]
}

/// `PATCH /api/sessions/{id}/pr/review`.
struct ReviewAutoSendRequest: Encodable {
    var autoSend: Bool

    enum CodingKeys: String, CodingKey {
        case autoSend = "auto_send"
    }
}
