import Foundation

/// The pixie's pixel-art mascot; `MascotSprites` draws it (D057).
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

/// A long-lived assistant with its own soul, memory and chat (D057).
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
