import Foundation

/// A registered repository; the Mac app shows each one as a project.
public struct Repo: Codable, Sendable, Hashable, Identifiable {
    public var name: String
    public var path: String
    public var defaultBranch: String
    public var worktree: WorktreeConfig

    public var id: String { name }

    enum CodingKeys: String, CodingKey {
        case name, path, worktree
        case defaultBranch = "default_branch"
    }
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
