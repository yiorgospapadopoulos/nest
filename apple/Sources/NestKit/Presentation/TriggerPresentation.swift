import Foundation

// How the app shows GitHub event triggers (B148), as the web's triggers/github.ts. A
// habit's editor edits its first GitHub trigger and keeps any others a pixie made.

extension GitHubEventKind {
    /// The editors' checkbox.
    public var label: String {
        switch self {
        case .issueOpened: "An issue is opened"
        case .prOpened: "A pull request is opened"
        case .comment: "Someone comments"
        case .review: "A review is posted"
        case .ciFailed: "CI fails"
        case .ciPassed: "CI passes"
        case .unknown: ""
        }
    }

    /// What follows "On GitHub when".
    var phrase: String? {
        switch self {
        case .issueOpened: "an issue is opened"
        case .prOpened: "a pull request is opened"
        case .comment: "someone comments"
        case .review: "a review is posted"
        case .ciFailed: "CI fails"
        case .ciPassed: "CI passes"
        case .unknown: nil
        }
    }
}

extension TriggerAuthors {
    public var label: String {
        switch self {
        case .members: "People with write access"
        case .humans: "Anyone but bots"
        case .everyone: "Everyone"
        case .unknown: ""
        }
    }
}

public enum TriggerText {
    public static let githubNote =
        "Checked on GitHub every minute. Each event starts at most one run."
    public static let triggerNote =
        "Each event starts a chat in its own worktree. It works once, then waits for you, and cannot push."
    public static let empty =
        "No triggers yet. A trigger starts a chat here when something happens on GitHub."
    /// Shown when people without write access count, as their text then drives the agent
    /// (D179).
    public static let outsidersWarning =
        "People without write access can start these too, and their text goes straight to the agent."
    public static let noRemote = "Add the project's GitHub address in General to use triggers."

    /// "On GitHub when an issue is opened or CI fails"; nil without known events.
    public static func github(_ events: [GitHubEventKind]) -> String? {
        let phrases = GitHubEventKind.choices.filter(events.contains).compactMap(\.phrase)
        guard let last = phrases.last else { return nil }
        let rest = phrases.dropLast()
        return "On GitHub when "
            + (rest.isEmpty ? last : rest.joined(separator: ", ") + " or " + last)
    }

    /// The modes a trigger's chats may start in; Auto is left out, as only some models take
    /// it. A new trigger starts in Ask.
    public static let modes = PermissionMode.selectable

    /// "When CI fails · on main · labelled bug · anyone but bots · Bypass", for a trigger's
    /// row.
    public static func summary(_ trigger: ChatTrigger) -> String {
        let when = github(trigger.events).map { "When" + $0.dropFirst("On GitHub when".count) }
        return [
            when,
            trigger.branches.isEmpty ? nil : "on " + trigger.branches.joined(separator: ", "),
            trigger.labels.isEmpty ? nil : "labelled " + trigger.labels.joined(separator: ", "),
            trigger.authors == .members ? nil : trigger.authors.label.lowercased(),
            trigger.permissionMode == .default ? nil : trigger.permissionMode.label,
        ]
        .compactMap { $0 }
        .joined(separator: " · ")
    }

    /// "Started a chat 14:02", "Skipped 09:12 (usage)"; nil when it never did anything.
    public static func activity(
        _ activity: TriggerActivity?, now: Date, calendar: Calendar = .current
    ) -> String? {
        guard let activity else { return nil }
        let words =
            switch activity.outcome {
            case .started: "Started a chat"
            case .queued: "Starting a chat"
            case .skipped: "Skipped"
            case .failed, .unknown: "Could not start a chat"
            }
        let time = PixieActivityText.time(activity.at, now: now, calendar: calendar)
        let why = activity.reason.map { " (\($0))" } ?? ""
        return "\(words) \(time)\(why)"
    }

    /// Comma separated words, each once, as typed into a Labels or Branches field.
    public static func list(_ text: String) -> [String] {
        var seen = Set<String>()
        return text.split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty && seen.insert($0).inserted }
    }

    /// "All projects", "web", or "web and 2 more".
    public static func projects(_ projects: [String]) -> String {
        guard let first = projects.first else { return "All projects" }
        return projects.count == 1 ? first : "\(first) and \(projects.count - 1) more"
    }
}

/// The GitHub part of a habit's editor.
public struct GitHubDraft: Sendable, Hashable {
    public var events: Set<GitHubEventKind> = []
    /// Empty is every project on GitHub.
    public var projects: [String] = []
    public var labels = ""
    public var branches = ""
    public var authors = TriggerAuthors.members

    public init() {}

    public init(watches: [GitHubWatch]?) {
        guard let first = watches?.first else { return }
        events = Set(first.events)
        projects = first.projects
        labels = first.labels.joined(separator: ", ")
        branches = first.branches.joined(separator: ", ")
        authors = first.authors
    }

    /// The habit's GitHub triggers after the edit: the first as drafted (gone without
    /// events), then the rest as they were.
    public func watches(keeping before: [GitHubWatch]?) -> [GitHubWatch] {
        let rest = Array((before ?? []).dropFirst())
        let ordered = GitHubEventKind.choices.filter(events.contains)
        guard !ordered.isEmpty else { return rest }
        let first = GitHubWatch(
            events: ordered, projects: projects, labels: TriggerText.list(labels),
            branches: TriggerText.list(branches), authors: authors)
        return [first] + rest
    }
}

/// A project's trigger editor.
public struct TriggerDraft: Sendable, Hashable {
    public static let nameLimit = 120
    public static let promptLimit = 4000

    public var name = ""
    public var prompt = ""
    public var events: Set<GitHubEventKind> = []
    public var labels = ""
    public var branches = ""
    public var authors = TriggerAuthors.members
    public var enabled = true
    public var permissionMode = PermissionMode.default

    public init() {}

    public init(trigger: ChatTrigger) {
        name = trigger.name
        prompt = trigger.prompt
        events = Set(trigger.events)
        labels = trigger.labels.joined(separator: ", ")
        branches = trigger.branches.joined(separator: ", ")
        authors = trigger.authors
        enabled = trigger.enabled
        permissionMode = trigger.permissionMode
    }

    /// Why it cannot be saved yet; an empty name only keeps Save off.
    public var problem: String? {
        if trimmedName.count > Self.nameLimit {
            return "A name has at most \(Self.nameLimit) characters"
        }
        if events.isEmpty { return "Choose at least one event" }
        if trimmedPrompt.isEmpty { return "Say what the chat should do" }
        if trimmedPrompt.count > Self.promptLimit {
            return "The instructions have at most \(Self.promptLimit) characters"
        }
        return nil
    }

    public var canSave: Bool { !trimmedName.isEmpty && problem == nil }

    public var body: ChatTriggerBody {
        ChatTriggerBody(
            name: trimmedName, prompt: trimmedPrompt, enabled: enabled,
            events: GitHubEventKind.choices.filter(events.contains),
            labels: TriggerText.list(labels), branches: TriggerText.list(branches),
            authors: authors, permissionMode: permissionMode)
    }

    private var trimmedName: String { name.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var trimmedPrompt: String { prompt.trimmingCharacters(in: .whitespacesAndNewlines) }
}
