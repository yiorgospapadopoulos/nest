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

    public init(
        commitMessage: String, files: [String]? = nil, push: Bool = true, openPR: Bool = true,
        prTitle: String? = nil, prBody: String? = nil, acknowledgeViolation: Bool = false
    ) {
        self.commitMessage = commitMessage
        self.files = files
        self.push = push
        self.openPR = openPR
        self.prTitle = prTitle
        self.prBody = prBody
        self.acknowledgeViolation = acknowledgeViolation
    }

    enum CodingKeys: String, CodingKey {
        case files, push
        case commitMessage = "commit_message"
        case openPR = "open_pr"
        case prTitle = "pr_title"
        case prBody = "pr_body"
        case acknowledgeViolation = "acknowledge_violation"
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

    /// Continues with the plan; the chat switches to Accept edits.
    public static let approvePlan = Self(
        behavior: nil, message: nil, always: false, answers: nil, dismiss: false,
        decision: .approve)

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

/// `POST /api/pixies`; fields left nil use the daemon's defaults.
public struct CreatePixieRequest: Encodable, Sendable, Hashable {
    public var name: String
    public var slug: String?
    public var mascot: Mascot?
    public var color: String?
    public var background: PixieBackground?
    public var model: String?
    public var effort: Effort?
    public var permissionMode: PermissionMode?
    public var autonomy: Autonomy?
    public var projectAccess: ProjectAccess?
    /// Repo names; nil means every project.
    public var projects: [String]?
    public var skills: [String]?
    public var allowedTools: [String]?
    public var disallowedTools: [String]?
    public var hidden: Bool?
    /// The first text of the pixie's `SOUL.md`.
    public var soul: String?

    public init(
        name: String, slug: String? = nil, mascot: Mascot? = nil, color: String? = nil,
        background: PixieBackground? = nil, model: String? = nil, effort: Effort? = nil,
        permissionMode: PermissionMode? = nil, autonomy: Autonomy? = nil,
        projectAccess: ProjectAccess? = nil, projects: [String]? = nil, skills: [String]? = nil,
        allowedTools: [String]? = nil, disallowedTools: [String]? = nil, hidden: Bool? = nil,
        soul: String? = nil
    ) {
        self.name = name
        self.slug = slug
        self.mascot = mascot
        self.color = color
        self.background = background
        self.model = model
        self.effort = effort
        self.permissionMode = permissionMode
        self.autonomy = autonomy
        self.projectAccess = projectAccess
        self.projects = projects
        self.skills = skills
        self.allowedTools = allowedTools
        self.disallowedTools = disallowedTools
        self.hidden = hidden
        self.soul = soul
    }

    enum CodingKeys: String, CodingKey {
        case name, slug, mascot, color, background, model, effort, autonomy, projects, skills
        case hidden, soul
        case permissionMode = "permission_mode"
        case projectAccess = "project_access"
        case allowedTools = "allowed_tools"
        case disallowedTools = "disallowed_tools"
    }
}

/// `PATCH /api/pixies/{id}`; nil fields are left unchanged.
public struct UpdatePixieRequest: Encodable, Sendable, Hashable {
    public var name: String?
    public var slug: String?
    public var mascot: Mascot?
    public var color: String?
    public var background: PixieBackground?
    public var model: String?
    public var effort: Effort?
    public var permissionMode: PermissionMode?
    public var autonomy: Autonomy?
    public var projectAccess: ProjectAccess?
    public var projects: [String]?
    public var skills: [String]?
    public var allowedTools: [String]?
    public var disallowedTools: [String]?
    public var hidden: Bool?
    /// True sets `projects` back to every project.
    public var allProjects: Bool?

    public init(
        name: String? = nil, slug: String? = nil, mascot: Mascot? = nil, color: String? = nil,
        background: PixieBackground? = nil, model: String? = nil, effort: Effort? = nil,
        permissionMode: PermissionMode? = nil, autonomy: Autonomy? = nil,
        projectAccess: ProjectAccess? = nil, projects: [String]? = nil, skills: [String]? = nil,
        allowedTools: [String]? = nil, disallowedTools: [String]? = nil, hidden: Bool? = nil,
        allProjects: Bool? = nil
    ) {
        self.name = name
        self.slug = slug
        self.mascot = mascot
        self.color = color
        self.background = background
        self.model = model
        self.effort = effort
        self.permissionMode = permissionMode
        self.autonomy = autonomy
        self.projectAccess = projectAccess
        self.projects = projects
        self.skills = skills
        self.allowedTools = allowedTools
        self.disallowedTools = disallowedTools
        self.hidden = hidden
        self.allProjects = allProjects
    }

    enum CodingKeys: String, CodingKey {
        case name, slug, mascot, color, background, model, effort, autonomy, projects, skills
        case hidden
        case permissionMode = "permission_mode"
        case projectAccess = "project_access"
        case allowedTools = "allowed_tools"
        case disallowedTools = "disallowed_tools"
        case allProjects = "all_projects"
    }
}

/// `PUT /api/pixies/{id}/files/{name}`: the hash is the one the writer read, null for a
/// file that does not exist yet.
public struct WritePixieFileRequest: Encodable, Sendable, Hashable {
    public var text: String
    public var hash: String?

    public init(text: String, hash: String?) {
        self.text = text
        self.hash = hash
    }

    enum CodingKeys: String, CodingKey {
        case text, hash
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(text, forKey: .text)
        try container.encode(hash, forKey: .hash)
    }
}
