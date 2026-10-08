import Foundation

/// Reads a file to attach, away from the main actor, refusing one the daemon would
/// refuse before reading it.
public enum AttachmentFile {
    /// The daemon's limit (`MAX_ATTACHMENT_BYTES`).
    public static let maximumSize = 20 * 1024 * 1024

    @concurrent
    public static func read(_ url: URL) async throws -> Data {
        let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size <= maximumSize else { throw AttachmentFileError.tooLarge }
        return try Data(contentsOf: url)
    }
}

public enum AttachmentFileError: LocalizedError, Equatable {
    case tooLarge

    /// The daemon's own words for it.
    public var errorDescription: String? {
        "attachments larger than 20 MB are not accepted"
    }
}
