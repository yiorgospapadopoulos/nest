import Foundation
import Observation

/// One configuration file in the editor sheet (B97). Saving names the version it read, so
/// a change made on disk meanwhile, in VS Code or a terminal, is never overwritten without
/// the user choosing to: the sheet shows "changed on disk" with Reload and Keep mine.
@MainActor @Observable
public final class ConfigFileEditor: Identifiable {
    public let path: String
    /// Such as "Instructions".
    public let title: String
    /// Such as "used by Claude and Codex".
    public let note: String?
    /// The draft.
    public var text = ""
    public private(set) var loaded = false
    public private(set) var saving = false
    /// The version the draft started from, nil for a file not made yet.
    public private(set) var version: String?
    /// The file as it is on disk now, when it changed after it was read and the draft has
    /// edits of its own.
    public private(set) var onDisk: ConfigFile?
    /// Why the daemon refused the text, such as invalid TOML; shown in the sheet.
    public private(set) var error: String?
    private var original = ""

    let api: any NestAPI

    public nonisolated var id: String { path }

    public init(api: any NestAPI, path: String, title: String, note: String? = nil) {
        self.api = api
        self.path = path
        self.title = title
        self.note = note
    }

    /// Whether the draft differs from what was read.
    public var isDirty: Bool { text != original }

    public func load() async throws {
        adopt(try await api.configurationFile(path: path))
        loaded = true
    }

    /// The file changed somewhere (`configuration.changed`): an untouched draft follows
    /// it; a draft with edits keeps them and shows the bar.
    public func checkDisk() async throws {
        guard loaded, !saving else { return }
        let file = try await api.configurationFile(path: path)
        guard file.version != version, !saving else { return }
        if file.text == text || !isDirty {
            adopt(file)
        } else {
            onDisk = file
        }
    }

    /// Takes the file on disk, dropping the draft's edits.
    public func reload() {
        guard let onDisk else { return }
        adopt(onDisk)
    }

    /// Keeps the draft; the next save replaces what is on disk now.
    public func keepMine() {
        guard let onDisk else { return }
        version = onDisk.version
        self.onDisk = nil
    }

    /// True when saved; false when the file changed on disk first, which shows the bar
    /// (a conflict with or without the current version), or when the daemon refused the
    /// text, which shows its words.
    @discardableResult
    public func save() async throws -> Bool {
        saving = true
        defer { saving = false }
        error = nil
        do {
            let saved = text
            version = try await api.saveConfigurationFile(
                path: path, text: saved, expectedVersion: version)
            original = saved
            onDisk = nil
            return true
        } catch let refusal as APIError where refusal.isConflict {
            onDisk = try await api.configurationFile(path: path)
            return false
        } catch APIError.invalidInput(let detail) {
            error = detail
            return false
        }
    }

    private func adopt(_ file: ConfigFile) {
        text = file.text
        original = file.text
        version = file.version
        onDisk = nil
        error = nil
    }
}
