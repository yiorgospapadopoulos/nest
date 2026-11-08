import Foundation

// GitHub events that start habits and project chats (B148).

public enum GitHubEventKind: String, Codable, Sendable, CaseIterable, UnknownSafeEnum {
    case issueOpened = "issue_opened"
    case prOpened = "pr_opened"
    case comment, review
    case ciFailed = "ci_failed"
    case ciPassed = "ci_passed"
    case unknown

    /// The ones the editors offer, in their order.
    public static let choices: [GitHubEventKind] = [
        .issueOpened, .prOpened, .comment, .review, .ciFailed, .ciPassed,
    ]
}

/// Whose events count: anyone but bots, also not the user's own, or every one.
public enum TriggerAuthors: String, Codable, Sendable, CaseIterable, UnknownSafeEnum {
    case humans, others, everyone
    case unknown

    public static let choices: [TriggerAuthors] = [.humans, .others, .everyone]
}

/// A habit's GitHub trigger; no projects is every project on GitHub. Labels apply to issues
/// and pull requests, branches to CI runs and the branch a pull request goes into.
public struct GitHubWatch: Codable, Sendable, Hashable {
    public var events: [GitHubEventKind]
    public var projects: [String]
    public var labels: [String]
    public var branches: [String]
    public var authors: TriggerAuthors

    public init(
        events: [GitHubEventKind], projects: [String] = [], labels: [String] = [],
        branches: [String] = [], authors: TriggerAuthors = .humans
    ) {
        self.events = events
        self.projects = projects
        self.labels = labels
        self.branches = branches
        self.authors = authors
    }
}

/// What a project's trigger is told and waits for, as the editor sends it.
public struct ChatTriggerBody: Codable, Sendable, Hashable {
    public var name: String
    public var prompt: String
    public var enabled: Bool
    public var events: [GitHubEventKind]
    public var labels: [String]
    public var branches: [String]
    public var authors: TriggerAuthors

    public init(
        name: String, prompt: String, enabled: Bool = true, events: [GitHubEventKind],
        labels: [String] = [], branches: [String] = [], authors: TriggerAuthors = .humans
    ) {
        self.name = name
        self.prompt = prompt
        self.enabled = enabled
        self.events = events
        self.labels = labels
        self.branches = branches
        self.authors = authors
    }
}

/// A project's trigger: each matching event starts a chat in its own worktree.
public struct ChatTrigger: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var name: String
    public var prompt: String
    public var enabled: Bool
    public var events: [GitHubEventKind]
    public var labels: [String]
    public var branches: [String]
    public var authors: TriggerAuthors

    public init(id: String, _ body: ChatTriggerBody) {
        self.id = id
        name = body.name
        prompt = body.prompt
        enabled = body.enabled
        events = body.events
        labels = body.labels
        branches = body.branches
        authors = body.authors
    }

    public var body: ChatTriggerBody {
        ChatTriggerBody(
            name: name, prompt: prompt, enabled: enabled, events: events, labels: labels,
            branches: branches, authors: authors)
    }
}

/// Only `enabled` changes; the rest stays.
public struct TriggerSwitch: Encodable, Sendable, Hashable {
    public var enabled: Bool

    public init(enabled: Bool) {
        self.enabled = enabled
    }
}

public enum TriggerOutcome: String, Codable, Sendable, CaseIterable, UnknownSafeEnum {
    case started, queued, skipped, failed
    case unknown
}

/// What a project's trigger did last.
public struct TriggerActivity: Codable, Sendable, Hashable {
    public var triggerID: String
    public var outcome: TriggerOutcome
    public var reason: String?
    public var at: Date
    public var title: String
    public var url: String
    public var sessionID: String?

    public init(
        triggerID: String, outcome: TriggerOutcome, reason: String?, at: Date, title: String,
        url: String, sessionID: String?
    ) {
        self.triggerID = triggerID
        self.outcome = outcome
        self.reason = reason
        self.at = at
        self.title = title
        self.url = url
        self.sessionID = sessionID
    }

    enum CodingKeys: String, CodingKey {
        case outcome, reason, at, title, url
        case triggerID = "trigger_id"
        case sessionID = "session_id"
    }
}
