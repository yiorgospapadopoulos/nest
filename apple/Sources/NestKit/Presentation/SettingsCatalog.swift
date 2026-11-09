import Foundation

/// A page of Settings (B81).
public enum SettingsPage: Sendable, Hashable {
    case general, appearance, notifications, agents, usage, storage, pixies, accounts
    /// Letting chats use apps on this Mac, simulators and the shared browser (B150).
    case computer
    /// Claude Code, Codex, other AI apps and the `nest` command working with chats (B151).
    case terminal
    /// How fast and how costly Nest is, run on request (B115).
    case performance
    case devices
    case shortcuts
    /// What the agents read, shared and per engine (B97); replaces Extensions.
    case configuration
    /// What makes Nest different, by area, with what is new (B103).
    case features
    /// A project's page, by repo name.
    case project(String)
    case addProject

    /// The pages before the projects, in order.
    public static let fixed: [SettingsPage] = [
        .general, .appearance, .notifications, .agents, .computer, .terminal, .usage, .performance,
        .storage, .pixies, .accounts, .devices, .shortcuts, .configuration, .features,
    ]

    public var title: String {
        switch self {
        case .general: "General"
        case .appearance: "Appearance"
        case .notifications: "Notifications"
        case .agents: "Agents"
        case .computer: "Computer use"
        case .terminal: "Terminal agents"
        case .usage: "Usage"
        case .performance: "Performance"
        case .storage: "Storage"
        case .pixies: "Pixies"
        case .accounts: "Accounts"
        case .devices: "Devices"
        case .shortcuts: "Keyboard shortcuts"
        case .configuration: "Configuration"
        case .features: "Features"
        case .project(let name): name
        case .addProject: "Add project"
        }
    }

    /// The Pixies page's icon (B86): a winged pixie on a 12 by 10 grid.
    public static let pixieGlyph = [
        "............", "....####....", "#..######..#", "##.#.##.#.##", "############",
        "##.######.##", "#..######..#", "....#..#....", "............", "............",
    ]

    /// The worktree rows Agents and each project both have (B141).
    static let worktreeLabels = [
        "Worktrees folder", "Branch name prefix", "Check out submodules",
        "Remove merged worktrees",
    ]

    /// What the page's rows are called, for the search field.
    public var labels: [String] {
        switch self {
        case .general:
            [
                "Sidebar", "Show automated chats", "Nest", "Version", "Restart Nest", "Setup",
                "Set up Nest", "Help", "Report a bug", "Uninstall", "Uninstall Nest",
            ]
        case .storage:
            [
                "Space used", "Used by Nest", "Attachments", "Artifacts",
                "Archive chats idle for", "Clean up", "Review large attachments", "Search index",
                "Rebuild",
            ]
        case .appearance:
            [
                "Mode", "Auto", "Light", "Dark", "Accent colour", "Chat background", "Image",
                "Visibility when empty", "Visibility with chats", "Grain", "Island settings",
                "Show the island", "Order", "Newest first", "Oldest first",
                "Use the free menu bar space",
            ]
        case .notifications:
            ["Notify me about", "Delivery", "Sound"]
                + NotificationPreferences.kindToggles.map(\.title)
                + ["iPhone push", "ntfy", "Server", "Topic", "Link address"]
        case .agents:
            ["New chats", "Model", "Thinking", "Permissions", "Work in", "Worktrees"]
                + Self.worktreeLabels + ["Stuck chats"] + StuckThreshold.allCases.map(\.title)
        case .computer:
            [
                "Let chats use apps", "Permissions", "Accessibility", "Screen Recording",
                "Pixies may use it", "Always allowed", "Simulators and browser",
            ] + [ComputerKind.ios, .android, .browser].map(\.title)
        case .terminal:
            ["Claude Code", "Codex", "Other MCP apps", "nest command", "Access"]
                + OutsideAccess.choices.map(\.title)
        case .usage:
            ["Limits", "5 hour", "Weekly", "Refresh"] + UsageUnit.allCases.map(\.title)
                + [
                    "Subagents", "Details", "Usage limits", "Check limits", "Warn me at",
                    "Also as a notification",
                ]
        case .pixies:
            [
                "Your pixies", "Show hidden pixies", "Pixies and subagents can push", "New pixie",
                "New pixies start with", "Model", "Autonomy", "Project files", "Projects",
                "Chats running at once", "Chats started per day", "Habits", "Pause all habits",
                "Skip habit runs above", "Reports", "Send to the phone from",
            ]
        case .accounts: ["Claude", "Sign in", "Sign out", "GitHub", "Check again"]
        case .configuration:
            [
                "Shared", "Instructions", "AGENTS.md", "CLAUDE.md", "Skills", "New skill",
                "MCP servers", "Add server", "Engines", "Claude", "Codex", "Claude Code",
                "Install Claude Code", "Uses shared", "Copy to Shared", "Plugins", "Browse",
                "Marketplaces", "Connectors", "Hooks", "Subagents", "Slash commands",
                "Permission rules", "Settings file", "Rules", "config.toml",
            ]
        case .devices: ["Pair a device", "Revoke", "iPhone"]
        case .performance:
            [
                "Run all", "Clear old runs", "Context cost", "Turn speed and cache", "Load speed",
                "Waiting on you", "Activity", "Advanced", "Mac app", "What changed",
            ]
        // The groups' and features' names come from the daemon, through `listed`.
        case .features: ["New"]
        case .shortcuts:
            ["Restore defaults"] + ShortcutGroup.allCases.map(\.rawValue)
                + ShortcutAction.allCases.map(\.title)
        case .project:
            [
                "General", "Name", "Folder", "Kind", "Default branch", "Push to", "Remove",
                "Chats", "Work in", "Worktrees", "Linked files", "Setup commands",
                "Setup time limit",
            ] + Self.worktreeLabels
                + [
                    "Clean up", "Artifacts", "Look", "Tab icon", "Colour", "Chat background",
                    "Configuration", "Instructions", "Project skills", "MCP servers", ".mcp.json",
                ]
        case .addProject: ["Folder", "Add"]
        }
    }

    /// Whether the page's title, one of its rows or one of the `extra` labels contains the
    /// query, ignoring case and surrounding spaces; an empty query matches every page.
    public func matches(_ query: String, extra: [String] = []) -> Bool {
        let query = query.trimmingCharacters(in: .whitespaces)
        guard !query.isEmpty else { return true }
        return ([title] + labels + extra).contains { $0.localizedCaseInsensitiveContains(query) }
    }

    /// The sidebar's pages: the fixed ones, each project, then Add project, as the query
    /// leaves them. `features` are the Features page's group and feature names.
    public static func listed(projects: [String], query: String, features: [String] = []) -> (
        pages: [SettingsPage], projects: [SettingsPage]
    ) {
        let projectPages = projects.map(SettingsPage.project) + [.addProject]
        let pages = fixed.filter { $0.matches(query, extra: $0 == .features ? features : []) }
        return (pages, projectPages.filter { $0.matches(query) })
    }
}

/// The tabs of a project's settings page.
public enum ProjectSettingsTab: String, Sendable, CaseIterable {
    case general = "General"
    /// The project's own instructions, skills and MCP servers (B97).
    case configuration = "Configuration"
    case chats = "Chats"
    case worktrees = "Worktrees"
    /// GitHub events that start a chat in the project (B148).
    case triggers = "Triggers"
    case look = "Look"
    case artifacts = "Artifacts"

    /// A plain folder has no worktrees or triggers.
    public static func tabs(git: Bool) -> [ProjectSettingsTab] {
        git ? allCases : allCases.filter { $0 != .worktrees && $0 != .triggers }
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
