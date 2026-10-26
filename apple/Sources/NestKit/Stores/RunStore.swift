import Foundation
import Observation

/// What a folder's run wrote, kept for its output pane: the daemon's last lines, then each
/// `run.output` chunk. `generation` changes whenever the text is replaced or trimmed at the
/// front, so a terminal fed from it starts over instead of appending.
public struct RunOutputBuffer: Sendable, Hashable {
    /// The most text kept, in UTF-8 bytes; older lines go first.
    public static let limit = 400_000

    public private(set) var text: String
    public private(set) var generation: Int

    public init(text: String = "", generation: Int = 0) {
        self.text = text
        self.generation = generation
        trim()
    }

    /// Starts over with the daemon's copy.
    public mutating func replace(with text: String) {
        self.text = text
        generation += 1
        trim()
    }

    public mutating func append(_ chunk: String) {
        text += chunk
        trim()
    }

    /// Past the limit, drops whole lines from the front.
    private mutating func trim() {
        let excess = text.utf8.count - Self.limit
        guard excess > 0 else { return }
        let cut = text.utf8.index(text.utf8.startIndex, offsetBy: excess)
        let rest = text[cut...]
        text = rest.firstIndex(of: "\n").map { String(rest[rest.index(after: $0)...]) } ?? ""
        generation += 1
    }
}

/// The runs of the chats' folders (B108): each chat's status, read when its pane shows and
/// kept by folder, since chats sharing a folder share one run; `run.changed` updates it for
/// every chat in that folder. An output pane reads its folder's output once, then follows
/// `run.output`, and reads it again when a new run starts.
@MainActor @Observable
public final class RunStore {
    /// Statuses by folder.
    public private(set) var statuses: [String: RunStatus] = [:]
    /// Output by folder, for folders an output pane has read.
    public private(set) var outputs: [String: RunOutputBuffer] = [:]
    /// Each chat's folder, as its status told.
    private(set) var folders: [String: String] = [:]

    let api: any NestAPI
    /// The latest output read a new run started.
    @ObservationIgnored private(set) var refreshing: Task<Void, Never>?

    public init(api: any NestAPI) {
        self.api = api
    }

    /// The run of the chat's folder, once read.
    public func status(of session: String) -> RunStatus? {
        folders[session].flatMap { statuses[$0] }
    }

    public func status(ofFolder folder: String) -> RunStatus? {
        statuses[folder]
    }

    public func output(of folder: String) -> RunOutputBuffer? {
        outputs[folder]
    }

    /// Reads the chat's run; a failure keeps what it had.
    public func load(_ session: String) async {
        guard let status = try? await api.runStatus(session) else { return }
        record(status, for: session)
    }

    public func start(_ session: String) async throws {
        record(try await api.startRun(session), for: session)
    }

    public func stop(_ session: String) async throws {
        record(try await api.stopRun(session), for: session)
    }

    public func restart(_ session: String) async throws {
        record(try await api.restartRun(session), for: session)
    }

    /// Reads the folder's output through one of its chats; a failure keeps what it had.
    public func loadOutput(folder: String, session: String) async {
        guard let output = try? await api.runOutput(session) else { return }
        folders[session] = folder
        outputs[folder, default: RunOutputBuffer()].replace(with: output.text)
    }

    /// Reads every known chat's run again, and the output of every folder an output pane
    /// read, as after a reconnect.
    public func reload() async {
        for session in folders.keys.sorted() {
            await load(session)
        }
        for folder in outputs.keys.sorted() {
            if let session = session(in: folder) {
                await loadOutput(folder: folder, session: session)
            }
        }
    }

    public func apply(_ event: Event) {
        switch event.body {
        case .runChanged(let change):
            update(change.status)
        case .runOutput(let folder, let text):
            outputs[folder]?.append(text)
        default:
            break
        }
    }

    private func record(_ status: RunStatus, for session: String) {
        folders[session] = status.folder
        update(status)
    }

    /// A new run (another start time) cleared the daemon's output, so a folder whose
    /// output is shown reads it again.
    private func update(_ status: RunStatus) {
        let folder = status.folder
        let previous = statuses[folder]
        statuses[folder] = status
        guard outputs[folder] != nil, let previous, previous.startedAt != status.startedAt,
            status.startedAt != nil, let session = session(in: folder)
        else { return }
        let before = refreshing
        refreshing = Task {
            await before?.value
            await loadOutput(folder: folder, session: session)
        }
    }

    /// A chat known to work in the folder, the same one each time.
    private func session(in folder: String) -> String? {
        folders.filter { $0.value == folder }.keys.sorted().first
    }
}
