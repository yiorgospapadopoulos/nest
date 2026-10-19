import Foundation

/// What an artifact's page stored (B88): string keys to string values, shared by all its
/// versions and the user's devices, kept until the artifact is deleted. `size` is what
/// counts toward the caps.
public struct ArtifactStorage: Decodable, Sendable, Hashable {
    public let items: [String: String]
    public let size: Int

    public init(items: [String: String], size: Int) {
        self.items = items
        self.size = size
    }
}

/// A change to a page's storage: keys set and removed together, or everything cleared.
public enum ArtifactStorageChange: Sendable, Hashable {
    case write(set: [String: String], remove: [String])
    case clear
}

/// `artifact.storage`: an artifact's storage changed, on any device or from a reader.
public struct ArtifactStorageEvent: Decodable, Sendable, Hashable {
    public let artifactID: String
    public let change: ArtifactStorageChange

    public init(artifactID: String, change: ArtifactStorageChange) {
        self.artifactID = artifactID
        self.change = change
    }

    enum CodingKeys: String, CodingKey {
        case set, remove, clear
        case artifactID = "artifact_id"
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        artifactID = try container.decode(String.self, forKey: .artifactID)
        if try container.decodeIfPresent(Bool.self, forKey: .clear) == true {
            change = .clear
        } else {
            change = .write(
                set: try container.decodeIfPresent([String: String].self, forKey: .set) ?? [:],
                remove: try container.decodeIfPresent([String].self, forKey: .remove) ?? [])
        }
    }
}

/// `POST /api/artifacts/{id}/storage`.
struct ArtifactStorageWrite: Encodable {
    let set: [String: String]
    let remove: [String]
}

/// The storage's size after a write.
struct ArtifactStorageSize: Decodable {
    let size: Int
}

/// One of a multi-file page's own files, beside its main content (B88).
public struct ArtifactFileInfo: Decodable, Sendable, Hashable {
    public let path: String
    public let size: Int
    public let mime: String

    public init(path: String, size: Int, mime: String) {
        self.path = path
        self.size = size
        self.mime = mime
    }
}
