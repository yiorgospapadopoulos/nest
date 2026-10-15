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

/// Where a new chat will work, as its composer offers and sends it (B55): on the project
/// folder's current branch, or a new worktree that starts from that branch, with an
/// optional name for its own branch.
public struct NewChatPlace: Sendable, Hashable {
    public let mode: SessionMode
    /// Worktree chats only: the folder's current branch.
    public let base: String?
    /// Worktree chats only: the typed name, trimmed; nil when blank.
    public let branch: String?

    /// Only a chosen worktree makes one: a draft with no mode works in place, the
    /// default (D038), and a plain folder always does.
    public init(mode: SessionMode?, typed: String, repo: Repo?) {
        let resolved = repo.map { $0.mode(for: mode) } ?? mode
        guard resolved == .worktree else {
            self.mode = .inPlace
            base = nil
            branch = nil
            return
        }
        self.mode = .worktree
        base = repo?.checkoutBranch
        let name = typed.trimmingCharacters(in: .whitespacesAndNewlines)
        branch = name.isEmpty ? nil : name
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
