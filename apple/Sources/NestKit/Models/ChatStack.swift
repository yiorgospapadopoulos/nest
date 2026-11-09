import Foundation

/// A chat whose branch starts from another chat's branch (B149): its pull request merges
/// into that branch while the other one's is open.
public struct ChatStack: Codable, Sendable, Hashable {
    /// The chat under this one; nil once its work reached the default branch.
    public var parent: String?
    public var parentBranch: String?
    /// Set while the branch has to move onto a new base, after the one under it changed.
    public var restack: Restack?

    enum CodingKeys: String, CodingKey {
        case parent, restack
        case parentBranch = "parent_branch"
    }

    /// "On top of #12", by the chat under it: its pull request, else its title, else the
    /// branch it starts from.
    public func onTopLabel(parent chat: Session?) -> String? {
        guard parent != nil else { return nil }
        if let number = chat?.pr?.number {
            return "On top of #\(number)"
        }
        return (chat?.title ?? parentBranch).map { "On top of \($0)" }
    }
}

/// Where a stacked chat's branch moves; `rebased` is the rebased commit once the rebase
/// happened, `error` why it could not.
public struct Restack: Codable, Sendable, Hashable {
    public var base: String
    public var rebased: String?
    public var error: String?

    public var line: String { "Moves onto \(base)" }
}

/// The one button a branch to move gets, from what is left to do.
public enum RestackAction: Sendable, Hashable {
    case push, rebaseAndPush, rebase

    /// Without an open pull request there is nothing to push.
    public init(rebased: Bool, openPR: Bool) {
        self = !openPR ? .rebase : rebased ? .push : .rebaseAndPush
    }

    public init(_ restack: Restack, of session: Session) {
        self.init(rebased: restack.rebased != nil, openPR: session.hasOpenPR)
    }

    public init(_ request: RestackRequest) {
        self.init(rebased: request.rebased, openPR: request.url != nil)
    }

    public var title: String {
        switch self {
        case .push: "Push"
        case .rebaseAndPush: "Rebase and push"
        case .rebase: "Rebase"
        }
    }

    /// The toast's start when it fails.
    public var failure: String {
        switch self {
        case .push: "Could not push"
        case .rebaseAndPush, .rebase: "Could not rebase"
        }
    }

    public var help: String {
        switch self {
        case .push: "Push the rebased branch and point the pull request at its new base"
        case .rebaseAndPush: "Rebase the branch onto its new base, then push it"
        case .rebase: "Rebase the branch onto its new base"
        }
    }
}

/// A restack approval's payload: a stacked chat's branch to move onto a new base.
public struct RestackRequest: Decodable, Sendable, Hashable {
    public var branch: String?
    public var base: String
    public var rebased: Bool
    public var error: String?
    public var number: Int?
    public var url: String?

    /// "feature-b moved onto main", or "Move feature-b onto main" before the rebase.
    public var headline: String {
        rebased
            ? "\(branch ?? "The branch") moved onto \(base)"
            : "Move \(branch ?? "the branch") onto \(base)"
    }
}

extension Session {
    /// Like the daemon: a pull request was opened and is not known to be merged or closed.
    public var hasOpenPR: Bool {
        prURL != nil && (pr == nil || pr?.state == .open)
    }
}
