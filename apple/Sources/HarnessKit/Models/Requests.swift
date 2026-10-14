import Foundation

/// `POST /api/sessions`; fields left nil use the daemon's defaults.
public struct CreateSessionRequest: Encodable, Sendable, Hashable {
    public var repo: String
    public var prompt: String
    public var title: String?
    public var mode: SessionMode?
    public var model: String?
    public var effort: Effort?
    public var permissionMode: PermissionMode?
    public var attachmentIDs: [String]
    /// In-place sessions refuse a dirty checkout unless this is set.
    public var allowDirty: Bool

    public init(
        repo: String, prompt: String, title: String? = nil, mode: SessionMode? = nil,
        model: String? = nil, effort: Effort? = nil, permissionMode: PermissionMode? = nil,
        attachmentIDs: [String] = [], allowDirty: Bool = false
    ) {
        self.repo = repo
        self.prompt = prompt
        self.title = title
        self.mode = mode
        self.model = model
        self.effort = effort
        self.permissionMode = permissionMode
        self.attachmentIDs = attachmentIDs
        self.allowDirty = allowDirty
    }

    enum CodingKeys: String, CodingKey {
        case repo, prompt, title, mode, model, effort
        case permissionMode = "permission_mode"
        case attachmentIDs = "attachment_ids"
        case allowDirty = "allow_dirty"
    }
}

/// `PATCH /api/sessions/{id}`; nil fields are left unchanged.
public struct UpdateSessionRequest: Encodable, Sendable, Hashable {
    public var model: String?
    /// Applies from the chat's next message.
    public var effort: Effort?
    public var permissionMode: PermissionMode?
    public var title: String?
    public var pinned: Bool?
    /// True archives the session and closes its agent run; false restores it.
    public var archived: Bool?

    public init(
        model: String? = nil, effort: Effort? = nil, permissionMode: PermissionMode? = nil,
        title: String? = nil, pinned: Bool? = nil, archived: Bool? = nil
    ) {
        self.model = model
        self.effort = effort
        self.permissionMode = permissionMode
        self.title = title
        self.pinned = pinned
        self.archived = archived
    }

    enum CodingKeys: String, CodingKey {
        case model, effort, title, pinned, archived
        case permissionMode = "permission_mode"
    }
}

/// `POST /api/sessions/{id}/approve`: commit, push and open a pull request.
public struct ApproveRequest: Encodable, Sendable, Hashable {
    public var commitMessage: String
    /// In-place sessions only, and required there: the files to commit.
    public var files: [String]?
    public var push: Bool
    public var openPR: Bool
    public var prTitle: String?
    public var prBody: String?
    /// Publish even though the agent changed git refs itself.
    public var acknowledgeViolation: Bool
    /// HEAD's commit as the review showed it; the daemon refuses if it moved since.
    public var expectedHead: String?
    /// The fingerprint of the review the user saw; the daemon refuses if the changes differ.
    public var expectedFingerprint: String?
    /// The address origin pushes to now, which the user agreed to push to (I-008).
    public var confirmRemoteURL: String?

    public init(
        commitMessage: String, files: [String]? = nil, push: Bool = true, openPR: Bool = true,
        prTitle: String? = nil, prBody: String? = nil, acknowledgeViolation: Bool = false,
        expectedHead: String? = nil, expectedFingerprint: String? = nil,
        confirmRemoteURL: String? = nil
    ) {
        self.commitMessage = commitMessage
        self.files = files
        self.push = push
        self.openPR = openPR
        self.prTitle = prTitle
        self.prBody = prBody
        self.acknowledgeViolation = acknowledgeViolation
        self.expectedHead = expectedHead
        self.expectedFingerprint = expectedFingerprint
        self.confirmRemoteURL = confirmRemoteURL
    }

    enum CodingKeys: String, CodingKey {
        case files, push
        case commitMessage = "commit_message"
        case openPR = "open_pr"
        case prTitle = "pr_title"
        case prBody = "pr_body"
        case acknowledgeViolation = "acknowledge_violation"
        case expectedHead = "expected_head"
        case expectedFingerprint = "expected_fingerprint"
        case confirmRemoteURL = "confirm_remote_url"
    }
}

/// `POST /api/approvals/{id}/resolve` for permissions, questions and plans.
public struct ResolveApprovalRequest: Encodable, Sendable, Hashable {
    public enum Behavior: String, Encodable, Sendable {
        case allow, deny
    }

    public enum Decision: String, Encodable, Sendable {
        case approve
        case keepPlanning = "keep_planning"
    }

    public var behavior: Behavior?
    public var message: String?
    /// Allow the tool for the rest of the session.
    public var always: Bool
    /// Question text to the chosen labels (or free text).
    public var answers: [String: [String]]?
    public var dismiss: Bool
    /// Plans only.
    public var decision: Decision?
    /// Approved plans only: how the chat goes on (`PermissionMode.planChoices`).
    public var mode: PermissionMode?

    public static func allow(always: Bool = false, message: String? = nil) -> Self {
        Self(behavior: .allow, message: message, always: always, answers: nil, dismiss: false)
    }

    public static func deny(message: String? = nil) -> Self {
        Self(behavior: .deny, message: message, always: false, answers: nil, dismiss: false)
    }

    public static func answer(_ answers: [String: [String]]) -> Self {
        Self(behavior: nil, message: nil, always: false, answers: answers, dismiss: false)
    }

    public static func dismiss(message: String? = nil) -> Self {
        Self(behavior: nil, message: message, always: false, answers: nil, dismiss: true)
    }

    /// Continues with the plan in the given mode, Accept edits unless chosen otherwise.
    public static func approvePlan(mode: PermissionMode = .acceptEdits) -> Self {
        Self(
            behavior: nil, message: nil, always: false, answers: nil, dismiss: false,
            decision: .approve, mode: mode)
    }

    /// Sends Claude back to planning, with the user's note when it is not blank.
    public static func keepPlanning(note: String = "") -> Self {
        let trimmed = note.trimmingCharacters(in: .whitespacesAndNewlines)
        return Self(
            behavior: nil, message: trimmed.isEmpty ? nil : trimmed, always: false,
            answers: nil, dismiss: false, decision: .keepPlanning)
    }
}

struct RegisterRepoRequest: Encodable {
    var path: String
    var name: String?
}

struct MessageRequest: Encodable {
    var text: String
    var attachmentIDs: [String]
    /// Sent only when set: stop the running turn and run this message next.
    var interrupt: Bool?

    enum CodingKeys: String, CodingKey {
        case text, interrupt
        case attachmentIDs = "attachment_ids"
    }
}

struct FeedbackRequest: Encodable {
    var text: String
}

struct VisibilityRequest: Encodable {
    var visible: Bool
    var client: String
}

struct OpenRepoRequest: Encodable {
    var app: RepoApp
}

struct ArchiveRequest: Encodable {
    var archived: Bool
}

struct RewindRequest: Encodable {
    /// The user message's event id.
    var message: Int
}
