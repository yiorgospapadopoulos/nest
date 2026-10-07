import Foundation
import Observation

/// A sidebar row: a harness session or a Claude Code chat.
public enum SidebarEntry: Sendable, Hashable, Identifiable {
    case session(Session)
    case claudeChat(ClaudeChat)

    /// The id of the pane the entry opens.
    public var id: String {
        switch self {
        case .session(let session): session.id
        case .claudeChat(let chat): chat.paneID
        }
    }

    public var title: String {
        switch self {
        case .session(let session): session.title
        case .claudeChat(let chat): chat.title
        }
    }

    public var lastActivity: Date {
        switch self {
        case .session(let session): session.updatedAt
        case .claudeChat(let chat): chat.lastActivityAt
        }
    }
}

/// A sidebar group with its rows.
public struct SidebarGroup: Sendable, Hashable, Identifiable {
    public let kind: SessionGroupKind
    public let entries: [SidebarEntry]

    public var id: SessionGroupKind { kind }

    /// The sessions' groups with the repo's Claude Code chats added to Idle, where the
    /// rows are sorted by last activity, newest first.
    public static func merge(_ groups: [SessionGroup], chats: [ClaudeChat]) -> [SidebarGroup] {
        var merged = groups.map {
            SidebarGroup(kind: $0.kind, entries: $0.sessions.map(SidebarEntry.session))
        }
        guard !chats.isEmpty else { return merged }
        let order = SessionGroupKind.allCases
        let index =
            merged.firstIndex { $0.kind == .idle }
            ?? merged.firstIndex { order.firstIndex(of: $0.kind)! > order.firstIndex(of: .idle)! }
            ?? merged.count
        let existing = merged.indices.contains(index) && merged[index].kind == .idle
        let entries =
            ((existing ? merged[index].entries : []) + chats.map(SidebarEntry.claudeChat))
            .sorted { ($0.lastActivity, $0.id) > ($1.lastActivity, $1.id) }
        let idle = SidebarGroup(kind: .idle, entries: entries)
        if existing {
            merged[index] = idle
        } else {
            merged.insert(idle, at: index)
        }
        return merged
    }
}

/// The Claude Code chats of the registered repos that harness does not own, listed again
/// whenever the daemon says they changed.
@MainActor @Observable
public final class ClaudeChatsStore {
    public private(set) var chats: [String: ClaudeChat] = [:]
    /// The last refresh after an update event failed with this.
    public private(set) var refreshError: APIError?

    let api: any HarnessAPI
    let settings: SettingsStore
    /// The latest refresh an update event started; each waits for the one before it.
    @ObservationIgnored private(set) var refreshing: Task<Void, Never>?

    public init(api: any HarnessAPI, settings: SettingsStore) {
        self.api = api
        self.settings = settings
    }

    /// Lists every repo's chats; automated ones only when Settings shows them.
    public func load() async throws {
        let list = try await api.claudeChats(
            repo: nil, includeAutomated: settings.showAutomatedChats)
        chats = Dictionary(list.map { ($0.id, $0) }) { first, _ in first }
    }

    /// Lists one repo's chats again.
    public func load(repo: String) async throws {
        let list = try await api.claudeChats(
            repo: repo, includeAutomated: settings.showAutomatedChats)
        chats = chats.filter { $0.value.repo != repo }
        for chat in list {
            chats[chat.id] = chat
        }
    }

    public func chat(_ id: String) -> ClaudeChat? {
        chats[id]
    }

    /// The repo's chats, most recently active first.
    public func chats(in repo: String) -> [ClaudeChat] {
        chats.values.filter { $0.repo == repo }.sorted {
            ($0.lastActivityAt, $0.id) > ($1.lastActivityAt, $1.id)
        }
    }

    /// Shows or hides automated chats and lists again.
    public func setShowAutomated(_ show: Bool) async throws {
        settings.showAutomatedChats = show
        try await load()
    }

    /// Continues the chat in harness. The returned session holds its history; the chat
    /// leaves the list.
    public func adopt(_ id: String) async throws -> Session {
        let session = try await api.adoptClaudeChat(id)
        chats[id] = nil
        return session
    }

    public func apply(_ event: Event) {
        guard case .claudeChatsUpdated(let repos) = event.body else { return }
        let previous = refreshing
        refreshing = Task {
            await previous?.value
            do {
                for repo in repos {
                    try await load(repo: repo)
                }
                refreshError = nil
            } catch {
                refreshError = error as? APIError ?? .transport(String(describing: error))
            }
        }
    }
}
