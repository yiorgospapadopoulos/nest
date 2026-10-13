import Foundation
import UniformTypeIdentifiers

/// Reads a file to attach, away from the main actor, refusing one the daemon would
/// refuse before reading it.
public enum AttachmentFile {
    /// The daemon's limit (`MAX_ATTACHMENT_BYTES`).
    public static let maximumSize = 20 * 1024 * 1024

    /// A link is read as the file it points to. Only regular files are read, and never
    /// more than one byte past the limit, whatever size they claim.
    @concurrent
    public static func read(_ url: URL) async throws -> Data {
        let file = url.resolvingSymlinksInPath()
        let values = try file.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
        guard values.isRegularFile == true else { throw AttachmentFileError.notAFile }
        if let size = values.fileSize, size > maximumSize {
            throw AttachmentFileError.tooLarge
        }
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        // Nothing to read from an empty file.
        guard let data = try handle.read(upToCount: maximumSize + 1) else { return Data() }
        guard data.count <= maximumSize else { throw AttachmentFileError.tooLarge }
        return data
    }

    /// Reads the file and uploads it, typed by its extension.
    public static func upload(_ url: URL, with api: any HarnessAPI) async throws -> Attachment {
        let data = try await read(url)
        let type = UTType(filenameExtension: url.pathExtension)?.preferredMIMEType
        return try await api.uploadAttachment(
            filename: url.lastPathComponent, mediaType: type ?? "application/octet-stream",
            data: data)
    }
}

public enum AttachmentFileError: LocalizedError, Equatable {
    case tooLarge
    case notAFile

    public var errorDescription: String? {
        switch self {
        // The daemon's own words for it.
        case .tooLarge: "attachments larger than 20 MB are not accepted"
        case .notAFile: "only files can be attached, not folders or packages"
        }
    }
}
