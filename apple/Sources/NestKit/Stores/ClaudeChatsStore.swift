import Foundation
import Observation

/// A sidebar row: a Nest session or a Claude Code chat.
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

/// The Mac sidebar's groups (B77): pinned chats, every other chat, and Archived.
public enum SidebarSection: String, Sendable, CaseIterable {
    case pinned, chats, archived

    public var title: String {
        switch self {
        case .pinned: "Pinned"
        case .chats: "Chats"
        case .archived: "Archived"
        }
    }
}

/// A sidebar group with its rows.
public struct SidebarGroup: Sendable, Hashable, Identifiable {
    public let kind: SidebarSection
    public let entries: [SidebarEntry]
    /// Whether the group's title shows: Chats has none unless pinned chats come first.
    public let showsTitle: Bool

    public var id: SidebarSection { kind }

    /// The project's chats in one list, newest activity first whatever their state, with
    /// pinned ones above it and archived ones apart at the end; empty groups are left
    /// out. Claude Code chats are never pinned.
    public static func list(sessions: [Session], chats: [ClaudeChat]) -> [SidebarGroup] {
        let live = sessions.filter { !$0.isArchived }
        let pinned = live.filter(\.pinned).map(SidebarEntry.session)
        let rest =
            live.filter { !$0.pinned }.map(SidebarEntry.session)
            + chats.filter { !$0.archived }.map(SidebarEntry.claudeChat)
        let archived =
            sessions.filter(\.isArchived).map(SidebarEntry.session)
            + chats.filter(\.archived).map(SidebarEntry.claudeChat)
        let groups: [(SidebarSection, [SidebarEntry])] = [
            (.pinned, pinned), (.chats, rest), (.archived, archived),
        ]
        return groups.filter { !$0.1.isEmpty }.map { kind, entries in
            SidebarGroup(
                kind: kind,
                entries: entries.sorted { ($0.lastActivity, $0.id) > ($1.lastActivity, $1.id) },
                showsTitle: kind != .chats || !pinned.isEmpty)
        }
    }
}

/// The Claude Code chats of the registered repos that Nest does not own, listed again
/// whenever the daemon says they changed.
@MainActor @Observable
public final class ClaudeChatsStore {
    public private(set) var chats: [String: ClaudeChat] = [:]

    let api: any NestAPI
    let settings: SettingsStore
    /// The latest refresh an update event started; each waits for the one before it.
    @ObservationIgnored private(set) var refreshing: Task<Void, Never>?

    public init(api: any NestAPI, settings: SettingsStore) {
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

    /// The repo's chats, archived ones included, most recently active first.
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

    /// Continues the chat in Nest. The returned session holds its history; the chat
    /// leaves the list.
    public func adopt(_ id: String) async throws -> Session {
        let session = try await api.adoptClaudeChat(id)
        chats[id] = nil
        return session
    }

    /// Moves the chat to Archived, or back, at once; the daemon's answer replaces it, and
    /// a failure puts the flag back and throws. Nothing is asked when it is already so.
    public func setArchived(_ id: String, _ archived: Bool) async throws {
        guard let chat = chats[id], chat.archived != archived else { return }
        chats[id]?.archived = archived
        do {
            chats[id] = try await api.setClaudeChatArchived(id, archived: archived)
        } catch {
            chats[id]?.archived = chat.archived
            throw error
        }
    }

    public func apply(_ event: Event) {
        guard case .claudeChatsUpdated(let repos) = event.body else { return }
        let previous = refreshing
        refreshing = Task {
            await previous?.value
            // A failure keeps the lists as they are; the next update or connect reads them.
            for repo in repos {
                guard (try? await load(repo: repo)) != nil else { return }
            }
        }
    }
}
