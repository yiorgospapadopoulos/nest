import Foundation

/// A page of the Settings window (B81).
public enum SettingsPage: Sendable, Hashable {
    case general, appearance, notifications, agents, usage, storage, pixies, accounts
    case extensions, devices
    case shortcuts
    /// A project's page, by repo name.
    case project(String)
    case addProject

    /// The pages before the projects, in order.
    public static let fixed: [SettingsPage] = [
        .general, .appearance, .notifications, .agents, .usage, .storage, .pixies,
        .accounts, .extensions, .devices, .shortcuts,
    ]

    public var title: String {
        switch self {
        case .general: "General"
        case .appearance: "Appearance"
        case .notifications: "Notifications"
        case .agents: "Agents"
        case .usage: "Usage"
        case .storage: "Storage"
        case .pixies: "Pixies"
        case .accounts: "Accounts"
        case .extensions: "Extensions"
        case .devices: "Devices"
        case .shortcuts: "Keyboard shortcuts"
        case .project(let name): name
        case .addProject: "Add project"
        }
    }

    /// The Pixies page's icon (B86): a winged pixie on the sprites' 12 by 10 grid.
    public static let pixieGlyph = [
        "............", "....####....", "#..######..#", "##.#.##.#.##", "############",
        "##.######.##", "#..######..#", "....#..#....", "............", "............",
    ]

    /// What the page's rows are called, for the search field.
    public var labels: [String] {
        switch self {
        case .general:
            ["Sidebar", "Show automated chats", "Nest", "Version", "Restart Nest"]
        case .storage:
            [
                "Space used", "Used by Nest", "Attachments", "Artifacts",
                "Archive chats idle for", "Clean up", "Review large attachments", "Search index",
                "Rebuild",
            ]
        case .appearance:
            [
                "Mode", "Auto", "Light", "Dark", "Accent colour", "Chat background", "Image",
                "Visibility when empty", "Visibility with chats", "Grain",
            ]
        case .notifications:
            ["Notify me about", "Delivery", "Sound"]
                + NotificationPreferences.kindToggles.map(\.title)
                + ["iPhone push"]
        case .agents:
            ["New chats", "Model", "Thinking", "Permissions", "Work in", "Stuck chats"]
                + StuckThreshold.allCases.map(\.title)
        case .usage:
            ["Limits", "5 hour", "Weekly", "Refresh"] + UsageUnit.allCases.map(\.title)
                + [
                    "Subagents", "Details", "Usage limits", "Check limits", "Warn me at",
                    "Also as a notification",
                ]
        case .pixies:
            [
                "Your pixies", "Show hidden pixies", "New pixie", "New pixies start with",
                "Model", "Autonomy", "Project files", "Projects", "Chats running at once",
                "Chats started per day", "Habits", "Pause all habits", "Skip habit runs above",
                "Reports", "Send to the phone from",
            ]
        case .accounts: ["Claude", "Sign in", "Sign out", "GitHub", "Check again"]
        case .extensions:
            [
                "Claude Code", "Install Claude Code", "Skills and plugins", "Plugins", "Skills",
                "Browse", "Marketplaces", "Connections", "Connectors", "MCP",
            ]
        case .devices: ["Pair a device", "Revoke", "iPhone"]
        case .shortcuts:
            ["Restore defaults"] + ShortcutGroup.allCases.map(\.rawValue)
                + ShortcutAction.allCases.map(\.title)
        case .project:
            [
                "General", "Name", "Folder", "Kind", "Default branch", "Push to", "Remove",
                "Chats", "Work in", "Worktrees", "Linked files", "Setup commands",
                "Setup time limit", "Artifacts", "Look", "Tab icon", "Colour", "Chat background",
            ]
        case .addProject: ["Folder", "Add"]
        }
    }

    /// Whether the page's title or one of its rows contains the query, ignoring case and
    /// surrounding spaces; an empty query matches every page.
    public func matches(_ query: String) -> Bool {
        let query = query.trimmingCharacters(in: .whitespaces)
        guard !query.isEmpty else { return true }
        return ([title] + labels).contains { $0.localizedCaseInsensitiveContains(query) }
    }

    /// The sidebar's pages: the fixed ones, each project, then Add project, as the query
    /// leaves them.
    public static func listed(projects: [String], query: String) -> (
        pages: [SettingsPage], projects: [SettingsPage]
    ) {
        let projectPages = projects.map(SettingsPage.project) + [.addProject]
        return (fixed.filter { $0.matches(query) }, projectPages.filter { $0.matches(query) })
    }
}

/// The tabs of a project's settings page.
public enum ProjectSettingsTab: String, Sendable, CaseIterable {
    case general = "General"
    case chats = "Chats"
    case worktrees = "Worktrees"
    case look = "Look"
    case artifacts = "Artifacts"

    /// A plain folder has no worktrees.
    public static func tabs(git: Bool) -> [ProjectSettingsTab] {
        git ? allCases : allCases.filter { $0 != .worktrees }
    }
}

/// The setup time limit's choices, in seconds, with a value set elsewhere kept.
public enum SetupTimeout {
    public static let choices = [300, 900, 1800]

    public static func choices(including value: Int) -> [Int] {
        choices.contains(value) ? choices : (choices + [value]).sorted()
    }

    /// "15 minutes", "90 seconds", "1 minute".
    public static func label(_ seconds: Int) -> String {
        guard seconds % 60 == 0 else { return "\(seconds) seconds" }
        let minutes = seconds / 60
        return minutes == 1 ? "1 minute" : "\(minutes) minutes"
    }
}
