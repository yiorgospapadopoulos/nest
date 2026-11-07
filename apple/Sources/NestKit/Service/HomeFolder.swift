import Foundation

/// Folders Settings opens, which may not be there yet (B130): macOS ignores opening a missing
/// one without a word. As the Linux app's make_folder_in_home.
public enum HomeFolder {
    public struct Refused: Error, LocalizedError, Equatable {
        public let reason: String
        public var errorDescription: String? { reason }
    }

    /// Makes the folder `path` when it is not there yet, such as the Claude skills folder on a
    /// new Mac, only where its nearest existing parent is in the home folder, links resolved.
    public static func make(_ path: String, home: URL) throws {
        let parts = path.split(separator: "/", omittingEmptySubsequences: true)
        guard path.hasPrefix("/"), !parts.contains(where: { $0 == "." || $0 == ".." }) else {
            throw Refused(reason: "Not a full path: \(path)")
        }
        let manager = FileManager.default
        var isFolder: ObjCBool = false
        if manager.fileExists(atPath: path, isDirectory: &isFolder), isFolder.boolValue {
            return
        }
        var existing = URL(filePath: path, directoryHint: .isDirectory)
        while !manager.fileExists(atPath: existing.path), existing.path != "/" {
            existing.deleteLastPathComponent()
        }
        let resolved = existing.resolvingSymlinksInPath().standardizedFileURL.path
        let inside = home.resolvingSymlinksInPath().standardizedFileURL.path
        guard resolved == inside || resolved.hasPrefix(inside + "/") else {
            throw Refused(reason: "Only places in your home folder open from Nest: \(path)")
        }
        do {
            try manager.createDirectory(atPath: path, withIntermediateDirectories: true)
        } catch {
            throw Refused(reason: "Cannot make \(path): \(error.localizedDescription)")
        }
    }
}
