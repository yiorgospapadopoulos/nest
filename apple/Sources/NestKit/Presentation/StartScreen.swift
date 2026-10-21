import Foundation

/// What the empty workspace's start screen shows (B90, design I): the question over the
/// docked composer, and beside it a column with what waits on the user in this project,
/// its open GitHub issues (B101) and its latest chats.
public struct StartScreen: Sendable, Equatable {
    /// One row of "Waiting on you": a chat, the right panel's tone and its Needs you line.
    public struct Waiting: Sendable, Hashable, Identifiable {
        public let id: String
        public let chat: String
        public let title: String
        public let tone: StatusTone
        public let line: NeedsYouLine
    }

    /// One row of "Recent": a chat and when it was last active.
    public struct Recent: Sendable, Hashable, Identifiable {
        public let chat: String
        public let title: String
        public let date: Date

        public var id: String { chat }
    }

    /// As many recent chats as sit beside the composer without pushing the column up.
    public static let recentLimit = 4
    /// The open issues list shows this many rows and scrolls past them.
    public static let issueRows = 5
    public static let columnWidth = 250.0
    /// Below this workspace width the column leaves the room to the composer.
    public static let columnMinWidth = 760.0

    public let waiting: [Waiting]
    public let recent: [Recent]
    /// The open issues, newest updated first; none while the repo has no GitHub.
    public let issues: [IssueSummary]
    public let issueCount: Int
    /// The section shows with issues, and with Mine even without, so its switch stays.
    public let showsIssues: Bool

    /// `approvals`, `checksFailed` and `stuck` as the right panel's Needs you card reads
    /// them; `sessions` the project's chats; `issues` its open issues, once read.
    public init(
        approvals: [Approval], checksFailed: [Session], stuck: [Session], sessions: [Session],
        issues: IssueList? = nil
    ) {
        let pending = approvals.filter { Pixie.id(ofRepo: $0.repo) == nil }.map { approval in
            Waiting(
                id: "approval-\(approval.id)", chat: approval.sessionID, title: approval.title,
                tone: approval.kind == .review || approval.kind == .merge ? .review : .waiting,
                line: NeedsYouLine.of(approval))
        }
        let failed = checksFailed.map {
            Waiting(
                id: "checks-\($0.id)", chat: $0.id, title: $0.title, tone: .failed,
                line: NeedsYouLine.checksFailed($0))
        }
        let stuckRows = stuck.map {
            Waiting(
                id: "stuck-\($0.id)", chat: $0.id, title: $0.title, tone: .waiting,
                line: NeedsYouLine.stuck($0))
        }
        waiting = pending + failed + stuckRows
        let listed = Set(waiting.map(\.chat))
        recent =
            sessions
            .filter { !$0.isArchived && !listed.contains($0.id) }
            .sorted { ($0.updatedAt, $0.id) > ($1.updatedAt, $1.id) }
            .prefix(Self.recentLimit)
            .map { Recent(chat: $0.id, title: $0.title, date: $0.updatedAt) }
        let open = issues.flatMap { $0.available ? $0.issues : nil } ?? []
        self.issues = open
        issueCount = open.count
        showsIssues = !open.isEmpty || (issues.map { $0.available && $0.show == .mine } ?? false)
    }

    /// More issues than rows: the list scrolls.
    public var issuesScroll: Bool { issues.count > Self.issueRows }

    /// The quiet line of Mine with nothing assigned.
    public var issuesEmptyLine: String? {
        showsIssues && issues.isEmpty ? "No open issues assigned to you" : nil
    }

    /// "Open issues · 7".
    public var issuesLabel: String { "Open issues \u{00B7} \(issueCount)" }

    /// The column shows while it has something to list and the workspace has room for it.
    public func showsColumn(width: Double) -> Bool {
        width >= Self.columnMinWidth && !(waiting.isEmpty && recent.isEmpty && !showsIssues)
    }

    /// The ways to ask, as the words before and after the project: "in <project>" or "for
    /// <project>" is left out without one.
    private static let questions: [(lead: String, link: String, tail: String)] = [
        ("What should we work on", "in", ""), ("What's next", "for", ""),
        ("Where should we start", "in", ""), ("What are we building", "in", " today"),
        ("What needs doing", "in", ""), ("What should we fix or build", "in", ""),
        ("What's on your mind", "for", ""), ("What shall we tackle", "in", ""),
    ]

    public static var questionCount: Int { questions.count }

    /// The question at `index`, wrapping past the end.
    public static func question(_ index: Int, project: String?) -> String {
        let question = questions[index % questions.count]
        let named = project.map { " \(question.link) \($0)" } ?? ""
        return "\(question.lead)\(named)\(question.tail)?"
    }

    /// "now", "4m", "2h", "1d": the largest whole unit only.
    public static func age(from date: Date, to now: Date) -> String {
        let minutes = Int(max(0, now.timeIntervalSince(date)) / 60)
        if minutes < 1 {
            return "now"
        }
        if minutes < 60 {
            return "\(minutes)m"
        }
        if minutes < 24 * 60 {
            return "\(minutes / 60)h"
        }
        return "\(minutes / (24 * 60))d"
    }
}

/// Which question the start screen asks: the next one each time it appears again, so the
/// same one never shows twice in a row (B90).
public struct StartQuestionRotation: Sendable, Equatable {
    /// The question on screen; nil before the start screen first appears.
    public private(set) var current: Int?

    public init() {}

    public mutating func next() -> Int {
        let index = current.map { ($0 + 1) % StartScreen.questionCount } ?? 0
        current = index
        return index
    }
}
