import Foundation
import Testing

@testable import NestKit

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
        api.fail("removeRepo", with: APIError.conflict("still has sessions"))
        await #expect(throws: APIError.self) {
            try await app.removeProject("todo-ui", purgeChats: false)
        }
        #expect(app.repos.count == 2)
    }

    /// Each change sends only the setting it changed, so it cannot undo a change made
    /// meanwhile elsewhere (audit BUG-102).
    @Test func aChangeSendsOnlyWhatItChanged() async throws {
        let app = try await loaded()
        let saved = try await app.changeSettings(of: "todo-ui") { $0.isDefault = nil }
        #expect(saved?.worktree.isDefault == nil)
        #expect(app.repo("todo-ui")?.worktree.isDefault == nil)
        #expect(api.calls.last == #"updateRepo todo-ui {"default":null}"#)

        try await app.changeSettings(of: "todo-ui") { $0.setup = [] }
        #expect(api.calls.last == #"updateRepo todo-ui {"setup":[]}"#)
        #expect(app.repo("todo-ui")?.worktree.link == [".env.local"])

        // Nothing changed, nothing sent.
        let calls = api.calls.count
        let same = try await app.changeSettings(of: "todo-ui") { $0.addLink(".env.local") }
        #expect(same == app.repo("todo-ui"))
        #expect(api.calls.count == calls)
        // A project gone meanwhile is left alone.
        #expect(try await app.changeSettings(of: "gone") { $0.isDefault = true } == nil)
        #expect(api.calls.count == calls)
    }

    /// Quick changes save one at a time, each on top of what the last save returned, so
    /// none is lost (audit BUG-102).
    @Test func quickChangesSaveInTurnWithoutLosingAny() async throws {
        let app = try await loaded()
        let gate = AsyncStream<Void>.makeStream()
        api.set { $0.gates["updateRepo"] = gate.stream }
        let first = Task { try await app.changeSettings(of: "todo-ui") { $0.addLink("a") } }
        try await waitFor { app.isSavingSettings(of: "todo-ui") }
        let second = Task { try await app.changeSettings(of: "todo-ui") { $0.addLink("b") } }
        try await Task.sleep(for: .milliseconds(20))
        #expect(!api.calls.contains { $0.hasPrefix("updateRepo") })

        gate.continuation.finish()
        _ = try await first.value
        _ = try await second.value

        #expect(
            api.calls.filter { $0.hasPrefix("updateRepo") } == [
                #"updateRepo todo-ui {"link":[".env.local","a"]}"#,
                #"updateRepo todo-ui {"link":[".env.local","a","b"]}"#,
            ])
        #expect(app.repo("todo-ui")?.worktree.link == [".env.local", "a", "b"])
        #expect(!app.isSavingSettings(of: "todo-ui"))
    }

    /// A refused save leaves the project as it was, and later changes still save.
    @Test func aRefusedChangeKeepsTheProjectAndTheNextOneSaves() async throws {
        let app = try await loaded()
        api.fail("updateRepo", with: APIError.invalidInput("bad link"))
        await #expect(throws: APIError.invalidInput("bad link")) {
            try await app.changeSettings(of: "todo-ui") { $0.addLink("x") }
        }
        #expect(app.repo("todo-ui")?.worktree.link == [".env.local"])
        api.set { $0.failures = [:] }
        try await app.changeSettings(of: "todo-ui") { $0.addLink("y") }
        #expect(app.repo("todo-ui")?.worktree.link == [".env.local", "y"])
    }

    /// B36: the icon is a project setting too, sent alone and saved in turn with the others.
    @Test func theIconChangesOnlyWhatChanged() async throws {
        let app = try await loaded()
        let gate = AsyncStream<Void>.makeStream()
        api.set { $0.gates["updateRepo"] = gate.stream }
        let links = Task { try await app.changeSettings(of: "todo-ui") { $0.addLink("a") } }
        try await waitFor { app.isSavingSettings(of: "todo-ui") }
        let sprite = Task { try await app.changeIcon(of: "todo-ui") { $0.mascot = .moth } }
        try await Task.sleep(for: .milliseconds(20))
        gate.continuation.finish()
        _ = try await links.value
        let saved = try await sprite.value

        #expect(saved?.projectIcon == ProjectIcon(mascot: .moth))
        #expect(app.repo("todo-ui")?.projectIcon == ProjectIcon(mascot: .moth))
        #expect(app.repo("todo-ui")?.worktree.link == [".env.local", "a"])
        #expect(api.calls.last == #"updateRepo todo-ui {"icon":"moth"}"#)

        try await app.changeIcon(of: "todo-ui") { $0.color = "#FF8800" }
        #expect(api.calls.last == ##"updateRepo todo-ui {"icon_color":"#FF8800"}"##)
        try await app.changeIcon(of: "todo-ui") { $0 = ProjectIcon() }
        #expect(api.calls.last == #"updateRepo todo-ui {"icon":null,"icon_color":null}"#)
        #expect(app.repo("todo-ui")?.projectIcon == ProjectIcon())

        // Nothing changed, nothing sent; a project gone meanwhile is left alone.
        let calls = api.calls.count
        #expect(try await app.changeIcon(of: "todo-ui") { $0.mascot = nil } == app.repo("todo-ui"))
        #expect(try await app.changeIcon(of: "gone") { $0.mascot = .bluebell } == nil)
        #expect(api.calls.count == calls)
        #expect(!app.isSavingSettings(of: "todo-ui"))
    }

    @Test func removingByValueSkipsAnEntryAlreadyGone() {
        var config = WorktreeConfig(link: ["a", "b"], setup: ["npm ci", "make", "npm ci"])
        config.removeLink("b")
        config.removeLink("zz")
        #expect(config.link == ["a"])
        config.removeSetup("npm ci", at: 2)
        #expect(config.setup == ["npm ci", "make"])
        // The list changed since it was shown: the command at that place is another one.
        config.removeSetup("npm ci", at: 1)
        config.removeSetup("npm ci", at: 9)
        #expect(config.setup == ["npm ci", "make"])
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
                == "Nest forgets this project. Its folder stays as it is.")
        #expect(
            ProjectRemoval.consequence(chats: 1).hasSuffix(
                "Its chat is deleted for good, with its worktree and history; its branch stays."))
        #expect(
            ProjectRemoval.consequence(chats: 3).hasSuffix(
                "Its 3 chats are deleted for good, with their worktrees and history;"
                    + " their branches stay."))
    }
}
