import CoreGraphics
import Foundation
import Testing

@testable import NestKit

@Suite struct TabReorderTests {
    @Test func theTargetIsTheNearestWholeStepWithinTheTabs() {
        #expect(TabReorder.target(from: 1, translation: 0, step: 100, count: 4) == 1)
        #expect(TabReorder.target(from: 1, translation: 49, step: 100, count: 4) == 1)
        #expect(TabReorder.target(from: 1, translation: 51, step: 100, count: 4) == 2)
        #expect(TabReorder.target(from: 1, translation: -60, step: 100, count: 4) == 0)
        #expect(TabReorder.target(from: 1, translation: 260, step: 100, count: 4) == 3)
        #expect(TabReorder.target(from: 1, translation: 900, step: 100, count: 4) == 3)
        #expect(TabReorder.target(from: 1, translation: -900, step: 100, count: 4) == 0)
    }

    @Test func withoutAMeasuredStepOrTabsTheTabStays() {
        #expect(TabReorder.target(from: 2, translation: 300, step: 0, count: 4) == 2)
        #expect(TabReorder.target(from: 0, translation: 300, step: 100, count: 0) == 0)
    }

    @Test func theTabsInBetweenSlideOneStepTowardTheStart() {
        let right = (0..<5).map { TabReorder.offset(of: $0, from: 1, to: 3, step: 80) }
        #expect(right == [0, 0, -80, -80, 0])
        let left = (0..<5).map { TabReorder.offset(of: $0, from: 3, to: 1, step: 80) }
        #expect(left == [0, 80, 80, 0, 0])
        let still = (0..<3).map { TabReorder.offset(of: $0, from: 1, to: 1, step: 80) }
        #expect(still == [0, 0, 0])
    }
}

@MainActor
@Suite struct ProjectOrderTests {
    let api = FakeAPI()
    let memory = MemoryStore()

    init() {
        api.set {
            $0.repos += ["third", "fourth"].map { name in
                var repo = Fixture.repos[0]
                repo.name = name
                return repo
            }
        }
    }

    func names(_ repos: [Repo]) -> [String] { repos.map(\.name) }

    @Test func openTabsFollowTheRepoOrderOnceLoaded() async throws {
        memory.values[AppStore.Key.openProjects] = "fourth\ntodo-ui\ngone"
        let app = AppStore(api: api, store: memory)
        // Before the repos load the saved order stands, and a new tab goes last.
        app.openProject("third")
        #expect(app.openProjects == ["fourth", "todo-ui", "gone", "third"])

        try await app.loadRepos()
        #expect(app.openProjects == ["todo-ui", "third", "fourth"])
        #expect(memory.values[AppStore.Key.openProjects] == "todo-ui\nthird\nfourth")

        app.openProject("map-viewer")
        #expect(app.openProjects == ["todo-ui", "map-viewer", "third", "fourth"])
        app.selectProject(at: 1)
        #expect(app.currentProject == "map-viewer")
    }

    @Test func movingATabPlacesItBeforeTheTabThatFollowsIt() async throws {
        let app = AppStore(api: api, store: memory)
        try await app.loadRepos()
        app.openProject("third")
        app.openProject("fourth")
        #expect(app.openProjects == ["todo-ui", "third", "fourth"])

        // map-viewer is closed: the project moves just before the tab that follows it.
        app.moveProject("fourth", to: 0)
        #expect(app.openProjects == ["fourth", "todo-ui", "third"])
        #expect(names(app.repos) == ["fourth", "todo-ui", "map-viewer", "third"])
        #expect(memory.values[AppStore.Key.openProjects] == "fourth\ntodo-ui\nthird")
        await app.savingOrder?.value
        #expect(api.calls.last == "reorderRepos fourth,todo-ui,map-viewer,third")

        app.selectProject(at: 0)
        #expect(app.currentProject == "fourth")
    }

    @Test func movingATabLastPlacesItAfterTheTabBeforeIt() async throws {
        let app = AppStore(api: api, store: memory)
        try await app.loadRepos()
        app.openProject("third")

        // Past the end is clamped to the last place.
        app.moveProject("todo-ui", to: 9)
        #expect(app.openProjects == ["third", "todo-ui"])
        #expect(names(app.repos) == ["map-viewer", "third", "todo-ui", "fourth"])
        await app.savingOrder?.value
        #expect(api.calls.last == "reorderRepos map-viewer,third,todo-ui,fourth")

        app.moveProject("todo-ui", to: -3)
        #expect(app.openProjects == ["todo-ui", "third"])
        #expect(names(app.repos) == ["map-viewer", "todo-ui", "third", "fourth"])
    }

    @Test func aMoveNowhereOrOfAClosedTabChangesNothing() async throws {
        let app = AppStore(api: api, store: memory)
        try await app.loadRepos()
        app.openProject("third")

        app.moveProject("third", to: 1)
        app.moveProject("map-viewer", to: 0)
        await app.savingOrder?.value

        #expect(app.openProjects == ["todo-ui", "third"])
        #expect(!api.calls.contains { $0.hasPrefix("reorderRepos") })
    }

    @Test func beforeTheReposLoadNothingMoves() {
        memory.values[AppStore.Key.openProjects] = "todo-ui\nthird"
        let app = AppStore(api: api, store: memory)

        app.moveProject("third", to: 0)

        #expect(app.openProjects == ["todo-ui", "third"])
        #expect(app.savingOrder == nil)
    }

    @Test func savesRunOneAtATimeInOrder() async throws {
        let (gate, open) = AsyncStream<Void>.makeStream()
        api.set { $0.gates["reorderRepos"] = gate }
        let app = AppStore(api: api, store: memory)
        try await app.loadRepos()
        app.openProject("third")

        app.moveProject("third", to: 0)
        app.moveProject("todo-ui", to: 0)
        #expect(app.openProjects == ["todo-ui", "third"])
        open.finish()
        await app.savingOrder?.value

        #expect(
            api.calls.filter { $0.hasPrefix("reorderRepos") } == [
                "reorderRepos third,todo-ui,map-viewer,fourth",
                "reorderRepos todo-ui,third,map-viewer,fourth",
            ])
    }

    @Test func aFailedSaveShowsTheErrorAndReloadsTheRepos() async throws {
        let app = AppStore(api: api, store: memory)
        try await app.loadRepos()
        app.openProject("third")
        api.fail("reorderRepos")

        app.moveProject("third", to: 0)
        #expect(app.openProjects == ["third", "todo-ui"])
        await app.savingOrder?.value
        await app.reloadingRepos?.value

        #expect(app.syncError == .server(status: 500, detail: "boom"))
        #expect(app.openProjects == ["todo-ui", "third"])
        #expect(names(app.repos) == ["todo-ui", "map-viewer", "third", "fourth"])
    }

    @Test func aFailureOtherThanTheAPIsIsATransportError() async throws {
        struct Broken: Error {}
        let app = AppStore(api: api, store: memory)
        try await app.loadRepos()
        app.openProject("third")
        api.fail("reorderRepos", with: Broken())

        app.moveProject("third", to: 0)
        await app.savingOrder?.value
        await app.reloadingRepos?.value

        #expect(app.syncError == .transport(String(describing: Broken())))
    }

    @Test func aReorderOnAnotherDeviceReloadsTheRepos() {
        let event = Fixture.event(
            EventType.reposReordered, #"{"order": ["map-viewer", "todo-ui"]}"#, session: nil)
        #expect(event.body == .reposChanged)
    }
}
