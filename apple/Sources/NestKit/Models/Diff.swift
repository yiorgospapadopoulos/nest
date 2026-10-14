import Foundation

/// A session's work against its base, untracked files included, with what Approve
/// publishes it on.
public struct SessionDiff: Decodable, Sendable, Hashable {
    /// The commit the work is compared with; nil when the repository had no commits.
    public var base: String?
    /// HEAD as the review was read; Approve sends its commit back and is refused if it
    /// moved.
    /// Nil from daemons before B32.
    public var head: ReviewHead?
    /// Commits on HEAD that neither the base nor Nest's own publishing accounts for;
    /// Approve publishes them too.
    public var commits: [ReviewCommit]
    public var files: [FileDiff]
    public var stats: DiffStats
    /// A hash of HEAD, the commits and every file shown; Approve sends it back and is
    /// refused when the changes differ from this review. Nil from daemons before B34.
    public var fingerprint: String?

    public static let foreignCommitsWarning =
        "These commits are on the branch, but Nest did not make them. Check them before publishing."

    /// "Pushes to <branch>"; nil when HEAD names no branch.
    public var pushTarget: String? {
        head?.branch.map { "Pushes to \($0)" }
    }

    enum CodingKeys: String, CodingKey {
        case base, head, commits, files, stats, fingerprint
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        base = try container.decodeIfPresent(String.self, forKey: .base)
        head = try container.decodeIfPresent(ReviewHead.self, forKey: .head)
        commits = try container.decodeIfPresent([ReviewCommit].self, forKey: .commits) ?? []
        files = try container.decode([FileDiff].self, forKey: .files)
        stats = try container.decode(DiffStats.self, forKey: .stats)
        fingerprint = try container.decodeIfPresent(String.self, forKey: .fingerprint)
    }
}

/// HEAD's commit and the branch it names, each nil when there is none.
public struct ReviewHead: Decodable, Sendable, Hashable {
    public var commit: String?
    public var branch: String?

    public init(commit: String?, branch: String?) {
        self.commit = commit
        self.branch = branch
    }
}

/// A commit Approve would publish that Nest did not make.
public struct ReviewCommit: Decodable, Sendable, Hashable, Identifiable {
    public var sha: String
    public var subject: String

    public init(sha: String, subject: String) {
        self.sha = sha
        self.subject = subject
    }

    public var id: String { sha }
    public var shortSHA: String { String(sha.prefix(7)) }
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
    /// Sent by daemons from B32 on; read through `isNestedRepository`.
    var nested: Bool?

    public var id: String { path }

    /// A git repository inside the work, which Nest does not commit; Approve is
    /// refused while one is among the changes.
    public var isNestedRepository: Bool { nested ?? false }

    public static let nestedRepositoryNote = "Nested repository, not committed"

    enum CodingKeys: String, CodingKey {
        case path, status, additions, deletions, binary, truncated, hunks
        case oldPath = "old_path"
        case nested = "nested_repository"
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
