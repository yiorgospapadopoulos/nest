import CoreGraphics
import Foundation
import Testing

@testable import NestKit

private let workspace = CGSize(width: 1000, height: 600)

@MainActor
@Suite struct AppStoreTests {
    let api = FakeAPI()
    let memory = MemoryStore()

    func app() -> AppStore {
        AppStore(api: api, store: memory)
    }

    @Test func numberAndArrowShortcutsPickTabs() async throws {
        let app = app()
        app.selectProject(at: 0)
        app.selectProject(offset: 1)
        #expect(app.currentProject == nil)
        api.set {
            $0.repos += [Fixture.repos[0]].map { repo in
                var repo = repo
                repo.name = "third"
                return repo
            }
        }
        try await app.loadRepos()
        app.openProject("map-viewer")
        app.openProject("third")
        app.selectProject(at: 0)
        #expect(app.currentProject == "todo-ui")
        app.selectProject(at: 8)
        #expect(app.currentProject == "third")
        app.selectProject(at: 1)
        #expect(app.currentProject == "map-viewer")
        app.selectProject(at: 5)
        app.selectProject(at: -1)
        #expect(app.currentProject == "map-viewer")
        app.selectProject(offset: 1)
        #expect(app.currentProject == "third")
        app.selectProject(offset: 1)
        #expect(app.currentProject == "todo-ui")
        app.selectProject(offset: -1)
        #expect(app.currentProject == "third")
    }

    @Test func revealOpensTheProjectAndTheChat() async throws {
        let app = app()
        try await app.loadRepos()
        app.reveal(chat: "h1", in: "map-viewer", size: workspace)
        #expect(app.currentProject == "map-viewer")
        #expect(app.state(of: "map-viewer").layout.focused == "h1")
        app.reveal(chat: "x", in: "gone", size: workspace)
        #expect(app.currentProject == "map-viewer")
        #expect(app.projects["gone"] == nil)
    }

    @Test func opensTheFirstRepoWhenNoTabIsOpen() async throws {
        let app = app()
        try await app.loadRepos()
        #expect(app.repos.map(\.name) == ["todo-ui", "map-viewer"])
        #expect(app.openProjects == ["todo-ui"])
        #expect(app.currentProject == "todo-ui")
        #expect(app.closedRepos.map(\.name) == ["map-viewer"])
        #expect(app.repo("map-viewer")?.defaultBranch == "develop")
        #expect(app.repo("nope") == nil)
        #expect(memory.values == ["projects.open": "todo-ui", "projects.current": "todo-ui"])
    }

    @Test func restoresTabsAndDropsReposThatAreGone() async throws {
        memory.values = ["projects.open": "gone\nmap-viewer\ntodo-ui", "projects.current": "gone"]
        let app = app()
        #expect(app.openProjects == ["gone", "map-viewer", "todo-ui"])

        try await app.loadRepos()

        // The tabs follow the daemon's project order (D090) and the first one is current.
        #expect(app.openProjects == ["todo-ui", "map-viewer"])
        #expect(app.currentProject == "todo-ui")
    }

    @Test func keepsAValidCurrentTab() async throws {
        memory.values = ["projects.open": "map-viewer\ntodo-ui", "projects.current": "todo-ui"]
        let app = app()
        try await app.loadRepos()
        #expect(app.currentProject == "todo-ui")
    }

    @Test func noReposMeansNoTabs() async throws {
        api.set { $0.repos = [] }
        let app = app()
        try await app.loadRepos()
        #expect(app.openProjects.isEmpty)
        #expect(app.currentProject == nil)
        #expect(memory.values["projects.current"] == nil)
    }

    @Test func managesTabs() async throws {
        let app = app()
        try await app.loadRepos()

        app.openProject("map-viewer")
        app.openProject("map-viewer")
        #expect(app.openProjects == ["todo-ui", "map-viewer"])
        #expect(app.currentProject == "map-viewer")

        app.selectProject("todo-ui")
        app.selectProject("not-open")
        #expect(app.currentProject == "todo-ui")

        app.closeProject("todo-ui")
        #expect(app.openProjects == ["map-viewer"])
        #expect(app.currentProject == "map-viewer")
        app.closeProject("map-viewer")
        #expect(app.openProjects == ["map-viewer"])
        #expect(memory.values["projects.open"] == "map-viewer")
    }

    @Test func openPanesSpanEveryProject() async throws {
        let app = app()
        try await app.loadRepos()
        app.update("todo-ui") { $0.openChat("s1", in: workspace) }
        app.update("map-viewer") { $0.openChat("s2", in: workspace) }
        #expect(app.openPanes == ["s1", "s2"])
        app.update("todo-ui") { $0.closePane("s1") }
        #expect(app.openPanes == ["s2"])
    }

    @Test func closingTheCurrentTabSelectsTheOneBefore() async throws {
        let app = app()
        try await app.loadRepos()
        app.openProject("map-viewer")
        app.closeProject("map-viewer")
        #expect(app.currentProject == "todo-ui")
        app.openProject("map-viewer")
        app.selectProject("todo-ui")
        app.closeProject("map-viewer")
        #expect(app.currentProject == "todo-ui")
        app.openProject("map-viewer")
        app.openProject("todo-ui")
        app.closeProject("missing")
        #expect(app.openProjects == ["todo-ui", "map-viewer"])
    }

    @Test func addsAProjectFromAFolder() async throws {
        let app = app()
        try await app.loadRepos()
        let repo = try await app.addProject(path: "/Users/example/projects/notes-app")
        #expect(repo.name == "notes-app")
        #expect(app.repos.map(\.name) == ["todo-ui", "map-viewer", "notes-app"])
        #expect(app.currentProject == "notes-app")
    }

    @Test func eachProjectKeepsItsOwnWorkspace() async throws {
        let app = app()
        try await app.loadRepos()
        app.openProject("map-viewer")

        app.update { $0.openChat("h1", in: workspace) }
        app.update("todo-ui") { state in
            state.openChat("c1", in: workspace)
            state.openChat("c2", in: workspace)
            state.leftCollapsed = true
        }

        #expect(app.state(of: "map-viewer").layout.leaves == ["h1"])
        #expect(app.state(of: "todo-ui").layout.leaves == ["c1", "c2"])
        #expect(app.state(of: "todo-ui").leftCollapsed)
        #expect(app.state(of: "other") == ProjectState())
    }

    @Test func updatingWithoutAProjectDoesNothing() async throws {
        api.set { $0.repos = [] }
        let app = app()
        app.update { $0.leftCollapsed = true }
        #expect(app.projects.isEmpty)
    }

    @Test func aDeletedChatLeavesEveryWorkspace() async throws {
        let app = app()
        app.update("todo-ui") { state in
            state.openChat("c1", in: workspace)
            state.openChat("c2", in: workspace)
            state.expandedGoals = ["c2"]
        }
        app.update("map-viewer") { $0.openChat("c2", in: workspace) }

        app.forgetChat("c2")

        #expect(app.state(of: "todo-ui").layout.leaves == ["c1"])
        #expect(app.state(of: "todo-ui").selectedChat == "c1")
        #expect(app.state(of: "todo-ui").expandedGoals.isEmpty)
        #expect(app.state(of: "map-viewer").layout.leaves.isEmpty)
        #expect(app.state(of: "map-viewer").selectedChat == nil)
    }

    @Test func opensProjectsInLocalApps() async throws {
        try await app().openProject("todo-ui", in: .finder)
        #expect(api.calls == ["openRepo todo-ui finder"])
    }

    @Test func defaultsToUserDefaults() {
        #expect(AppStore(api: api).store is UserDefaultsStore)
    }
}

@Suite struct ProjectStateTests {
    @Test func startsWithAllCardsOpenOnTheWorkspace() {
        let state = ProjectState()
        #expect(state.openCards == [.agents, .needsYou, .goals])
        #expect(state.view == .workspace)
        #expect(!state.leftCollapsed && !state.rightCollapsed)
        #expect(state.layout.leaves.isEmpty)
    }

    @Test func openingAChatLeavesTheBoard() {
        var state = ProjectState()
        state.view = .board
        #expect(state.openChat("c1", in: workspace) == .added)
        #expect(state.view == .workspace)
        #expect(state.selectedChat == "c1")
    }

    @Test func dragAndDropSelectsTheDroppedChat() {
        var state = ProjectState()
        state.openChat("c1", in: workspace)
        state.view = .board
        state.dropChat("c2", onto: "c1", side: .left)
        #expect(state.layout.leaves == ["c2", "c1"])
        #expect(state.selectedChat == "c2")
        state.dropChat("c3", onto: "missing", side: .left)
        #expect(state.selectedChat == "c2")
        #expect(state.view == .workspace)
    }

    @Test func closingAndFocusingPanes() {
        var state = ProjectState()
        state.openChat("c1", in: workspace)
        state.openChat("c2", in: workspace)
        state.focusPane("c1")
        #expect(state.selectedChat == "c1")
        state.closePane("c1")
        #expect(state.selectedChat == "c2")
        state.closePane("c3")
        #expect(state.selectedChat == "c2")
    }

    @Test func cardsOpenAndCloseIndependently() {
        var state = ProjectState()
        state.toggleCard(.agents)
        #expect(state.openCards == [.needsYou, .goals])
        state.toggleCard(.agents)
        #expect(state.openCards == [.agents, .needsYou, .goals])

        state.rightCollapsed = true
        state.toggleCard(.goals)
        state.showCard(.goals)
        #expect(!state.rightCollapsed)
        #expect(state.openCards.contains(.goals))
    }
}
