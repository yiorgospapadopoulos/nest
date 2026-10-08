import CoreGraphics
import Foundation
import Observation

public enum ConnectionState: Sendable, Equatable {
    case disconnected
    case connecting
    case connected
    case reconnecting(attempt: Int, delay: Double)
    /// The daemon rejected the device token.
    case unauthorized
    /// The daemon refused the connection's origin.
    case forbiddenOrigin
}

/// The right panel's cards.
public enum RightCard: String, Sendable, CaseIterable {
    case agents, needsYou, goals
}

public enum ProjectView: String, Sendable {
    case workspace, board
}

/// What a project tab remembers: its workspace and how its panels are arranged.
public struct ProjectState: Sendable, Hashable {
    public var layout = WorkspaceLayout()
    public var leftCollapsed = false
    public var rightCollapsed = false
    /// The right panel's open cards; they share its height equally.
    public var openCards = Set(RightCard.allCases)
    public var view = ProjectView.workspace
    /// The chat highlighted in the sidebar.
    public var selectedChat: String?
    /// Chats whose Goals entry is expanded.
    public var expandedGoals: Set<String> = []
    /// Agents whose recent steps are shown, by agent id.
    public var expandedAgents: Set<String> = []
    /// Chats whose background bar is open to its lists.
    public var expandedBackground: Set<String> = []
    /// The terminal and browser panes in the workspace, by pane id.
    public private(set) var tools: [String: ToolPane] = [:]

    public init() {}

    /// Opens a chat by click; the workspace view comes back if the board was showing.
    @discardableResult
    public mutating func openChat(_ id: String, in size: CGSize) -> OpenOutcome {
        view = .workspace
        selectedChat = id
        defer { pruneTools() }
        return layout.open(id, in: size)
    }

    public mutating func dropChat(_ id: String, onto target: String?, side: DropSide) {
        view = .workspace
        if layout.drop(id, onto: target, side: side) != nil {
            selectedChat = id
        }
        pruneTools()
    }

    /// Shows `new` in place of `old`'s pane, as when a draft becomes a chat or a Claude
    /// Code chat continues in harness; it stays selected.
    public mutating func replaceChat(_ old: String, with new: String) {
        layout.replace(old, with: new)
        selectedChat = new
        pruneTools()
    }

    public mutating func closePane(_ id: String) {
        layout.remove(id)
        if selectedChat == id {
            selectedChat = layout.focused
        }
        pruneTools()
    }

    // MARK: Terminal and browser panes

    /// Opens a terminal or browser pane by the same rules as a chat.
    public mutating func openTool(_ pane: ToolPane, in size: CGSize) {
        view = .workspace
        tools[pane.id] = pane
        layout.open(pane.id, in: size)
        pruneTools()
    }

    /// The terminal pane for `folder`, focused: an open one, or a new one. `opened` tells
    /// whether its shell is new.
    @discardableResult
    public mutating func terminal(for folder: String, in size: CGSize) -> (
        pane: ToolPane, opened: Bool
    ) {
        let folder = ToolPane.normalized(folder)
        let open = layout.leaves.compactMap { tools[$0] }
        if let pane = open.first(where: { $0.kind == .terminal && $0.folder == folder }) {
            view = .workspace
            layout.open(pane.id, in: size)
            return (pane, false)
        }
        let pane = ToolPane.terminal(in: folder)
        openTool(pane, in: size)
        return (pane, true)
    }

    /// Remembers the page a browser pane shows.
    public mutating func setURL(_ url: String, of pane: String) {
        tools[pane]?.url = url
    }

    /// Terminal and browser panes in reading order, as they are saved.
    public var openTools: [ToolPane] {
        layout.leaves.compactMap { tools[$0] }
    }

    /// A pane that left the workspace (closed, or replaced by a chat) is forgotten.
    private mutating func pruneTools() {
        tools = tools.filter { layout.contains($0.key) }
    }

    public mutating func focusPane(_ id: String) {
        layout.focus(id)
        selectedChat = layout.focused
    }

    public mutating func toggleCard(_ card: RightCard) {
        if openCards.remove(card) == nil {
            openCards.insert(card)
        }
    }

    /// A rail button: unfolds the panel with that card open.
    public mutating func showCard(_ card: RightCard) {
        rightCollapsed = false
        openCards.insert(card)
    }

    /// Opens or closes a chat's background bar.
    public mutating func toggleBackground(_ chat: String) {
        if expandedBackground.remove(chat) == nil {
            expandedBackground.insert(chat)
        }
    }

    /// Forgets a chat that was deleted.
    public mutating func forget(_ id: String) {
        closePane(id)
        expandedGoals.remove(id)
        expandedBackground.remove(id)
    }
}

/// Projects (registered repos) as tabs, each with its own workspace state, and the
/// connection to the daemon.
@MainActor @Observable
public final class AppStore {
    enum Key {
        static let openProjects = "projects.open"
        static let currentProject = "projects.current"

        static func tools(of project: String) -> String { "projects.tools.\(project)" }
    }

    /// The workspace size saved panes are reopened in, before the window measures it.
    static let restoreSize = CGSize(width: 900, height: 700)

    public var connection = ConnectionState.disconnected
    /// The last error of a background refresh.
    public var syncError: APIError?
    /// The latest repo reload `reloadRepos` started.
    @ObservationIgnored public private(set) var reloadingRepos: Task<Void, Never>?
    public private(set) var repos: [Repo] = []
    /// Open project tabs in order, by repo name.
    public private(set) var openProjects: [String]
    public private(set) var currentProject: String?
    public var projects: [String: ProjectState] = [:]

    let api: any HarnessAPI
    @ObservationIgnored let store: any KeyValueStore

    public init(api: any HarnessAPI, store: any KeyValueStore = UserDefaultsStore()) {
        self.api = api
        self.store = store
        openProjects = (store.string(forKey: Key.openProjects) ?? "")
            .split(separator: "\n").map(String.init)
        currentProject = store.string(forKey: Key.currentProject)
        for project in openProjects {
            restoreTools(of: project)
        }
    }

    /// Loads the repos; tabs of repos that are gone close and their terminal and browser
    /// panes end, and the first repo opens when no tab is open. A closed tab keeps its panes.
    public func loadRepos() async throws {
        repos = try await api.repos()
        let names = Set(repos.map(\.name))
        openProjects.removeAll { !names.contains($0) }
        for name in projects.keys where !names.contains(name) {
            projects[name] = nil
            saveTools([], of: name)
        }
        if openProjects.isEmpty, let first = repos.first {
            openProjects = [first.name]
        }
        if currentProject.map({ !openProjects.contains($0) }) ?? true {
            currentProject = openProjects.first
        }
        save()
    }

    /// Lists the repos again in the background, after the ones started before; a failure
    /// shows as the sync error.
    public func reloadRepos() {
        let previous = reloadingRepos
        reloadingRepos = Task {
            await previous?.value
            do {
                try await loadRepos()
            } catch {
                syncError = error as? APIError ?? .transport(String(describing: error))
            }
        }
    }

    public func repo(_ name: String) -> Repo? {
        repos.first { $0.name == name }
    }

    /// Repos without an open tab, for the add-project popover.
    public var closedRepos: [Repo] {
        repos.filter { !openProjects.contains($0.name) }
    }

    /// Registers a folder as a repo and opens it.
    @discardableResult
    public func addProject(path: String) async throws -> Repo {
        let repo = try await api.registerRepo(path: path, name: nil)
        repos.removeAll { $0.name == repo.name }
        repos.append(repo)
        openProject(repo.name)
        return repo
    }

    public func openProject(_ name: String) {
        if !openProjects.contains(name) {
            openProjects.append(name)
        }
        if projects[name] == nil {
            restoreTools(of: name)
        }
        currentProject = name
        save()
    }

    public func selectProject(_ name: String) {
        guard openProjects.contains(name) else { return }
        currentProject = name
        save()
    }

    /// Closes a tab; the last tab stays open.
    public func closeProject(_ name: String) {
        guard openProjects.count > 1, let index = openProjects.firstIndex(of: name) else { return }
        openProjects.remove(at: index)
        if currentProject == name {
            currentProject = openProjects[max(0, index - 1)]
        }
        save()
    }

    /// The tab at a position (Cmd-1 to Cmd-9); Cmd-9 is always the last tab.
    public func selectProject(at index: Int) {
        guard !openProjects.isEmpty, index >= 0 else { return }
        let name = index >= 8 ? openProjects[openProjects.count - 1] : openProjects[safe: index]
        if let name {
            selectProject(name)
        }
    }

    /// The next (or previous, with a negative step) tab, wrapping around.
    public func selectProject(offset: Int) {
        guard let current = currentProject, let index = openProjects.firstIndex(of: current)
        else { return }
        let count = openProjects.count
        selectProject(openProjects[((index + offset) % count + count) % count])
    }

    /// Opens a project's tab and shows a chat in its workspace, as a notification asks.
    public func reveal(chat: String, in project: String, size: CGSize) {
        guard repo(project) != nil else { return }
        openProject(project)
        update(project) { $0.openChat(chat, in: size) }
    }

    public func moveProject(_ name: String, to index: Int) {
        guard let from = openProjects.firstIndex(of: name) else { return }
        openProjects.remove(at: from)
        openProjects.insert(name, at: min(max(0, index), openProjects.count))
        save()
    }

    public func state(of project: String) -> ProjectState {
        projects[project] ?? ProjectState()
    }

    /// Changes a project's state; the current project's when none is named.
    public func update(_ project: String? = nil, _ change: (inout ProjectState) -> Void) {
        guard let name = project ?? currentProject else { return }
        var state = state(of: name)
        let tools = state.openTools
        change(&state)
        projects[name] = state
        if state.openTools != tools {
            saveTools(state.openTools, of: name)
        }
    }

    /// A deleted chat leaves every workspace.
    public func forgetChat(_ id: String) {
        for name in projects.keys {
            projects[name]?.forget(id)
        }
    }

    public func openProject(_ name: String, in app: RepoApp) async throws {
        try await api.openRepo(name, in: app)
    }

    /// Reopens the terminal and browser panes the project had; unreadable data is ignored.
    private func restoreTools(of project: String) {
        guard let text = store.string(forKey: Key.tools(of: project)),
            let panes = try? JSONDecoder().decode([ToolPane].self, from: Data(text.utf8)),
            !panes.isEmpty
        else { return }
        var state = ProjectState()
        for pane in panes {
            state.openTool(pane, in: Self.restoreSize)
        }
        projects[project] = state
    }

    private func saveTools(_ panes: [ToolPane], of project: String) {
        let data = try? JSONEncoder().encode(panes)
        let text = panes.isEmpty ? nil : data.map { String(decoding: $0, as: UTF8.self) }
        store.set(text, forKey: Key.tools(of: project))
    }

    private func save() {
        store.set(openProjects.joined(separator: "\n"), forKey: Key.openProjects)
        store.set(currentProject, forKey: Key.currentProject)
    }
}

extension Array {
    subscript(safe index: Int) -> Element? {
        indices.contains(index) ? self[index] : nil
    }
}
