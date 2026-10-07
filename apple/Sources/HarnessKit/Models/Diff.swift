import Foundation

/// A session's work against its base, untracked files included.
public struct SessionDiff: Decodable, Sendable, Hashable {
    /// The commit the work is compared with; nil when the repository had no commits.
    public var base: String?
    public var files: [FileDiff]
    public var stats: DiffStats
}

public struct DiffStats: Decodable, Sendable, Hashable {
    public var files: Int
    public var additions: Int
    public var deletions: Int
}

public enum FileStatus: String, UnknownSafeEnum {
    case added, modified, deleted, renamed
    case unknown
}

public struct FileDiff: Decodable, Sendable, Hashable, Identifiable {
    public var path: String
    /// The previous path of a renamed file.
    public var oldPath: String?
    public var status: FileStatus
    public var additions: Int
    public var deletions: Int
    public var binary: Bool
    /// Lines beyond the daemon's per-file limit are left out; the counts include them.
    public var truncated: Bool
    public var hunks: [Hunk]

    public var id: String { path }

    enum CodingKeys: String, CodingKey {
        case path, status, additions, deletions, binary, truncated, hunks
        case oldPath = "old_path"
    }
}

public struct Hunk: Decodable, Sendable, Hashable {
    public var oldStart: Int
    public var oldLines: Int
    public var newStart: Int
    public var newLines: Int
    /// The text after the @@ range, usually the enclosing function.
    public var header: String
    public var lines: [DiffLine]

    enum CodingKeys: String, CodingKey {
        case header, lines
        case oldStart = "old_start"
        case oldLines = "old_lines"
        case newStart = "new_start"
        case newLines = "new_lines"
    }
}

public enum DiffLineKind: String, UnknownSafeEnum {
    case context, add, delete
    case unknown
}

public struct DiffLine: Decodable, Sendable, Hashable {
    public var kind: DiffLineKind
    public var text: String
    public var oldLine: Int?
    public var newLine: Int?

    enum CodingKeys: String, CodingKey {
        case kind, text
        case oldLine = "old_line"
        case newLine = "new_line"
    }
}
