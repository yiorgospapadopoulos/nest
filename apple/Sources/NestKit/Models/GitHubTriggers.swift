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

/// Whose events count: people with write access to the repository (the default), anyone
/// but bots, or every one.
public enum TriggerAuthors: String, Codable, Sendable, CaseIterable, UnknownSafeEnum {
    case members, humans, everyone
    case unknown

    public static let choices: [TriggerAuthors] = [.members, .humans, .everyone]
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
        branches: [String] = [], authors: TriggerAuthors = .members
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
    /// The mode its chats start in: Ask until the user picks another.
    public var permissionMode: PermissionMode

    public init(
        name: String, prompt: String, enabled: Bool = true, events: [GitHubEventKind],
        labels: [String] = [], branches: [String] = [], authors: TriggerAuthors = .members,
        permissionMode: PermissionMode = .default
    ) {
        self.name = name
        self.prompt = prompt
        self.enabled = enabled
        self.events = events
        self.labels = labels
        self.branches = branches
        self.authors = authors
        self.permissionMode = permissionMode
    }

    enum CodingKeys: String, CodingKey {
        case name, prompt, enabled, events, labels, branches, authors
        case permissionMode = "permission_mode"
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
    public var permissionMode: PermissionMode

    public init(id: String, _ body: ChatTriggerBody) {
        self.id = id
        name = body.name
        prompt = body.prompt
        enabled = body.enabled
        events = body.events
        labels = body.labels
        branches = body.branches
        authors = body.authors
        permissionMode = body.permissionMode
    }

    enum CodingKeys: String, CodingKey {
        case id, name, prompt, enabled, events, labels, branches, authors
        case permissionMode = "permission_mode"
    }

    /// A daemon from before the per-trigger mode sends none: its chats asked.
    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        name = try container.decode(String.self, forKey: .name)
        prompt = try container.decode(String.self, forKey: .prompt)
        enabled = try container.decode(Bool.self, forKey: .enabled)
        events = try container.decode([GitHubEventKind].self, forKey: .events)
        labels = try container.decode([String].self, forKey: .labels)
        branches = try container.decode([String].self, forKey: .branches)
        authors = try container.decode(TriggerAuthors.self, forKey: .authors)
        permissionMode =
            try container.decodeIfPresent(PermissionMode.self, forKey: .permissionMode)
            ?? .default
    }

    public var body: ChatTriggerBody {
        ChatTriggerBody(
            name: name, prompt: prompt, enabled: enabled, events: events, labels: labels,
            branches: branches, authors: authors, permissionMode: permissionMode)
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
