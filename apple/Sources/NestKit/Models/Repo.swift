import Foundation

/// A registered project folder: a git repository, or a plain folder that agents work in
/// in place, with no branch, review or pull requests.
public struct Repo: Codable, Sendable, Hashable, Identifiable {
    public var name: String
    public var path: String
    /// Nil for a plain folder.
    public var defaultBranch: String?
    /// The branch checked out in the project folder now; nil when HEAD is detached, for a
    /// plain folder, or from an older daemon (B55).
    public var currentBranch: String?
    public var worktree: WorktreeConfig
    public var git: Bool
    /// A pixie sprite shown as the project's icon; nil shows its initials (B36).
    public var icon: Mascot?
    /// A pixie colour (`#RRGGBB`) for the icon; nil is the default colour.
    public var iconColor: String?
    /// The one address Nest pushes to; nil before it is set or for a plain folder.
    public var remoteURL: String?

    public var id: String { name }

    enum CodingKeys: String, CodingKey {
        case name, path, worktree, git, icon
        case defaultBranch = "default_branch"
        case currentBranch = "current_branch"
        case iconColor = "icon_color"
        case remoteURL = "remote_url"
    }

    /// `git` and the icon are optional, since older daemons do not send them. A sprite this
    /// app does not know shows the initials.
    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        name = try container.decode(String.self, forKey: .name)
        path = try container.decode(String.self, forKey: .path)
        defaultBranch = try container.decodeIfPresent(String.self, forKey: .defaultBranch)
        currentBranch = try container.decodeIfPresent(String.self, forKey: .currentBranch)
        worktree = try container.decode(WorktreeConfig.self, forKey: .worktree)
        git = try container.decodeIfPresent(Bool.self, forKey: .git) ?? true
        icon = try container.decodeIfPresent(Mascot.self, forKey: .icon).flatMap {
            $0 == .unknown ? nil : $0
        }
        iconColor = try container.decodeIfPresent(String.self, forKey: .iconColor)
        remoteURL = try container.decodeIfPresent(String.self, forKey: .remoteURL)
    }

    /// The project's icon as Project settings edits it.
    public var projectIcon: ProjectIcon { ProjectIcon(mascot: icon, color: iconColor) }

    /// The branch in-place chats work on: the one checked out now, else the default one.
    public var checkoutBranch: String? { currentBranch ?? defaultBranch }

    /// What sits next to the project's name in the toolbar.
    public var badge: ProjectBadge? {
        guard git else { return .initGit }
        return checkoutBranch.map(ProjectBadge.branch)
    }

    /// Where a new chat works: as chosen, except that a plain folder has no worktrees.
    public func mode(for preferred: SessionMode?) -> SessionMode? {
        git ? preferred : .inPlace
    }
}

/// A project's icon: its initials, or a pixie sprite, in the default colour or a pixie
/// colour (B36).
public struct ProjectIcon: Sendable, Hashable {
    /// Nil shows the project's initials.
    public var mascot: Mascot?
    /// `#RRGGBB`; nil is the default colour.
    public var color: String?

    public init(mascot: Mascot? = nil, color: String? = nil) {
        self.mascot = mascot
        self.color = color
    }
}

/// The toolbar's chip beside the project name.
public enum ProjectBadge: Sendable, Hashable {
    /// The branch checked out in a git repository's folder.
    case branch(String)
    /// A plain folder: offers a chat that sets it up with git.
    case initGit
}

/// The chat the Init button starts in a plain folder.
public enum GitInit {
    /// Prefilled in the new chat's composer; the user sends it.
    public static let prompt =
        "Initialize this folder as a git repository: run git init with main as the default branch and add a .gitignore that fits what is in this folder. Do not commit; Nest handles commits."
}

/// How a repo's task worktrees are prepared: files to link and setup commands to run.
public struct WorktreeConfig: Codable, Sendable, Hashable {
    /// The repo's own choice for new sessions: true worktree, false in place, nil follows the
    /// shared agent default.
    public var isDefault: Bool?
    public var link: [String]
    public var setup: [String]
    public var setupTimeoutSeconds: Int

    public init(
        isDefault: Bool? = nil, link: [String] = [], setup: [String] = [],
        setupTimeoutSeconds: Int = 900
    ) {
        self.isDefault = isDefault
        self.link = link
        self.setup = setup
        self.setupTimeoutSeconds = setupTimeoutSeconds
    }

    enum CodingKeys: String, CodingKey {
        case link, setup
        case isDefault = "default"
        case setupTimeoutSeconds = "setup_timeout_seconds"
    }
}

extension WorktreeConfig {
    /// Adds a link as typed, trimmed; false when it is blank, already there, or not a
    /// relative path inside the repository (the daemon refuses those).
    @discardableResult
    public mutating func addLink(_ text: String) -> Bool {
        let path = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let parts = path.split(separator: "/", omittingEmptySubsequences: true)
        guard !path.hasPrefix("/"), !parts.allSatisfy({ $0 == "." }), !parts.contains(".."),
            !link.contains(path)
        else { return false }
        link.append(path)
        return true
    }

    /// Removes a linked path; one already gone is left alone.
    public mutating func removeLink(_ path: String) {
        link.removeAll { $0 == path }
    }

    /// Removes the setup command shown at this place, if it is still the one there.
    public mutating func removeSetup(_ command: String, at index: Int) {
        if setup[safe: index] == command {
            setup.remove(at: index)
        }
    }

    /// Adds a setup command as typed, trimmed; false when it is blank.
    @discardableResult
    public mutating func addSetup(_ text: String) -> Bool {
        let command = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !command.isEmpty else { return false }
        setup.append(command)
        return true
    }
}

/// `PATCH /api/repos/{name}`: only the project settings that changed, so a change cannot
/// undo another made meanwhile (audit BUG-102).
public struct RepoPatch: Encodable, Sendable, Hashable {
    /// The worktree default changed; `isDefault` is then the new one, nil following the
    /// agent default.
    public var changesDefault = false
    public var isDefault: Bool?
    public var link: [String]?
    public var setup: [String]?
    /// The icon's sprite changed; `icon` is then the new one, nil showing the initials.
    public var changesIcon = false
    public var icon: Mascot?
    /// The icon's colour changed; `iconColor` is then the new one, nil the default colour.
    public var changesIconColor = false
    public var iconColor: String?
    /// A git repo's new default branch, which must exist locally (B81).
    public var defaultBranch: String?
    /// The push address changed; `remoteURL` is then the new one, nil clearing it.
    public var changesRemoteURL = false
    public var remoteURL: String?
    /// Each setup command's time limit, in seconds.
    public var setupTimeoutSeconds: Int?

    /// Changes only these; the rest stay as they are.
    public init(
        defaultBranch: String? = nil, setupTimeoutSeconds: Int? = nil
    ) {
        self.defaultBranch = defaultBranch
        self.setupTimeoutSeconds = setupTimeoutSeconds
    }

    /// Sets the push address, or clears it with nil.
    public init(remoteURL: String?) {
        changesRemoteURL = true
        self.remoteURL = remoteURL
    }

    /// The worktree settings that differ between the two.
    public init(from old: WorktreeConfig, to new: WorktreeConfig) {
        changesDefault = old.isDefault != new.isDefault
        isDefault = new.isDefault
        link = old.link == new.link ? nil : new.link
        setup = old.setup == new.setup ? nil : new.setup
    }

    /// The parts of the icon that differ between the two.
    public init(from old: ProjectIcon, to new: ProjectIcon) {
        changesIcon = old.mascot != new.mascot
        icon = new.mascot
        changesIconColor = old.color != new.color
        iconColor = new.color
    }

    public var isEmpty: Bool {
        !changesDefault && link == nil && setup == nil && !changesIcon && !changesIconColor
            && defaultBranch == nil && !changesRemoteURL && setupTimeoutSeconds == nil
    }

    enum CodingKeys: String, CodingKey {
        case link, setup, icon
        case isDefault = "default"
        case iconColor = "icon_color"
        case defaultBranch = "default_branch"
        case remoteURL = "remote_url"
        case setupTimeoutSeconds = "setup_timeout_seconds"
    }

    /// A changed value that became nil is sent as null, which clears it.
    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        if changesDefault {
            try container.encode(isDefault, forKey: .isDefault)
        }
        try container.encodeIfPresent(link, forKey: .link)
        try container.encodeIfPresent(setup, forKey: .setup)
        if changesIcon {
            try container.encode(icon, forKey: .icon)
        }
        if changesIconColor {
            try container.encode(iconColor, forKey: .iconColor)
        }
        try container.encodeIfPresent(defaultBranch, forKey: .defaultBranch)
        if changesRemoteURL {
            try container.encode(remoteURL, forKey: .remoteURL)
        }
        try container.encodeIfPresent(setupTimeoutSeconds, forKey: .setupTimeoutSeconds)
    }
}

/// What removing a project from Nest does, for its confirmation.
public enum ProjectRemoval {
    public static func consequence(chats: Int) -> String {
        let folder = "Nest forgets this project. Its folder stays as it is."
        switch chats {
        case 0: return folder
        case 1:
            return
                "\(folder) Its chat is deleted for good, with its worktree and history; its branch stays."
        default:
            return
                "\(folder) Its \(chats) chats are deleted for good, with their worktrees and history; their branches stay."
        }
    }
}

/// Local apps a project can be opened in.
public enum RepoApp: String, Codable, Sendable, CaseIterable {
    case vscode
    case finder
    case terminal
}
