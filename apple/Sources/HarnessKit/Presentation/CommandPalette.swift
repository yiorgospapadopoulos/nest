import Foundation

/// What choosing a palette entry does.
public enum PaletteAction: Sendable, Hashable {
    case openChat(project: String, chat: String)
    case newChat
    /// A terminal pane in the project folder.
    case newTerminal
    /// An empty browser pane.
    case newBrowser
    case showView(ProjectView)
    case toggleSidebar
    case toggleActivityPanel
    case showUsage
    case openInVSCode
    case goToProject(String)
    /// A search hit: the chat's pane, scrolled to the event when there is one.
    case openMessage(project: String, pane: String, event: Int?)
}

public enum PaletteGroup: String, Sendable, CaseIterable {
    case chats = "Chats"
    case commands = "Commands"
    case projects = "Projects"
    /// Search hits in chat history.
    case messages = "Messages"
}

/// The glyph of a command entry; chats show their status dot instead.
public enum PaletteGlyph: Sendable, Hashable {
    case status(StatusTone, hollow: Bool)
    case newChat, terminal, browser, board, workspace, sidebar, activityPanel, usage, code
    case folder
    case message(SearchHitKind)
}

public struct PaletteItem: Sendable, Hashable, Identifiable {
    public let group: PaletteGroup
    public let title: String
    public let subtitle: String
    public let glyph: PaletteGlyph
    public let action: PaletteAction
    /// A search hit's text, its matches marked.
    public var snippet: [SnippetPart] = []

    /// Each action appears once.
    public var id: PaletteAction { action }
}

/// The Cmd-K palette: chats of every open project, commands and projects, filtered by the
/// query, then the messages the daemon's search found, with a keyboard selection.
public struct CommandPalette: Sendable, Hashable {
    public let items: [PaletteItem]
    public private(set) var query = ""
    /// Index into `visible`.
    public private(set) var selection = 0
    /// Search hits for the query, one per chat and event.
    public private(set) var messages: [PaletteItem] = []
    /// The daemon still indexes the stored history, so hits may be missing.
    public private(set) var indexing = false

    public init(items: [PaletteItem]) {
        self.items = items
    }

    /// Whether the query is long enough to search messages.
    public var searchesMessages: Bool {
        query.trimmingCharacters(in: .whitespacesAndNewlines).count
            >= MessageSearch.minimumLength
    }

    /// Entries whose title or subtitle contain every word of the query, in order, then the
    /// message hits.
    public var visible: [PaletteItem] {
        let words = query.lowercased().split(separator: " ")
        guard !words.isEmpty else { return items }
        return items.filter { item in
            let text = "\(item.title) \(item.subtitle)".lowercased()
            return words.allSatisfy { text.contains($0) }
        } + messages
    }

    public var selected: PaletteItem? {
        let list = visible
        return list.indices.contains(selection) ? list[selection] : nil
    }

    /// A new query selects the first match again; one too short to search drops the hits.
    public mutating func search(_ text: String) {
        query = text
        selection = 0
        if !searchesMessages {
            messages = []
            indexing = false
        }
    }

    /// The daemon's hits for `text`; ignored when the query changed since.
    public mutating func show(_ results: SearchResults, for text: String) {
        guard text == query, searchesMessages else { return }
        var seen = Set<PaletteAction>()
        messages = results.hits.compactMap { hit in
            let item = PaletteItem(
                group: .messages, title: hit.title, subtitle: "\(hit.repo) · \(hit.kind.label)",
                glyph: .message(hit.kind),
                action: .openMessage(project: hit.repo, pane: hit.pane, event: hit.eventID),
                snippet: Snippet.parts(hit.snippet))
            return seen.insert(item.action).inserted ? item : nil
        }
        indexing = results.indexing
        selection = min(selection, max(visible.count - 1, 0))
    }

    /// Arrow keys: moves the selection, wrapping at both ends.
    public mutating func move(by step: Int) {
        let count = visible.count
        guard count > 0 else { return }
        selection = ((selection + step) % count + count) % count
    }

    public mutating func select(_ item: PaletteItem) {
        selection = visible.firstIndex(of: item) ?? selection
    }
}

extension CommandPalette {
    /// The entries for the current window: chats of the open projects, the current
    /// project's commands, then the other open projects.
    @MainActor
    public static func catalog(app: AppStore, sessions: SessionsStore) -> CommandPalette {
        var items: [PaletteItem] = []
        for project in app.openProjects {
            for session in sessions.sessions(in: project) where !session.isArchived {
                let tone = sessions.tone(of: session)
                items.append(
                    PaletteItem(
                        group: .chats, title: session.title,
                        subtitle: "\(project) · \(sessions.statusLabel(of: session))",
                        glyph: .status(tone, hollow: session.state == .idle && tone == .done),
                        action: .openChat(project: project, chat: session.id)))
            }
        }
        if let project = app.currentProject {
            let state = app.state(of: project)
            let offerBoard = state.view == .workspace
            items += [
                PaletteItem(
                    group: .commands, title: "New chat in \(project)", subtitle: "Chat",
                    glyph: .newChat, action: .newChat),
                PaletteItem(
                    group: .commands, title: "New terminal in \(project)", subtitle: "Terminal",
                    glyph: .terminal, action: .newTerminal),
                PaletteItem(
                    group: .commands, title: "New browser", subtitle: "Browser",
                    glyph: .browser, action: .newBrowser),
                PaletteItem(
                    group: .commands,
                    title: offerBoard ? "Show the Board view" : "Show the Workspace view",
                    subtitle: "View", glyph: offerBoard ? .board : .workspace,
                    action: .showView(offerBoard ? .board : .workspace)),
                PaletteItem(
                    group: .commands,
                    title: "\(state.leftCollapsed ? "Expand" : "Collapse") the chat sidebar",
                    subtitle: "Layout", glyph: .sidebar, action: .toggleSidebar),
                PaletteItem(
                    group: .commands,
                    title: "\(state.rightCollapsed ? "Expand" : "Collapse") the activity panel",
                    subtitle: "Layout", glyph: .activityPanel, action: .toggleActivityPanel),
                PaletteItem(
                    group: .commands, title: "Show usage", subtitle: "Usage", glyph: .usage,
                    action: .showUsage),
                PaletteItem(
                    group: .commands, title: "Open \(project) in VS Code", subtitle: "Project",
                    glyph: .code, action: .openInVSCode),
            ]
        }
        for project in app.openProjects where project != app.currentProject {
            let attention = sessions.attention(of: project)
            items.append(
                PaletteItem(
                    group: .projects, title: "Go to \(project)",
                    subtitle: attention > 0 ? "\(attention) need you" : "Project",
                    glyph: .folder, action: .goToProject(project)))
        }
        return CommandPalette(items: items)
    }
}
