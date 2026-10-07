import Foundation

/// A registered project folder: a git repository, or a plain folder that agents work in
/// in place, with no branch, review or pull requests.
public struct Repo: Codable, Sendable, Hashable, Identifiable {
    public var name: String
    public var path: String
    /// Nil for a plain folder.
    public var defaultBranch: String?
    public var worktree: WorktreeConfig
    public var git: Bool

    public var id: String { name }

    enum CodingKeys: String, CodingKey {
        case name, path, worktree, git
        case defaultBranch = "default_branch"
    }

    /// `git` is optional, since older daemons only know git repositories.
    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        name = try container.decode(String.self, forKey: .name)
        path = try container.decode(String.self, forKey: .path)
        defaultBranch = try container.decodeIfPresent(String.self, forKey: .defaultBranch)
        worktree = try container.decode(WorktreeConfig.self, forKey: .worktree)
        git = try container.decodeIfPresent(Bool.self, forKey: .git) ?? true
    }

    /// What sits next to the project's name in the toolbar.
    public var badge: ProjectBadge? {
        guard git else { return .initGit }
        return defaultBranch.map(ProjectBadge.branch)
    }

    /// Where a new chat works: as chosen, except that a plain folder has no worktrees.
    public func mode(for preferred: SessionMode?) -> SessionMode? {
        git ? preferred : .inPlace
    }
}

/// The toolbar's chip beside the project name.
public enum ProjectBadge: Sendable, Hashable {
    /// A git repository's default branch.
    case branch(String)
    /// A plain folder: offers a chat that sets it up with git.
    case initGit
}

/// The chat the Init button starts in a plain folder.
public enum GitInit {
    /// Prefilled in the new chat's composer; the user sends it.
    public static let prompt =
        "Initialize this folder as a git repository: run git init with main as the default branch and add a .gitignore that fits what is in this folder. Do not commit; harness handles commits."
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

/// Local apps a project can be opened in.
public enum RepoApp: String, Codable, Sendable, CaseIterable {
    case vscode
    case finder
    case terminal
}
