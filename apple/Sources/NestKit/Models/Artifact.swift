import Foundation

/// What an artifact holds, fixed when it is made (B79). Slides and documents are Markdown,
/// designs and design systems JSON, each shown in a page the daemon builds (B88).
public enum ArtifactKind: String, UnknownSafeEnum {
    case markdown, html, slides, document, design
    case designSystem = "design_system"
    case unknown
}

/// Who saved a version: the agent, or the user editing a document in place (B88).
public enum ArtifactAuthor: String, UnknownSafeEnum {
    case agent, user
    case unknown
}

/// A titled document a chat's agent saved, as the daemon lists it (B79). It belongs to
/// the chat that saved it and, from a pixie's chat or habit run, to that pixie; it
/// outlives both.
public struct Artifact: Decodable, Sendable, Hashable, Identifiable {
    public let id: String
    /// The latest version's title.
    public var title: String
    public let kind: ArtifactKind
    /// The saving chat's project, or `pixie:<id>` for a pixie's chat or habit run.
    public let repo: String
    public let sessionID: String?
    /// The chat's current title, or its last one once deleted.
    public var chatTitle: String?
    public var chatDeleted: Bool
    public let pixieID: String?
    public var pixieName: String?
    public let createdAt: Date
    /// When the latest version was saved; lists sort by it.
    public var updatedAt: Date
    public var latestVersion: Int
    public var versionCount: Int
    /// The user opened its latest version.
    public var seen: Bool

    public init(
        id: String, title: String, kind: ArtifactKind, repo: String, sessionID: String?,
        chatTitle: String?, chatDeleted: Bool = false, pixieID: String? = nil,
        pixieName: String? = nil, createdAt: Date, updatedAt: Date, latestVersion: Int,
        seen: Bool
    ) {
        self.id = id
        self.title = title
        self.kind = kind
        self.repo = repo
        self.sessionID = sessionID
        self.chatTitle = chatTitle
        self.chatDeleted = chatDeleted
        self.pixieID = pixieID
        self.pixieName = pixieName
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.latestVersion = latestVersion
        versionCount = latestVersion
        self.seen = seen
    }

    enum CodingKeys: String, CodingKey {
        case id, title, kind, repo, seen
        case sessionID = "session_id"
        case chatTitle = "chat_title"
        case chatDeleted = "chat_deleted"
        case pixieID = "pixie_id"
        case pixieName = "pixie_name"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case latestVersion = "latest_version"
        case versionCount = "version_count"
    }
}

/// One saved version of an artifact, without its content.
public struct ArtifactVersion: Decodable, Sendable, Hashable {
    public let version: Int
    public let title: String
    /// Bytes of UTF-8 content.
    public let size: Int
    public let createdAt: Date
    public let author: ArtifactAuthor

    public init(
        version: Int, title: String, size: Int, createdAt: Date, author: ArtifactAuthor = .agent
    ) {
        self.version = version
        self.title = title
        self.size = size
        self.createdAt = createdAt
        self.author = author
    }

    enum CodingKeys: String, CodingKey {
        case version, title, size, author
        case createdAt = "created_at"
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        version = try container.decode(Int.self, forKey: .version)
        title = try container.decode(String.self, forKey: .title)
        size = try container.decode(Int.self, forKey: .size)
        createdAt = try container.decode(Date.self, forKey: .createdAt)
        author = try container.decodeIfPresent(ArtifactAuthor.self, forKey: .author) ?? .agent
    }
}

/// `POST /api/artifacts/{id}/versions`: the user's edit of a document, made from
/// `baseVersion`, which must still be the latest.
struct SaveArtifactVersionRequest: Encodable {
    let content: String
    let baseVersion: Int

    enum CodingKeys: String, CodingKey {
        case content
        case baseVersion = "base_version"
    }
}

/// An artifact with its versions, oldest first.
public struct ArtifactDetail: Decodable, Sendable, Hashable {
    public let artifact: Artifact
    public let versions: [ArtifactVersion]

    enum CodingKeys: String, CodingKey {
        case versions
    }

    public init(from decoder: any Decoder) throws {
        artifact = try Artifact(from: decoder)
        versions = try decoder.container(keyedBy: CodingKeys.self)
            .decode([ArtifactVersion].self, forKey: .versions)
    }
}

/// A version's whole document.
public struct ArtifactContent: Decodable, Sendable, Hashable {
    public let artifactID: String
    public let version: Int
    public let kind: ArtifactKind
    public let title: String
    public let content: String
    /// The whole document the reader shows in its sandbox, built by the daemon: the HTML
    /// as saved, or a page that renders the Markdown (B82).
    public let page: String
    public let size: Int
    public let createdAt: Date
    public let author: ArtifactAuthor
    /// A multi-file html page's other files, already built into `page` (B88).
    public let files: [ArtifactFileInfo]

    public init(
        artifactID: String, version: Int, kind: ArtifactKind, title: String, content: String,
        page: String, createdAt: Date, author: ArtifactAuthor = .agent,
        files: [ArtifactFileInfo] = []
    ) {
        self.artifactID = artifactID
        self.version = version
        self.kind = kind
        self.title = title
        self.content = content
        self.page = page
        size = content.utf8.count
        self.createdAt = createdAt
        self.author = author
        self.files = files
    }

    enum CodingKeys: String, CodingKey {
        case version, kind, title, content, page, size, author, files
        case artifactID = "artifact_id"
        case createdAt = "created_at"
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        artifactID = try container.decode(String.self, forKey: .artifactID)
        version = try container.decode(Int.self, forKey: .version)
        kind = try container.decode(ArtifactKind.self, forKey: .kind)
        title = try container.decode(String.self, forKey: .title)
        content = try container.decode(String.self, forKey: .content)
        page = try container.decode(String.self, forKey: .page)
        size = try container.decode(Int.self, forKey: .size)
        createdAt = try container.decode(Date.self, forKey: .createdAt)
        author = try container.decodeIfPresent(ArtifactAuthor.self, forKey: .author) ?? .agent
        files = try container.decodeIfPresent([ArtifactFileInfo].self, forKey: .files) ?? []
    }
}

/// `session.artifact`: the chat saved an artifact, a card in its transcript.
public struct ArtifactCard: Decodable, Sendable, Hashable {
    public enum Action: String, UnknownSafeEnum {
        /// `edited` is the user's own save of a document (B88).
        case created, updated, edited
        case unknown
    }

    public let artifactID: String
    public let version: Int
    public let title: String
    public let kind: ArtifactKind
    public let action: Action

    enum CodingKeys: String, CodingKey {
        case version, title, kind, action
        case artifactID = "artifact_id"
    }
}

/// `artifact.saved`: a version was saved somewhere; `unseen` is the new badge count.
public struct ArtifactSaved: Decodable, Sendable, Hashable {
    public let artifact: Artifact
    public let action: ArtifactCard.Action
    public let version: Int
    public let unseen: Int
}

/// `GET /api/artifacts/unseen`.
struct UnseenArtifacts: Decodable {
    let unseen: Int
}
