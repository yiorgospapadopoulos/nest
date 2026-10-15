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
        return try readCapped(file)
    }

    /// Reads at most one byte past the limit and refuses the file then: it may have grown
    /// since its size was checked.
    static func readCapped(_ file: URL) throws -> Data {
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        // Nothing to read from an empty file.
        guard let data = try handle.read(upToCount: maximumSize + 1) else { return Data() }
        guard data.count <= maximumSize else { throw AttachmentFileError.tooLarge }
        return data
    }

    /// Reads the file and prepares it: an image as Claude Code sends it, with a thumbnail
    /// (`ImageAttachment`); anything else as it is, typed by its extension.
    @concurrent
    public static func prepare(_ url: URL) async throws -> PreparedAttachment {
        let data = try await read(url)
        return prepared(data, filename: url.lastPathComponent)
    }

    /// Prepares pasted or dropped data as `prepare(_:)` does a file, within the same limit.
    @concurrent
    public static func prepare(data: Data, filename: String) async throws -> PreparedAttachment {
        guard data.count <= maximumSize else { throw AttachmentFileError.tooLarge }
        return prepared(data, filename: filename)
    }

    private static func prepared(_ data: Data, filename: String) -> PreparedAttachment {
        if var image = ImageAttachment.prepare(data, filename: filename) {
            image.thumbnail = ImageAttachment.thumbnail(image.data)
            return image
        }
        let type = UTType(filenameExtension: (filename as NSString).pathExtension)
        return PreparedAttachment(
            data: data, filename: filename,
            mediaType: type?.preferredMIMEType ?? "application/octet-stream", thumbnail: nil)
    }

    public static func upload(_ prepared: PreparedAttachment, with api: any NestAPI)
        async throws -> Attachment
    {
        try await api.uploadAttachment(
            filename: prepared.filename, mediaType: prepared.mediaType, data: prepared.data)
    }

    /// Reads, prepares and uploads the file.
    public static func upload(_ url: URL, with api: any NestAPI) async throws -> Attachment {
        try await upload(prepare(url), with: api)
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
