import Foundation

/// A project's branches and worktrees, from `GET /api/repos/{name}/branch-map` (B96, B131):
/// every local branch, each with the branch it comes from, and what only a remote has. The
/// daemon lists them depth first from the top row, the one branch with no parent.
public struct BranchMap: Decodable, Sendable, Hashable {
    public var defaultBranch: String?
    /// Nil while the project folder is on a detached HEAD or a branch with no commits.
    public var currentBranch: String?
    /// The project folder is on a detached HEAD, as git says. False from an older daemon.
    public var detached: Bool
    public var branches: [Branch]
    /// Branches only a remote has, the top row's left out. Empty from an older daemon.
    public var remoteBranches: [RemoteBranch]

    public init(
        defaultBranch: String?, currentBranch: String?, detached: Bool = false,
        branches: [Branch], remoteBranches: [RemoteBranch] = []
    ) {
        self.defaultBranch = defaultBranch
        self.currentBranch = currentBranch
        self.detached = detached
        self.branches = branches
        self.remoteBranches = remoteBranches
    }

    enum CodingKeys: String, CodingKey {
        case branches, detached
        case defaultBranch = "default_branch"
        case currentBranch = "current_branch"
        case remoteBranches = "remote_branches"
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        defaultBranch = try container.decodeIfPresent(String.self, forKey: .defaultBranch)
        currentBranch = try container.decodeIfPresent(String.self, forKey: .currentBranch)
        detached = try container.decodeIfPresent(Bool.self, forKey: .detached) ?? false
        branches = try container.decode([Branch].self, forKey: .branches)
        remoteBranches =
            try container.decodeIfPresent([RemoteBranch].self, forKey: .remoteBranches) ?? []
    }

    public struct Branch: Decodable, Sendable, Hashable, Identifiable {
        public var name: String
        /// The branch it comes from; nil for the top row.
        public var parent: String?
        public var worktree: Worktree?
        /// The project folder is on it.
        public var here: Bool
        /// Commits its remote branch has that it does not, as of the last fetch.
        public var behind: Int
        /// The remote that alone has it: a remote-only top row.
        public var remote: String?

        public init(
            name: String, parent: String?, worktree: Worktree?, here: Bool, behind: Int = 0,
            remote: String? = nil
        ) {
            self.name = name
            self.parent = parent
            self.worktree = worktree
            self.here = here
            self.behind = behind
            self.remote = remote
        }

        enum CodingKeys: String, CodingKey {
            case name, parent, worktree, here, behind, remote
        }

        public init(from decoder: any Decoder) throws {
            let container = try decoder.container(keyedBy: CodingKeys.self)
            name = try container.decode(String.self, forKey: .name)
            parent = try container.decodeIfPresent(String.self, forKey: .parent)
            worktree = try container.decodeIfPresent(Worktree.self, forKey: .worktree)
            here = try container.decode(Bool.self, forKey: .here)
            behind = try container.decodeIfPresent(Int.self, forKey: .behind) ?? 0
            remote = try container.decodeIfPresent(String.self, forKey: .remote)
        }

        public var id: String { name }

        /// The note at its row's right, "3 behind"; nil with nothing to note. A note only:
        /// nothing pulls.
        public var behindNote: String? {
            remote == nil && behind > 0 ? "\(behind) behind" : nil
        }

        /// What selecting its row asks the daemon for.
        public var selection: SelectPlaceRequest {
            worktree.map { SelectPlaceRequest(worktreePath: $0.path) }
                ?? SelectPlaceRequest(branch: name)
        }
    }

    /// A branch only a remote has; picking it makes the local branch.
    public struct RemoteBranch: Decodable, Sendable, Hashable, Identifiable {
        public var remote: String
        public var name: String

        public init(remote: String, name: String) {
            self.remote = remote
            self.name = name
        }

        public var id: String { "\(remote)/\(name)" }
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

    /// The row with no parent, pinned over the rest.
    public var top: Branch? { branches.first { $0.parent == nil } }

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

    /// The branches and remote branches whose name holds `query`, with no regard for case.
    public func find(_ query: String) -> FoundPlaces {
        let wanted = query.lowercased()
        func holds(_ name: String) -> Bool { name.lowercased().contains(wanted) }
        return FoundPlaces(
            branches: Array(branches.lazy.filter { holds($0.name) }.prefix(40)),
            remotes: Array(remoteBranches.lazy.filter { holds($0.name) }.prefix(20)))
    }
}

/// What Find found: branches first, then what only a remote has.
public struct FoundPlaces: Sendable, Hashable {
    public let branches: [BranchMap.Branch]
    public let remotes: [BranchMap.RemoteBranch]

    public var isEmpty: Bool { branches.isEmpty && remotes.isEmpty }
    public var count: Int { branches.count + remotes.count }
}
