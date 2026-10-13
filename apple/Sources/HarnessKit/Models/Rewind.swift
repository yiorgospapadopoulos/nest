import Foundation

/// `GET /api/sessions/{id}/rewind?message=`: what restoring the files to before a user
/// message would change, from Claude Code's file checkpoints (IMP-02).
public struct RewindPreview: Decodable, Sendable, Hashable {
    public var canRewind: Bool
    /// The files that would change, when the daemon lists them.
    public var files: [String]
    public var filesChanged: Int
    public var insertions: Int
    public var deletions: Int
    /// Why the files cannot be restored, when they cannot.
    public var error: String?

    public init(
        canRewind: Bool, files: [String] = [], filesChanged: Int? = nil, insertions: Int = 0,
        deletions: Int = 0, error: String? = nil
    ) {
        self.canRewind = canRewind
        self.files = files
        self.filesChanged = filesChanged ?? files.count
        self.insertions = insertions
        self.deletions = deletions
        self.error = error
    }

    enum CodingKeys: String, CodingKey {
        case insertions, deletions, error
        case canRewind = "can_rewind"
        case filesChanged = "files_changed"
    }

    /// `files_changed` is Claude Code's list of paths, or a count.
    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        canRewind = try container.decode(Bool.self, forKey: .canRewind)
        if let paths = try? container.decodeIfPresent([String].self, forKey: .filesChanged) {
            files = paths
            filesChanged = paths.count
        } else {
            files = []
            filesChanged = try container.decodeIfPresent(Int.self, forKey: .filesChanged) ?? 0
        }
        insertions = try container.decodeIfPresent(Int.self, forKey: .insertions) ?? 0
        deletions = try container.decodeIfPresent(Int.self, forKey: .deletions) ?? 0
        error = try container.decodeIfPresent(String.self, forKey: .error)
    }

    /// "2 files change: +12 -4", or that nothing changed since the message.
    public var summary: String {
        guard filesChanged > 0 else { return "No files changed since this message." }
        let noun = filesChanged == 1 ? "1 file changes" : "\(filesChanged) files change"
        return "\(noun): +\(insertions) -\(deletions)"
    }
}

/// "Restore files to before this message": the preview, then the restore (IMP-02). Only
/// the files go back; the conversation stays as it is.
@MainActor @Observable
public final class RewindFlow {
    /// What the confirmation says about the conversation.
    public static let scope =
        "Only files are restored. The conversation stays as it is, and Claude is not told."

    public let session: String
    /// The user message's event id.
    public let message: Int
    public private(set) var preview: RewindPreview?
    /// Why the preview or the restore failed.
    public private(set) var failure: String?
    public private(set) var isRestoring = false

    let api: any HarnessAPI

    public init(session: String, message: Int, api: any HarnessAPI) {
        self.session = session
        self.message = message
        self.api = api
    }

    /// The daemon restores files only while the chat is idle.
    public static func isAvailable(for session: Session?) -> Bool {
        session.map { $0.state == .idle && !$0.isArchived } ?? false
    }

    public var isLoading: Bool { preview == nil && failure == nil }

    /// The preview says the files can go back, and no restore runs.
    public var canRestore: Bool { preview?.canRewind == true && !isRestoring }

    public func load() async {
        do {
            let preview = try await api.rewindPreview(session, message: message)
            self.preview = preview
            failure =
                preview.canRewind
                ? nil : preview.error ?? "The files cannot be restored to before this message."
        } catch {
            failure = Self.describe(error)
        }
    }

    /// Restores the files; whether it worked (`failure` says why not).
    @discardableResult
    public func restore() async -> Bool {
        guard canRestore else { return false }
        isRestoring = true
        defer { isRestoring = false }
        do {
            try await api.rewind(session, message: message)
            failure = nil
            return true
        } catch {
            failure = Self.describe(error)
            return false
        }
    }

    private static func describe(_ error: any Error) -> String {
        (error as? APIError)?.message ?? error.localizedDescription
    }
}
