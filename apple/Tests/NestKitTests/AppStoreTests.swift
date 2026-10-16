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
        app.openProject("llm-hunter")
        app.openProject("third")
        app.selectProject(at: 0)
        #expect(app.currentProject == "cv-page")
        app.selectProject(at: 8)
        #expect(app.currentProject == "third")
        app.selectProject(at: 1)
        #expect(app.currentProject == "llm-hunter")
        app.selectProject(at: 5)
        app.selectProject(at: -1)
        #expect(app.currentProject == "llm-hunter")
        app.selectProject(offset: 1)
        #expect(app.currentProject == "third")
        app.selectProject(offset: 1)
        #expect(app.currentProject == "cv-page")
        app.selectProject(offset: -1)
        #expect(app.currentProject == "third")
    }

    @Test func revealOpensTheProjectAndTheChat() async throws {
        let app = app()
        try await app.loadRepos()
        app.reveal(chat: "h1", in: "llm-hunter", size: workspace)
        #expect(app.currentProject == "llm-hunter")
        #expect(app.state(of: "llm-hunter").layout.focused == "h1")
        app.reveal(chat: "x", in: "gone", size: workspace)
        #expect(app.currentProject == "llm-hunter")
        #expect(app.projects["gone"] == nil)
    }

    @Test func opensTheFirstRepoWhenNoTabIsOpen() async throws {
        let app = app()
        try await app.loadRepos()
        #expect(app.repos.map(\.name) == ["cv-page", "llm-hunter"])
        #expect(app.openProjects == ["cv-page"])
        #expect(app.currentProject == "cv-page")
        #expect(app.closedRepos.map(\.name) == ["llm-hunter"])
        #expect(app.repo("llm-hunter")?.defaultBranch == "develop")
        #expect(app.repo("nope") == nil)
        #expect(memory.values == ["projects.open": "cv-page", "projects.current": "cv-page"])
    }

    @Test func restoresTabsAndDropsReposThatAreGone() async throws {
        memory.values = ["projects.open": "gone\nllm-hunter\ncv-page", "projects.current": "gone"]
        let app = app()
        #expect(app.openProjects == ["gone", "llm-hunter", "cv-page"])

        try await app.loadRepos()

        // The tabs follow the daemon's project order (D090) and the first one is current.
        #expect(app.openProjects == ["cv-page", "llm-hunter"])
        #expect(app.currentProject == "cv-page")
    }

    @Test func keepsAValidCurrentTab() async throws {
        memory.values = ["projects.open": "llm-hunter\ncv-page", "projects.current": "cv-page"]
        let app = app()
        try await app.loadRepos()
        #expect(app.currentProject == "cv-page")
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

        app.openProject("llm-hunter")
        app.openProject("llm-hunter")
        #expect(app.openProjects == ["cv-page", "llm-hunter"])
        #expect(app.currentProject == "llm-hunter")

        app.selectProject("cv-page")
        app.selectProject("not-open")
        #expect(app.currentProject == "cv-page")

        app.closeProject("cv-page")
        #expect(app.openProjects == ["llm-hunter"])
        #expect(app.currentProject == "llm-hunter")
        app.closeProject("llm-hunter")
        #expect(app.openProjects == ["llm-hunter"])
        #expect(memory.values["projects.open"] == "llm-hunter")
    }

    @Test func openPanesSpanEveryProject() async throws {
        let app = app()
        try await app.loadRepos()
        app.update("cv-page") { $0.openChat("s1", in: workspace) }
        app.update("llm-hunter") { $0.openChat("s2", in: workspace) }
        #expect(app.openPanes == ["s1", "s2"])
        app.update("cv-page") { $0.closePane("s1") }
        #expect(app.openPanes == ["s2"])
    }

    @Test func closingTheCurrentTabSelectsTheOneBefore() async throws {
        let app = app()
        try await app.loadRepos()
        app.openProject("llm-hunter")
        app.closeProject("llm-hunter")
        #expect(app.currentProject == "cv-page")
        app.openProject("llm-hunter")
        app.selectProject("cv-page")
        app.closeProject("llm-hunter")
        #expect(app.currentProject == "cv-page")
        app.openProject("llm-hunter")
        app.openProject("cv-page")
        app.closeProject("missing")
        #expect(app.openProjects == ["cv-page", "llm-hunter"])
    }

    @Test func addsAProjectFromAFolder() async throws {
        let app = app()
        try await app.loadRepos()
        let repo = try await app.addProject(path: "/Users/example/projects/novel-engine")
        #expect(repo.name == "novel-engine")
        #expect(app.repos.map(\.name) == ["cv-page", "llm-hunter", "novel-engine"])
        #expect(app.currentProject == "novel-engine")
    }

    @Test func eachProjectKeepsItsOwnWorkspace() async throws {
        let app = app()
        try await app.loadRepos()
        app.openProject("llm-hunter")

        app.update { $0.openChat("h1", in: workspace) }
        app.update("cv-page") { state in
            state.openChat("c1", in: workspace)
            state.openChat("c2", in: workspace)
            state.leftCollapsed = true
        }

        #expect(app.state(of: "llm-hunter").layout.leaves == ["h1"])
        #expect(app.state(of: "cv-page").layout.leaves == ["c1", "c2"])
        #expect(app.state(of: "cv-page").leftCollapsed)
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
        app.update("cv-page") { state in
            state.openChat("c1", in: workspace)
            state.openChat("c2", in: workspace)
            state.expandedGoals = ["c2"]
        }
        app.update("llm-hunter") { $0.openChat("c2", in: workspace) }

        app.forgetChat("c2")

        #expect(app.state(of: "cv-page").layout.leaves == ["c1"])
        #expect(app.state(of: "cv-page").selectedChat == "c1")
        #expect(app.state(of: "cv-page").expandedGoals.isEmpty)
        #expect(app.state(of: "llm-hunter").layout.leaves.isEmpty)
        #expect(app.state(of: "llm-hunter").selectedChat == nil)
    }

    @Test func opensProjectsInLocalApps() async throws {
        try await app().openProject("cv-page", in: .finder)
        #expect(api.calls == ["openRepo cv-page finder"])
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
