import Foundation

/// Where a chat works, as its sidebar row and pane header say it (B55): a worktree, named by
/// its branch (the two are one pair), or the project folder, named by the branch checked out
/// there now, which every in-place chat shares.
public enum ChatPlace: Sendable, Hashable {
    /// `folder` is nil while the worktree is still being made.
    case worktree(name: String, folder: String?)
    /// `branch` is nil when HEAD is detached or the branch is not known.
    case projectFolder(branch: String?, folder: String)

    /// A Nest chat's place; nil in a plain folder, which has no branch to name, or when an
    /// in-place chat's folder is unknown.
    public static func of(_ session: Session, repo: Repo?) -> ChatPlace? {
        guard repo?.git != false else { return nil }
        if session.mode == .worktree || session.worktreePath != nil {
            let folderName = session.worktreePath.map { URL(fileURLWithPath: $0).lastPathComponent }
            return .worktree(
                name: session.branch ?? folderName ?? "New worktree", folder: session.worktreePath)
        }
        return (session.cwd ?? repo?.path).map {
            .projectFolder(branch: repo?.currentBranch, folder: $0)
        }
    }

    /// A Claude Code chat's place: the worktree Claude Code made, else the folder.
    public static func of(_ chat: ClaudeChat, repo: Repo?) -> ChatPlace? {
        guard repo?.git != false else { return nil }
        if let worktree = chat.worktree {
            return .worktree(name: worktree, folder: chat.cwd)
        }
        return .projectFolder(branch: repo?.currentBranch, folder: chat.cwd)
    }

    public var isWorktree: Bool {
        if case .worktree = self { true } else { false }
    }

    /// The words beside the branch icon, in the sidebar row and the header.
    public var name: String {
        switch self {
        case .worktree(let name, _): name
        case .projectFolder(let branch, _): branch ?? "This folder"
        }
    }

    /// What a row's or header's accessibility label adds, after a comma.
    public var accessibilityLabel: String {
        switch self {
        case .worktree(let name, _): "worktree \(name)"
        case .projectFolder(let branch, _): branch.map { "on \($0)" } ?? "in this folder"
        }
    }

    /// The tooltip, naming the folder.
    public var help: String {
        switch self {
        case .worktree(let name, let folder):
            folder.map { "Worktree \(name) in \($0)" } ?? "Worktree \(name)"
        case .projectFolder(let branch, let folder):
            branch.map { "On \($0) in \(folder)" } ?? "In \(folder)"
        }
    }
}

/// Where a new chat works, as the user chose it: in the project folder (B55), in a new
/// worktree from a branch (nil: the folder's branch), in an existing worktree, or on
/// another local branch itself, in a worktree of its own (B96).
public enum NewChatChoice: Sendable, Hashable {
    case inPlace
    case newWorktree(from: String?)
    case worktree(path: String, branch: String)
    case onBranch(String)

    /// A mode's choice, as the defaults and the plain menu set it: no mode works in place
    /// (D038); a worktree is a new one from the folder's branch.
    public init(mode: SessionMode?) {
        self = mode == .worktree ? .newWorktree(from: nil) : .inPlace
    }

    /// Nil on a branch: the daemon works in place when it is the folder's branch by then.
    public var mode: SessionMode? {
        switch self {
        case .inPlace: .inPlace
        case .newWorktree, .worktree: .worktree
        case .onBranch: nil
        }
    }

    /// The branch a new worktree starts from named: the folder's when none was chosen, as
    /// the picker marks it.
    public func resolved(_ repo: Repo?) -> NewChatChoice {
        if case .newWorktree(nil) = self, let branch = repo?.checkoutBranch {
            return .newWorktree(from: branch)
        }
        return self
    }
}

/// Where a new chat will work, as its composer sends it (B55, B96): on the project
/// folder's current branch; a new worktree from a branch, with an optional name for its
/// own branch; an existing worktree; or another branch itself.
public struct NewChatPlace: Sendable, Hashable {
    /// Nil leaves it to the daemon (on a branch).
    public let mode: SessionMode?
    /// New worktrees only: the branch it starts from.
    public let base: String?
    /// New worktrees only: the typed name, trimmed; nil when blank.
    public let branch: String?
    /// Existing worktrees only: its folder.
    public let worktreePath: String?
    /// On a branch only: that branch.
    public let onBranch: String?

    /// A plain folder always works in place.
    public init(_ choice: NewChatChoice, typed: String, repo: Repo?) {
        let choice = repo?.git == false ? .inPlace : choice
        mode = choice.mode
        let name = typed.trimmingCharacters(in: .whitespacesAndNewlines)
        switch choice {
        case .newWorktree(let from):
            (base, branch) = (from ?? repo?.checkoutBranch, name.isEmpty ? nil : name)
        case .inPlace, .worktree, .onBranch: (base, branch) = (nil, nil)
        }
        if case .worktree(let path, _) = choice { worktreePath = path } else { worktreePath = nil }
        if case .onBranch(let name) = choice { onBranch = name } else { onBranch = nil }
    }

    /// The composer button: "Work on wip" (the folder's branch or another), "New worktree
    /// from main", or the worktree's branch.
    public static func title(_ choice: NewChatChoice, repo: Repo?) -> String {
        switch choice {
        case .inPlace: inPlaceTitle(repo)
        case .newWorktree(let from):
            (from ?? repo?.checkoutBranch).map { "New worktree from \($0)" } ?? worktreeTitle
        case .worktree(_, let branch): branch
        case .onBranch(let branch): "Work on \(branch)"
        }
    }

    /// The selector's first choice: "Work on main", or "Work in this folder" when the
    /// folder's branch is not known.
    public static func inPlaceTitle(_ repo: Repo?) -> String {
        repo?.currentBranch.map { "Work on \($0)" } ?? "Work in this folder"
    }

    public static func inPlaceDetail(_ repo: Repo?) -> String {
        repo?.currentBranch.map { "Edits the project folder, on \($0)" }
            ?? "Edits the project folder"
    }

    public static let worktreeTitle = "New worktree"
    public static let worktreeDetail = "A separate copy of the project on its own new branch"
}
