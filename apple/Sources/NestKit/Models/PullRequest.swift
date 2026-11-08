import Foundation

public enum PRState: String, UnknownSafeEnum {
    case open, merged, closed
    case unknown
}

/// One check; skipped and neutral checks count as passed.
public enum CheckState: String, UnknownSafeEnum {
    case pending, success, failure, skipped
    case unknown
}

/// All checks of a pull request together.
public enum ChecksState: String, UnknownSafeEnum {
    case pending, success, failure
    /// The pull request has no checks.
    case noChecks = "none"
    case unknown
}

public enum MergeMethod: String, Codable, Sendable, Hashable, CaseIterable {
    case squash, merge, rebase

    /// The method menu's entries.
    public var label: String {
        switch self {
        case .squash: "Squash and merge"
        case .merge: "Merge commit"
        case .rebase: "Rebase and merge"
        }
    }
}

public struct PRCheck: Codable, Sendable, Hashable {
    public var name: String
    public var state: CheckState
    public var url: String?
}

/// The checks summary; merge approvals carry it without the items.
public struct PRChecks: Codable, Sendable, Hashable {
    public var state: ChecksState
    public var passed: Int
    public var failed: Int
    public var pending: Int
    public var items: [PRCheck]

    enum CodingKeys: String, CodingKey {
        case state, passed, failed, pending, items
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        state = try container.decode(ChecksState.self, forKey: .state)
        passed = try container.decode(Int.self, forKey: .passed)
        failed = try container.decode(Int.self, forKey: .failed)
        pending = try container.decode(Int.self, forKey: .pending)
        items = try container.decodeIfPresent([PRCheck].self, forKey: .items) ?? []
    }
}

/// A pull request Nest opened, as the daemon last read it from GitHub (D034).
public struct PullRequest: Codable, Sendable, Hashable {
    public var number: Int
    public var url: String
    public var title: String
    public var state: PRState
    public var checks: PRChecks
    /// Nil while GitHub works it out.
    public var mergeable: Bool?
    public var mergeState: String?
    public var reviewDecision: String?
    public var headSHA: String?
    /// The branch it merges into; missing on daemons before B149.
    public var baseBranch: String?
    /// Set while GitHub's own auto-merge is on for it (B149).
    public var autoMerge: GitHubAutoMerge?
    public var createdAt: Date?
    /// When Nest last saw something change, and when it last asked GitHub.
    public var changedAt: Date
    public var updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case number, url, title, state, checks, mergeable
        case mergeState = "merge_state"
        case reviewDecision = "review_decision"
        case headSHA = "head_sha"
        case baseBranch = "base_branch"
        case autoMerge = "auto_merge"
        case createdAt = "created_at"
        case changedAt = "changed_at"
        case updatedAt = "updated_at"
    }

    /// The names of the checks that failed, in GitHub's order.
    public var failingChecks: [String] {
        checks.items.filter { $0.state == .failure }.map(\.name)
    }
}

/// GitHub's own auto-merge, on for a pull request; it merges there when checks pass.
public struct GitHubAutoMerge: Codable, Sendable, Hashable {
    public var enabledAt: Date?

    enum CodingKeys: String, CodingKey {
        case enabledAt = "enabled_at"
    }
}

/// A chat's "Merge when checks pass" (B149): Nest merges the pull request itself once it is
/// green, when GitHub's auto-merge is not available for it.
public struct MergeWhenReady: Codable, Sendable, Hashable {
    public var method: MergeMethod
    public var deleteBranch: Bool

    public init(method: MergeMethod = .squash, deleteBranch: Bool = false) {
        self.method = method
        self.deleteBranch = deleteBranch
    }

    enum CodingKeys: String, CodingKey {
        case method
        case deleteBranch = "delete_branch"
    }
}

/// `PATCH /api/sessions/{id}/pr/auto-merge`; the daemon squashes and keeps the branch.
struct AutoMergeRequest: Encodable {
    var enabled: Bool
}

/// A merge approval's payload: the pull request is green and mergeable at this commit.
public struct MergeProposal: Decodable, Sendable, Hashable {
    public var number: Int
    public var title: String
    public var url: String
    public var headSHA: String?
    public var checks: PRChecks

    enum CodingKeys: String, CodingKey {
        case number, title, url, checks
        case headSHA = "head_sha"
    }
}

/// `POST /api/sessions/{id}/merge`.
public struct MergeRequest: Encodable, Sendable, Hashable {
    public var method: MergeMethod
    /// Deletes the branch on GitHub after merging; only when the user ticks it (B96). Nest
    /// deletes no branch otherwise.
    public var deleteBranch: Bool

    public init(method: MergeMethod = .squash, deleteBranch: Bool = false) {
        self.method = method
        self.deleteBranch = deleteBranch
    }

    enum CodingKeys: String, CodingKey {
        case method
        case deleteBranch = "delete_branch"
    }
}

/// How a pull request shows in chips, popovers and cards.
public enum PRBadge {
    /// The chip's dot: amber while checks run, green when they passed, red when one failed,
    /// hollow without checks; grey once merged or closed.
    public static func dot(of pr: PullRequest) -> (tone: StatusTone, hollow: Bool) {
        guard pr.state == .open else { return (.done, false) }
        switch pr.checks.state {
        case .pending: return (.waiting, false)
        case .success: return (.review, false)
        case .failure: return (.failed, false)
        case .noChecks, .unknown: return (.done, true)
        }
    }

    /// Such as "2 failed, 3 passed", "1 running" or "No checks".
    public static func checksSummary(_ checks: PRChecks) -> String {
        var parts: [String] = []
        if checks.failed > 0 {
            parts.append("\(checks.failed) failed")
        }
        if checks.pending > 0 {
            parts.append("\(checks.pending) running")
        }
        if checks.passed > 0 {
            parts.append("\(checks.passed) passed")
        }
        return parts.isEmpty ? "No checks" : parts.joined(separator: ", ")
    }

    /// The popover's grey line under the pull request: "Open · 3 passed".
    public static func statusLine(_ pr: PullRequest) -> String {
        "\(stateLabel(pr.state)) \u{00B7} \(checksSummary(pr.checks))"
    }

    /// The popover's row for a chat from an issue: GitHub closes it with the merge, from
    /// the pull request's "Closes #118" (B101).
    public static func closes(_ issue: IssueRef) -> String {
        "Closes #\(issue.number) on merge"
    }

    public static let autoSendTitle = "Send review comments on their own"

    public static func autoSendDetail(_ on: Bool) -> String {
        on ? "New comments go to the agent as they arrive" : "Off: they wait in Needs you"
    }

    /// Whether the chat sends new review comments itself; off until the user turns it on.
    public static func autoSends(_ session: Session) -> Bool {
        session.review?.autoSend ?? false
    }

    public static let mergeWhenReadyTitle = "Merge when checks pass"

    /// On while Nest waits to merge or GitHub's own auto-merge is on.
    public static func mergesWhenReady(_ session: Session) -> Bool {
        session.mergeWhenReady != nil || session.pr?.autoMerge != nil
    }

    /// Who merges it, while the switch is on; nil while it is off.
    public static func mergeWhenReadyDetail(_ session: Session) -> String? {
        if session.pr?.autoMerge != nil {
            return "GitHub merges it when checks pass"
        }
        return session.mergeWhenReady == nil
            ? nil : "Nest merges it when checks pass, while Nest is running"
    }

    public static func stateLabel(_ state: PRState) -> String {
        switch state {
        case .open: "Open"
        case .merged: "Merged"
        case .closed: "Closed"
        case .unknown: "Unknown"
        }
    }
}
