import Foundation

/// The pixie's pixel-art mascot; `MascotSprites` draws it (D072).
public enum Mascot: String, Codable, Sendable, CaseIterable, UnknownSafeEnum {
    case invader, ghost, cat, owl, robot, frog, mushroom, bunny, crab, sprout
    case unknown
}

public enum PixieBackground: String, Codable, Sendable, CaseIterable, UnknownSafeEnum {
    case plain, meadow, dusk, night, dawn
    case unknown
}

/// What a pixie may do on its own; stored now, used in stage 3.
public enum Autonomy: String, Codable, Sendable, CaseIterable, UnknownSafeEnum {
    case observe, message, start, answer
    case unknown
}

/// How far a pixie's chat reaches into the user's projects.
public enum ProjectAccess: String, Codable, Sendable, CaseIterable, UnknownSafeEnum {
    case edit, read
    /// Wire value "none"; named apart so `.none` never reads as `Optional.none`.
    case noAccess = "none"
    case unknown
}

/// A long-lived assistant with its own soul, memory and chat (D072).
public struct Pixie: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var slug: String
    public var name: String
    public var mascot: Mascot
    /// `#RRGGBB`.
    public var color: String
    public var background: PixieBackground
    public var model: String?
    public var effort: Effort?
    public var permissionMode: PermissionMode
    public var autonomy: Autonomy
    public var projectAccess: ProjectAccess
    /// Repo names; nil means every project.
    public var projects: [String]?
    public var skills: [String]
    public var canCall: [String]
    public var allowedTools: [String]
    public var disallowedTools: [String]
    public var hidden: Bool
    public var position: Int
    public var chatSessionID: String?
    public var createdAt: Date
    public var updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case id, slug, name, mascot, color, background, model, effort, autonomy, projects, skills
        case hidden, position
        case permissionMode = "permission_mode"
        case projectAccess = "project_access"
        case canCall = "can_call"
        case allowedTools = "allowed_tools"
        case disallowedTools = "disallowed_tools"
        case chatSessionID = "chat_session_id"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

extension Pixie {
    /// The pixie with the change made, as the daemon makes it; the app shows it while the
    /// change saves. The daemon's answer has the last word, such as Auto dropping to Ask
    /// before edits on a model without it.
    public func applying(_ change: UpdatePixieRequest) -> Pixie {
        var pixie = self
        pixie.name = change.name ?? name
        pixie.slug = change.slug ?? slug
        pixie.mascot = change.mascot ?? mascot
        pixie.color = change.color ?? color
        pixie.background = change.background ?? background
        pixie.model = change.model ?? (change.clearsModel ? nil : model)
        pixie.effort = change.effort ?? (change.clearsEffort ? nil : effort)
        pixie.permissionMode = change.permissionMode ?? permissionMode
        pixie.autonomy = change.autonomy ?? autonomy
        pixie.projectAccess = change.projectAccess ?? projectAccess
        pixie.projects = change.allProjects == true ? nil : change.projects ?? projects
        pixie.skills = change.skills ?? skills
        pixie.allowedTools = change.allowedTools ?? allowedTools
        pixie.disallowedTools = change.disallowedTools ?? disallowedTools
        pixie.hidden = change.hidden ?? hidden
        return pixie
    }
}

/// A pixie file's text and the hash a later write must name.
public struct PixieFile: Codable, Sendable, Hashable {
    public var text: String
    public var hash: String

    public init(text: String, hash: String) {
        self.text = text
        self.hash = hash
    }
}

/// A line of a pixie's memory that matched a search.
public struct PixieSearchHit: Codable, Sendable, Hashable {
    public var file: String
    public var line: String

    public init(file: String, line: String) {
        self.file = file
        self.line = line
    }
}
