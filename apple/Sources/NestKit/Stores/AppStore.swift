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
    case needsYou, goals
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
    /// Code chat continues in Nest; it stays selected.
    public mutating func replaceChat(_ old: String, with new: String) {
        layout.replace(old, with: new)
        selectedChat = new
        pruneTools()
    }

    /// A new chat's first message went: its draft's pane shows the chat, or, for the
    /// empty workspace's composer, which has no pane, the chat opens in one.
    public mutating func startChat(fromDraft draft: String, as chat: String, in size: CGSize) {
        if layout.contains(draft) {
            replaceChat(draft, with: chat)
        } else {
            openChat(chat, in: size)
        }
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

    /// The bottom bar's Terminal button: the project's open terminal pane, whatever
    /// folder it runs in, focused; else a new one in `folder`. `opened` tells whether its
    /// shell is new.
    @discardableResult
    public mutating func projectTerminal(folder: String, in size: CGSize) -> (
        pane: ToolPane, opened: Bool
    ) {
        if let pane = openTools.first(where: { $0.kind == .terminal }) {
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

        static let pixiePanes = "pixies.panes"
        static let foldedTeams = "pixies.foldedTeams"

        static func tools(of project: String) -> String { "projects.tools.\(project)" }
    }

    /// The workspace size saved panes are reopened in, before the window measures it.
    static let restoreSize = CGSize(width: 900, height: 700)

    public var connection = ConnectionState.disconnected
    /// The last error of a background refresh.
    public var syncError: APIError?
    /// The latest repo reload `reloadRepos` started.
    @ObservationIgnored public private(set) var reloadingRepos: Task<Void, Never>?
    /// The latest project order save `moveProject` started; saves run one at a time.
    @ObservationIgnored public private(set) var savingOrder: Task<Void, Never>?
    public private(set) var repos: [Repo] = []
    /// The latest settings save of each project, which the next one waits for.
    private var settingSaves: [String: Task<Repo?, any Error>] = [:]
    /// Open project tabs by repo name, in the repos' shared order (D090) once they load.
    public private(set) var openProjects: [String]
    public private(set) var currentProject: String?
    public var projects: [String: ProjectState] = [:]
    /// The Pixies tab's workspace (B37): its panes are pixies, by pixie id, each showing
    /// the pixie's one ongoing chat. It is kept apart from the projects', so repo reloads,
    /// `openPanes` and `forgetChat` never touch it; its open pixies are saved in reading
    /// order and reopen at launch, as a project's terminal and browser panes do.
    public private(set) var pixieState = ProjectState()
    /// The teams folded in the Pixies list, by id; remembered on this Mac only (B40).
    public private(set) var foldedTeams: Set<String> = []

    let api: any NestAPI
    @ObservationIgnored let store: any KeyValueStore

    public init(api: any NestAPI, store: any KeyValueStore = UserDefaultsStore()) {
        self.api = api
        self.store = store
        openProjects = (store.string(forKey: Key.openProjects) ?? "")
            .split(separator: "\n").map(String.init)
        currentProject = store.string(forKey: Key.currentProject)
        for project in openProjects {
            restoreTools(of: project)
        }
        let pixies = store.string(forKey: Key.pixiePanes)?.split(separator: "\n") ?? []
        for pixie in pixies {
            pixieState.openChat(String(pixie), in: Self.restoreSize)
        }
        foldedTeams = Set(
            store.string(forKey: Key.foldedTeams)?.split(separator: "\n").map(String.init) ?? [])
    }

    /// Loads the repos; tabs of repos that are gone close and their terminal and browser
    /// panes end, and the first repo opens when no tab is open. A closed tab keeps its panes.
    public func loadRepos() async throws {
        show(try await api.repos())
    }

    private func show(_ repos: [Repo]) {
        self.repos = repos
        let names = Set(repos.map(\.name))
        openProjects.removeAll { !names.contains($0) }
        for name in projects.keys where !names.contains(name) {
            projects[name] = nil
            saveTools([], of: name)
        }
        if openProjects.isEmpty, let first = repos.first {
            openProjects = [first.name]
        }
        sortOpenProjects()
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
            sortOpenProjects()
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

    /// Moves a tab to `index` among the open tabs and saves the new project order for every
    /// device (D090): the project goes just before the open tab that now follows it, or
    /// just after the one before it when it becomes last. Shown at once; when the save
    /// fails the sync error is set and the repos load again.
    public func moveProject(_ name: String, to index: Int) {
        guard let from = openProjects.firstIndex(of: name) else { return }
        let target = min(max(index, 0), openProjects.count - 1)
        guard target != from else { return }
        var tabs = openProjects
        tabs.remove(at: from)
        tabs.insert(name, at: target)
        var order = repos.map(\.name)
        order.removeAll { $0 == name }
        let (neighbour, offset) =
            target + 1 < tabs.count ? (tabs[target + 1], 0) : (tabs[target - 1], 1)
        // Before the repos load there is no order to place it in.
        guard let at = order.firstIndex(of: neighbour) else { return }
        order.insert(name, at: at + offset)
        repos = order.compactMap(repo)
        openProjects = tabs
        save()
        let previous = savingOrder
        savingOrder = Task {
            await previous?.value
            do {
                _ = try await api.reorderRepos(order)
            } catch {
                syncError = error as? APIError ?? .transport(String(describing: error))
                reloadRepos()
            }
        }
    }

    /// Sorts the open tabs by the repos' order; tabs of repos not loaded yet keep theirs.
    private func sortOpenProjects() {
        let rank = { (name: String) in self.repos.firstIndex { $0.name == name } ?? Int.max }
        openProjects = openProjects.enumerated()
            .sorted { (rank($0.element), $0.offset) < (rank($1.element), $1.offset) }
            .map(\.element)
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

    /// The panes every project's workspace shows, open tabs or not.
    public var openPanes: Set<String> {
        Set(projects.values.flatMap(\.layout.leaves))
    }

    /// A deleted chat leaves every workspace.
    public func forgetChat(_ id: String) {
        for name in projects.keys {
            projects[name]?.forget(id)
        }
    }

    // MARK: Pixies tab

    /// Changes the Pixies tab's workspace; the open pixies are saved when they change.
    public func updatePixies(_ change: (inout ProjectState) -> Void) {
        let open = pixieState.layout.leaves
        change(&pixieState)
        let now = pixieState.layout.leaves
        if now != open {
            store.set(now.isEmpty ? nil : now.joined(separator: "\n"), forKey: Key.pixiePanes)
        }
    }

    /// Opens a pixie's pane in the Pixies tab and focuses it, or focuses it when it is
    /// open: a click in the list, or a pixie call's name in a chat. A workspace not
    /// measured yet (no area, as while the tab is coming on screen) places it by the size
    /// a restored window uses.
    public func openPixie(_ id: String, in size: CGSize) {
        let measured = size.width > 0 && size.height > 0 ? size : Self.restoreSize
        updatePixies { $0.openChat(id, in: measured) }
    }

    /// Folds a team's section in the Pixies list, or unfolds it.
    public func toggleTeamFold(_ id: String) {
        if foldedTeams.remove(id) == nil {
            foldedTeams.insert(id)
        }
        let saved = foldedTeams.sorted().joined(separator: "\n")
        store.set(saved.isEmpty ? nil : saved, forKey: Key.foldedTeams)
    }

    /// Closes the panes of pixies that are gone: `ids` are every pixie there is.
    public func keepPixies(_ ids: Set<String>) {
        let gone = pixieState.layout.leaves.filter { !ids.contains($0) }
        guard !gone.isEmpty else { return }
        updatePixies { state in
            for id in gone {
                state.closePane(id)
            }
        }
    }

    /// The ongoing chats of the pixies open in the Pixies tab.
    public func openPixieChats(_ pixies: [Pixie]) -> Set<String> {
        Set(Self.chats(of: pixieState.layout.leaves, among: pixies))
    }

    /// The chats of the pixies with these ids, in their order; pixies with no chat yet, or
    /// gone, are left out.
    static func chats(of ids: [String], among pixies: [Pixie]) -> [String] {
        ids.compactMap { id in pixies.first { $0.id == id }?.chatSessionID }
    }

    public func openProject(_ name: String, in app: RepoApp) async throws {
        try await api.openRepo(name, in: app)
    }

    // MARK: Project settings

    /// Unregisters a project; with `purgeChats` its chats are deleted first, which the
    /// daemon requires while it has any. The folder stays. Its tab closes and its terminal
    /// and browser panes end.
    public func removeProject(_ name: String, purgeChats: Bool) async throws {
        try await api.removeRepo(name, purgeSessions: purgeChats)
        show(repos.filter { $0.name != name })
    }

    /// Changes a project's worktree default, links or setup commands. Saves run one at a
    /// time per project, each change applied to the settings the last save returned, and
    /// only the settings it changed are sent (audit BUG-102). Nil when the project is gone.
    @discardableResult
    public func changeSettings(
        of name: String, _ change: @escaping @Sendable (inout WorktreeConfig) -> Void
    ) async throws -> Repo? {
        try await saveSettings(of: name) { repo in
            var config = repo.worktree
            change(&config)
            return RepoPatch(from: repo.worktree, to: config)
        }
    }

    /// Changes a project's icon (B36), saved in turn with its other settings like
    /// `changeSettings`. Nil when the project is gone.
    @discardableResult
    public func changeIcon(
        of name: String, _ change: @escaping @Sendable (inout ProjectIcon) -> Void
    ) async throws -> Repo? {
        try await saveSettings(of: name) { repo in
            var icon = repo.projectIcon
            change(&icon)
            return RepoPatch(from: repo.projectIcon, to: icon)
        }
    }

    private func saveSettings(
        of name: String, _ patch: @escaping @Sendable (Repo) -> RepoPatch
    ) async throws -> Repo? {
        let previous = settingSaves[name]
        let save = Task {
            _ = try? await previous?.value
            guard let repo = repo(name) else { return nil as Repo? }
            let patch = patch(repo)
            guard !patch.isEmpty else { return repo }
            let saved = try await api.updateRepo(name, patch)
            if let index = repos.firstIndex(where: { $0.name == name }) {
                repos[index] = saved
            }
            return saved
        }
        settingSaves[name] = save
        defer {
            if settingSaves[name] == save {
                settingSaves[name] = nil
            }
        }
        return try await save.value
    }

    /// A settings change of the project is saving or waiting its turn.
    public func isSavingSettings(of name: String) -> Bool {
        settingSaves[name] != nil
    }

    /// Gitignored files of the project worth linking, not linked yet.
    public func linkSuggestions(for name: String) async throws -> [String] {
        let linked = Set(repo(name)?.worktree.link ?? [])
        return try await api.linkSuggestions(name).filter { !linked.contains($0) }
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
