import Foundation
import Testing

@testable import NestKit

/// General (B110): chats with no project, in a tab of its own before the project tabs.
@MainActor
@Suite struct GeneralTabTests {
    let api = FakeAPI()
    let memory = MemoryStore()

    @Test func generalIsAPlainFolderWithNoGitBadge() {
        let general = Repo.general

        #expect(general.name == "general")
        #expect(general.isGeneral)
        #expect(general.title == "General")
        #expect(!general.git)
        #expect(general.badge == nil)
        #expect(general.mode(for: .worktree) == .inPlace)
        #expect(!Fixture.repos[0].isGeneral)
        #expect(Fixture.repos[0].title == "todo-ui")
    }

    @Test func theAppKnowsGeneralWithoutTheDaemonListingIt() async throws {
        let app = AppStore(api: api, store: memory)
        try await app.loadRepos()

        #expect(app.repo(Repo.generalName) == .general)
        #expect(!app.repos.contains(.general))
        #expect(!app.closedRepos.contains(.general))
        #expect(!app.isGeneralOpen)
    }

    @Test func generalOpensAsTheFirstTabAndCmdOneSelectsIt() async throws {
        let app = AppStore(api: api, store: memory)
        try await app.loadRepos()
        app.openProject("map-viewer")

        app.openProject(Repo.generalName)

        #expect(app.openProjects == ["general", "todo-ui", "map-viewer"])
        #expect(app.currentProject == "general")
        #expect(app.isGeneralOpen)
        app.selectProject(at: 1)
        #expect(app.currentProject == "todo-ui")
        app.selectProject(at: 0)
        #expect(app.currentProject == "general")
        // Saved and restored first, and kept when the repos load again.
        #expect(memory.values[AppStore.Key.openProjects] == "general\ntodo-ui\nmap-viewer")
        let relaunched = AppStore(api: api, store: memory)
        try await relaunched.loadRepos()
        #expect(relaunched.openProjects == ["general", "todo-ui", "map-viewer"])
    }

    @Test func generalClosesAndReopensFirst() async throws {
        let app = AppStore(api: api, store: memory)
        try await app.loadRepos()
        app.openProject(Repo.generalName)

        app.closeProject(Repo.generalName)
        #expect(app.openProjects == ["todo-ui"])
        #expect(app.currentProject == "todo-ui")
        #expect(!app.isGeneralOpen)

        app.openProject(Repo.generalName)
        #expect(app.openProjects == ["general", "todo-ui"])
    }

    @Test func generalStaysFirstWhenTabsMove() async throws {
        let app = AppStore(api: api, store: memory)
        try await app.loadRepos()
        app.openProject("map-viewer")
        app.openProject(Repo.generalName)

        app.moveProject(Repo.generalName, to: 2)
        #expect(app.openProjects == ["general", "todo-ui", "map-viewer"])
        app.moveProject("map-viewer", to: 0)
        #expect(app.openProjects == ["general", "map-viewer", "todo-ui"])
        await app.savingOrder?.value
        #expect(api.calls.last == "reorderRepos map-viewer,todo-ui")
    }
}
