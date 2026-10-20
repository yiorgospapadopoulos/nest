import Foundation

/// A project's branches and worktrees, from `GET /api/repos/{name}/branch-map` (B96): the
/// default branch, the branch the project folder is on, every branch checked out in a
/// worktree and the branches between them, each with the branch it comes from. The daemon
/// lists them depth first from the root, siblings by name.
public struct BranchMap: Decodable, Sendable, Hashable {
    public var defaultBranch: String
    /// Nil while the project folder is on a detached HEAD.
    public var currentBranch: String?
    public var branches: [Branch]

    public init(defaultBranch: String, currentBranch: String?, branches: [Branch]) {
        self.defaultBranch = defaultBranch
        self.currentBranch = currentBranch
        self.branches = branches
    }

    enum CodingKeys: String, CodingKey {
        case branches
        case defaultBranch = "default_branch"
        case currentBranch = "current_branch"
    }

    public struct Branch: Decodable, Sendable, Hashable, Identifiable {
        public var name: String
        /// The branch it comes from; nil for the root.
        public var parent: String?
        public var worktree: Worktree?
        /// The project folder is on it.
        public var here: Bool

        public init(name: String, parent: String?, worktree: Worktree?, here: Bool) {
            self.name = name
            self.parent = parent
            self.worktree = worktree
            self.here = here
        }

        public var id: String { name }
    }

    /// A linked worktree with the branch checked out.
    public struct Worktree: Decodable, Sendable, Hashable {
        public var path: String
        public var owner: Owner

        public init(path: String, owner: Owner) {
            self.path = path
            self.owner = owner
        }
    }

    /// Who made the worktree: Nest, Claude Code, or someone else.
    public enum Owner: String, UnknownSafeEnum {
        case nest, claude, other
        case unknown
    }

    public func branch(_ name: String) -> Branch? {
        branches.first { $0.name == name }
    }

    /// The branches that come from `name`, in the map's order.
    public func children(of name: String) -> [Branch] {
        branches.filter { $0.parent == name }
    }

    /// The branch a chat's place names: a worktree by its folder, else by its name; the
    /// project folder by the branch checked out there.
    public func branch(for place: ChatPlace) -> Branch? {
        switch place {
        case .worktree(let name, let folder):
            branches.first { folder != nil && $0.worktree?.path == folder } ?? branch(name)
        case .projectFolder(let branch, _):
            branch.flatMap(self.branch)
        }
    }
}
