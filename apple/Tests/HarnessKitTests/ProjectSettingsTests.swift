import Foundation
import Testing

@testable import HarnessKit

/// Per-project settings: Remove, the worktree default, links and setup (IMP-09).
@MainActor
@Suite struct ProjectSettingsTests {
    let api = FakeAPI()
    let memory = MemoryStore()

    func loaded() async throws -> AppStore {
        let app = AppStore(api: api, store: memory)
        try await app.loadRepos()
        return app
    }

    @Test func removingAProjectClosesItsTab() async throws {
        let app = try await loaded()
        app.openProject("map-viewer")
        app.update("map-viewer") {
            $0.openTool(.terminal(in: "/tmp"), in: CGSize(width: 9, height: 9))
        }
        #expect(memory.values["projects.tools.map-viewer"] != nil)

        try await app.removeProject("map-viewer", purgeChats: true)

        #expect(api.calls.last == "removeRepo map-viewer purge=true")
        #expect(app.repos.map(\.name) == ["todo-ui"])
        #expect(app.openProjects == ["todo-ui"])
        #expect(app.currentProject == "todo-ui")
        #expect(app.projects["map-viewer"] == nil)
        #expect(memory.values["projects.tools.map-viewer"] == nil)

        try await app.removeProject("todo-ui", purgeChats: false)
        #expect(api.calls.last == "removeRepo todo-ui purge=false")
        #expect(app.openProjects.isEmpty)
        #expect(app.currentProject == nil)
    }

    @Test func aRefusedRemovalKeepsTheProject() async throws {
        let app = try await loaded()
        api.fail("removeRepo", with: APIError.conflict("still has sessions", files: []))
        await #expect(throws: APIError.self) {
            try await app.removeProject("todo-ui", purgeChats: false)
        }
        #expect(app.repos.count == 2)
    }

    @Test func savingTheWorktreeSettingsUpdatesTheProject() async throws {
        let app = try await loaded()
        var config = try #require(app.repo("todo-ui")).worktree
        config.isDefault = nil
        config.setup = []

        let saved = try await app.saveWorktree(config, of: "todo-ui")

        #expect(saved.worktree == config)
        #expect(app.repo("todo-ui")?.worktree == config)
        #expect(
            api.calls.last
                == #"updateWorktree todo-ui {"link":[".env.local"],"setup":[],"setup_timeout_seconds":900}"#
        )
        // A project gone from the list meanwhile is not added back.
        api.set { $0.repos.append(Fixture.plainRepo) }
        try await app.saveWorktree(config, of: Fixture.plainRepo.name)
        #expect(app.repo(Fixture.plainRepo.name) == nil)
    }

    @Test func suggestsOnlyLinksNotThereYet() async throws {
        let app = try await loaded()
        api.set { $0.linkSuggestions["todo-ui"] = [".env.local", "node_modules/", ".env"] }
        #expect(try await app.linkSuggestions(for: "todo-ui") == ["node_modules/", ".env"])
        api.set { $0.linkSuggestions["other"] = [".env"] }
        #expect(try await app.linkSuggestions(for: "other") == [".env"])
    }

    @Test func linksMustStayInsideTheProject() {
        var config = WorktreeConfig()
        let added = ["  .env  ", "config/local.json", "node_modules/"].map { config.addLink($0) }
        #expect(added == [true, true, true])
        let refused = ["", "   ", ".env", "/etc/hosts", "../secrets", "a/../../b", ".", "./"]
        #expect(refused.map { config.addLink($0) }.allSatisfy { !$0 })
        #expect(config.link == [".env", "config/local.json", "node_modules/"])

        let commands = [" npm ci \n", "  "].map { config.addSetup($0) }
        #expect(commands == [true, false])
        #expect(config.setup == ["npm ci"])
    }

    @Test func theRemovalSaysWhatGoes() {
        #expect(
            ProjectRemoval.consequence(chats: 0)
                == "harness forgets this project. Its folder stays as it is.")
        #expect(
            ProjectRemoval.consequence(chats: 1).hasSuffix(
                "Its chat is deleted for good, with its worktree and branch."))
        #expect(
            ProjectRemoval.consequence(chats: 3).hasSuffix(
                "Its 3 chats are deleted for good, with their worktrees and branches."))
    }
}
