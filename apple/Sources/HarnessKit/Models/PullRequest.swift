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

/// A pull request harness opened, as the daemon last read it from GitHub (D034).
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
    public var createdAt: Date?
    /// When harness last saw something change, and when it last asked GitHub.
    public var changedAt: Date
    public var updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case number, url, title, state, checks, mergeable
        case mergeState = "merge_state"
        case reviewDecision = "review_decision"
        case headSHA = "head_sha"
        case createdAt = "created_at"
        case changedAt = "changed_at"
        case updatedAt = "updated_at"
    }

    /// The names of the checks that failed, in GitHub's order.
    public var failingChecks: [String] {
        checks.items.filter { $0.state == .failure }.map(\.name)
    }
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
    /// Deletes the remote branch after merging.
    public var deleteBranch: Bool

    public init(method: MergeMethod = .squash, deleteBranch: Bool = true) {
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

    public static func stateLabel(_ state: PRState) -> String {
        switch state {
        case .open: "Open"
        case .merged: "Merged"
        case .closed: "Closed"
        case .unknown: "Unknown"
        }
    }
}

/// What "Send to agent" sends when checks failed, the same on the iPhone. Agents have no
/// GitHub login (D013), so it asks for the logs rather than have the agent fetch them.
public enum CIFailure {
    public static func message(_ checks: [String]) -> String {
        "CI failed: \(checks.joined(separator: ", ")). Please fix. You can't use gh or reach"
            + " GitHub from here, so work from the code and the check names, and ask me for"
            + " the logs if you need them."
    }
}
