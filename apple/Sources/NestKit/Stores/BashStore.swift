import Foundation
import Observation

/// The `!` commands run in each chat since its last sent message (B59). They live in this
/// app only, like a draft; the next message tells Claude about them, then the sent
/// message shows them instead.
@MainActor @Observable
public final class BashStore {
    public struct Row: Sendable, Hashable, Identifiable {
        public let id: String
        public let command: String
        public var run: ShellRun?
        /// Why the command could not run.
        public var failure: String?

        public var isRunning: Bool { run == nil && failure == nil }
    }

    private var rows: [String: [Row]] = [:]
    private var count = 0

    let api: any NestAPI

    public init(api: any NestAPI) {
        self.api = api
    }

    /// The chat's commands, oldest first.
    public func rows(chat: String) -> [Row] {
        rows[chat] ?? []
    }

    /// Runs a command in the chat's folder; its row shows at once and fills in.
    public func run(_ command: String, chat: String) async {
        count += 1
        let id = "bash-\(count)"
        rows[chat, default: []].append(Row(id: id, command: command))
        let result: Result<ShellRun, any Error>
        do {
            result = .success(try await api.runShell(chat, command: command))
        } catch {
            result = .failure(error)
        }
        guard let index = rows[chat]?.firstIndex(where: { $0.id == id }) else { return }
        switch result {
        case .success(let run):
            rows[chat]?[index].run = run
        case .failure(let error):
            rows[chat]?[index].failure =
                (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    /// The message to send, the finished commands' contexts first, and the rows it
    /// accounts for (`sent` removes them once it went).
    public func outgoing(_ text: String, chat: String) -> (text: String, rows: [String]) {
        let done = rows(chat: chat).filter { !$0.isRunning }
        let contexts = done.compactMap(\.run?.context)
        return (BashBlocks.message(text, contexts: contexts), done.map(\.id))
    }

    public func sent(_ ids: [String], chat: String) {
        rows[chat]?.removeAll { ids.contains($0.id) }
    }
}

/// Images of tool results, read once each with the device token (B59).
@MainActor @Observable
public final class AttachmentImages {
    private var loaded: [String: Data] = [:]
    private var failures: Set<String> = []
    @ObservationIgnored private var requested: Set<String> = []

    let api: any NestAPI

    public init(api: any NestAPI) {
        self.api = api
    }

    public func data(for id: String) -> Data? {
        loaded[id]
    }

    public func failed(_ id: String) -> Bool {
        failures.contains(id)
    }

    public func load(_ id: String) async {
        guard !requested.contains(id) else { return }
        requested.insert(id)
        do {
            loaded[id] = try await api.attachmentData(id)
        } catch {
            failures.insert(id)
        }
    }
}
