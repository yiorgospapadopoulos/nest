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
    /// Worktree chats only: the local branch the worktree starts from (B55).
    public var base: String?
    /// Worktree chats only: the new branch's name; nil lets the daemon name it.
    public var branch: String?

    public init(
        repo: String, prompt: String, title: String? = nil, mode: SessionMode? = nil,
        model: String? = nil, effort: Effort? = nil, permissionMode: PermissionMode? = nil,
        attachmentIDs: [String] = [], base: String? = nil, branch: String? = nil
    ) {
        self.repo = repo
        self.prompt = prompt
        self.title = title
        self.mode = mode
        self.model = model
        self.effort = effort
        self.permissionMode = permissionMode
        self.attachmentIDs = attachmentIDs
        self.base = base
        self.branch = branch
    }

    enum CodingKeys: String, CodingKey {
        case repo, prompt, title, mode, model, effort, base, branch
        case permissionMode = "permission_mode"
        case attachmentIDs = "attachment_ids"
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
    /// HEAD's commit as the review showed it; the daemon refuses if it moved since.
    public var expectedHead: String?
    /// The fingerprint of the review the user saw; the daemon refuses if the changes differ.
    public var expectedFingerprint: String?
    /// The address origin pushes to now, which the user agreed to push to (I-008).
    public var confirmRemoteURL: String?

    public init(
        commitMessage: String, files: [String]? = nil, push: Bool = true, openPR: Bool = true,
        prTitle: String? = nil, prBody: String? = nil,
        expectedHead: String? = nil, expectedFingerprint: String? = nil,
        confirmRemoteURL: String? = nil
    ) {
        self.commitMessage = commitMessage
        self.files = files
        self.push = push
        self.openPR = openPR
        self.prTitle = prTitle
        self.prBody = prBody
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
    var restore: RewindRestore
}

struct ShellRequest: Encodable {
    var command: String
}

struct MemoryRequest: Encodable {
    var text: String
    var scope: MemoryScope
}

struct ForkRequest: Encodable {
    /// The user message's event id.
    var message: Int
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

/// `PATCH /api/pixies/{id}`; nil fields are left unchanged. `clearsModel` and
/// `clearsEffort` send an explicit null, which sets Model or Thinking back to Default.
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
    /// True sends `"model": null`: the pixie follows the agent default again. A `model`
    /// set as well wins.
    public var clearsModel: Bool
    /// True sends `"effort": null`: thinking is left to the model again. An `effort` set as
    /// well wins.
    public var clearsEffort: Bool
    /// True sets `projects` back to every project.
    public var allProjects: Bool?
    /// The team to join.
    public var teamID: String?
    /// True sends `"team_id": null`: the pixie leaves its team. A `teamID` set as well wins.
    public var leavesTeam: Bool
    /// `PixieLimits.running`.
    public var maxRunning: Int?
    /// `PixieLimits.perDay`.
    public var maxPerDay: Int?
    /// The least severe report that reaches the phone (B42).
    public var reportPush: ReportSeverity?

    public init(
        name: String? = nil, slug: String? = nil, mascot: Mascot? = nil, color: String? = nil,
        background: PixieBackground? = nil, model: String? = nil, effort: Effort? = nil,
        permissionMode: PermissionMode? = nil, autonomy: Autonomy? = nil,
        projectAccess: ProjectAccess? = nil, projects: [String]? = nil, skills: [String]? = nil,
        allowedTools: [String]? = nil, disallowedTools: [String]? = nil, hidden: Bool? = nil,
        clearsModel: Bool = false, clearsEffort: Bool = false, allProjects: Bool? = nil,
        teamID: String? = nil, leavesTeam: Bool = false, maxRunning: Int? = nil,
        maxPerDay: Int? = nil, reportPush: ReportSeverity? = nil
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
        self.clearsModel = clearsModel
        self.clearsEffort = clearsEffort
        self.allProjects = allProjects
        self.teamID = teamID
        self.leavesTeam = leavesTeam
        self.maxRunning = maxRunning
        self.maxPerDay = maxPerDay
        self.reportPush = reportPush
    }

    enum CodingKeys: String, CodingKey {
        case name, slug, mascot, color, background, model, effort, autonomy, projects, skills
        case hidden
        case permissionMode = "permission_mode"
        case projectAccess = "project_access"
        case allowedTools = "allowed_tools"
        case disallowedTools = "disallowed_tools"
        case allProjects = "all_projects"
        case teamID = "team_id"
        case maxRunning = "max_running"
        case maxPerDay = "max_per_day"
        case reportPush = "report_push"
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encodeIfPresent(name, forKey: .name)
        try container.encodeIfPresent(slug, forKey: .slug)
        try container.encodeIfPresent(mascot, forKey: .mascot)
        try container.encodeIfPresent(color, forKey: .color)
        try container.encodeIfPresent(background, forKey: .background)
        if let model {
            try container.encode(model, forKey: .model)
        } else if clearsModel {
            try container.encodeNil(forKey: .model)
        }
        if let effort {
            try container.encode(effort, forKey: .effort)
        } else if clearsEffort {
            try container.encodeNil(forKey: .effort)
        }
        try container.encodeIfPresent(permissionMode, forKey: .permissionMode)
        try container.encodeIfPresent(autonomy, forKey: .autonomy)
        try container.encodeIfPresent(projectAccess, forKey: .projectAccess)
        try container.encodeIfPresent(projects, forKey: .projects)
        try container.encodeIfPresent(skills, forKey: .skills)
        try container.encodeIfPresent(allowedTools, forKey: .allowedTools)
        try container.encodeIfPresent(disallowedTools, forKey: .disallowedTools)
        try container.encodeIfPresent(hidden, forKey: .hidden)
        try container.encodeIfPresent(allProjects, forKey: .allProjects)
        if let teamID {
            try container.encode(teamID, forKey: .teamID)
        } else if leavesTeam {
            try container.encodeNil(forKey: .teamID)
        }
        try container.encodeIfPresent(maxRunning, forKey: .maxRunning)
        try container.encodeIfPresent(maxPerDay, forKey: .maxPerDay)
        try container.encodeIfPresent(reportPush, forKey: .reportPush)
    }
}

/// `POST /api/pixies/{id}/habits`: a habit needs a schedule or at least one trigger.
public struct CreateHabitRequest: Encodable, Sendable, Hashable {
    public var name: String
    public var prompt: String
    public var schedule: HabitSchedule?
    public var triggers: [HabitTrigger]
    public var maxMinutes: Int
    public var enabled: Bool

    public init(
        name: String, prompt: String, schedule: HabitSchedule?, triggers: [HabitTrigger],
        maxMinutes: Int, enabled: Bool = true
    ) {
        self.name = name
        self.prompt = prompt
        self.schedule = schedule
        self.triggers = triggers
        self.maxMinutes = maxMinutes
        self.enabled = enabled
    }

    enum CodingKeys: String, CodingKey {
        case name, prompt, schedule, triggers, enabled
        case maxMinutes = "max_minutes"
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(name, forKey: .name)
        try container.encode(prompt, forKey: .prompt)
        try container.encode(schedule, forKey: .schedule)
        try container.encode(triggers, forKey: .triggers)
        try container.encode(maxMinutes, forKey: .maxMinutes)
        try container.encode(enabled, forKey: .enabled)
    }
}

/// `PATCH /api/pixies/{id}/habits/{hid}`: only the fields given change.
public struct UpdateHabitRequest: Encodable, Sendable, Hashable {
    public var name: String?
    public var prompt: String?
    public var schedule: HabitSchedule?
    /// True sends `"schedule": null`: the habit runs on its triggers only.
    public var clearsSchedule: Bool
    public var triggers: [HabitTrigger]?
    public var maxMinutes: Int?
    public var enabled: Bool?

    public init(
        name: String? = nil, prompt: String? = nil, schedule: HabitSchedule? = nil,
        clearsSchedule: Bool = false, triggers: [HabitTrigger]? = nil, maxMinutes: Int? = nil,
        enabled: Bool? = nil
    ) {
        self.name = name
        self.prompt = prompt
        self.schedule = schedule
        self.clearsSchedule = clearsSchedule
        self.triggers = triggers
        self.maxMinutes = maxMinutes
        self.enabled = enabled
    }

    enum CodingKeys: String, CodingKey {
        case name, prompt, schedule, triggers, enabled
        case maxMinutes = "max_minutes"
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encodeIfPresent(name, forKey: .name)
        try container.encodeIfPresent(prompt, forKey: .prompt)
        if let schedule {
            try container.encode(schedule, forKey: .schedule)
        } else if clearsSchedule {
            try container.encodeNil(forKey: .schedule)
        }
        try container.encodeIfPresent(triggers, forKey: .triggers)
        try container.encodeIfPresent(maxMinutes, forKey: .maxMinutes)
        try container.encodeIfPresent(enabled, forKey: .enabled)
    }
}

/// `POST /api/pixie-teams`; the daemon derives the handle from the name when it is nil.
public struct CreatePixieTeamRequest: Encodable, Sendable, Hashable {
    public var name: String
    public var handle: String?

    public init(name: String, handle: String? = nil) {
        self.name = name
        self.handle = handle
    }
}

/// `PATCH /api/pixie-teams/{id}`; nil fields are left unchanged. The leader must be a
/// member.
public struct UpdatePixieTeamRequest: Encodable, Sendable, Hashable {
    public var name: String?
    public var handle: String?
    public var leaderID: String?

    public init(name: String? = nil, handle: String? = nil, leaderID: String? = nil) {
        self.name = name
        self.handle = handle
        self.leaderID = leaderID
    }

    enum CodingKeys: String, CodingKey {
        case name, handle
        case leaderID = "leader_id"
    }
}

/// `PUT /api/pixies/order`: every pixie's id, in the new order.
public struct ReorderPixiesRequest: Encodable, Sendable, Hashable {
    public var ids: [String]

    public init(ids: [String]) {
        self.ids = ids
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
