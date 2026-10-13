import Foundation

public enum ApprovalKind: String, UnknownSafeEnum {
    /// A tool call the agent waits to be allowed.
    case permission
    /// The agent's AskUserQuestion, waiting for answers.
    case question
    /// Finished work to approve, reject or send feedback on.
    case review
    /// A plan Claude finished in plan mode: Approve plan or Keep planning.
    case plan
    /// A green, mergeable pull request: Merge or Dismiss.
    case merge
    case unknown
}

public enum ApprovalStatus: String, UnknownSafeEnum {
    case pending, resolved, expired, superseded
    case unknown
}

/// An item of the approval queue; `payload` depends on the kind.
public struct Approval: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var sessionID: String
    /// The session's repo and title.
    public var repo: String
    public var title: String
    public var kind: ApprovalKind
    public var status: ApprovalStatus
    public var payload: JSONValue
    public var resolution: JSONValue?
    public var createdAt: Date
    public var resolvedAt: Date?

    enum CodingKeys: String, CodingKey {
        case id, repo, title, kind, status, payload, resolution
        case sessionID = "session_id"
        case createdAt = "created_at"
        case resolvedAt = "resolved_at"
    }

    /// Asked in a pixie's chat, whose repo is `pixie:<id>` rather than a project (D057).
    public var isPixieChat: Bool { repo.hasPrefix("pixie:") }

    public var permission: PermissionRequest? {
        kind == .permission ? try? payload.decode(PermissionRequest.self) : nil
    }

    public var question: QuestionRequest? {
        kind == .question ? try? payload.decode(QuestionRequest.self) : nil
    }

    public var review: ReviewSummary? {
        kind == .review ? try? payload.decode(ReviewSummary.self) : nil
    }

    public var plan: PlanRequest? {
        kind == .plan ? try? payload.decode(PlanRequest.self) : nil
    }

    public var merge: MergeProposal? {
        kind == .merge ? try? payload.decode(MergeProposal.self) : nil
    }
}

public struct PermissionRequest: Decodable, Sendable, Hashable {
    public var tool: String
    public var input: JSONValue
    /// The engine's own sentence for the prompt, when it gives one.
    public var title: String?
    /// Why Claude Code asks, when it says, such as the rule or path involved.
    public var reason: String?
}

public struct QuestionRequest: Decodable, Sendable, Hashable {
    public var toolUseID: String
    public var questions: [Question]

    enum CodingKeys: String, CodingKey {
        case questions
        case toolUseID = "tool_use_id"
    }
}

public struct Question: Decodable, Sendable, Hashable {
    public var question: String
    public var header: String?
    public var multiSelect: Bool
    public var options: [QuestionOption]

    enum CodingKeys: String, CodingKey {
        case question, header, options
        case multiSelect = "multi_select"
    }
}

public struct QuestionOption: Decodable, Sendable, Hashable {
    public var label: String
    public var description: String?
    /// The option the agent prefers.
    public var recommended: Bool
}

public struct ReviewSummary: Decodable, Sendable, Hashable {
    public var base: String?
    public var files: Int
    public var additions: Int
    public var deletions: Int
    public var paths: [String]
    /// The agent's last summary of the work.
    public var summary: String?
}
