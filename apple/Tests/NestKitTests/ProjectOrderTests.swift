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
        memory.values[AppStore.Key.openProjects] = "fourth\ncv-page\ngone"
        let app = AppStore(api: api, store: memory)
        // Before the repos load the saved order stands, and a new tab goes last.
        app.openProject("third")
        #expect(app.openProjects == ["fourth", "cv-page", "gone", "third"])

        try await app.loadRepos()
        #expect(app.openProjects == ["cv-page", "third", "fourth"])
        #expect(memory.values[AppStore.Key.openProjects] == "cv-page\nthird\nfourth")

        app.openProject("llm-hunter")
        #expect(app.openProjects == ["cv-page", "llm-hunter", "third", "fourth"])
        app.selectProject(at: 1)
        #expect(app.currentProject == "llm-hunter")
    }

    @Test func movingATabPlacesItBeforeTheTabThatFollowsIt() async throws {
        let app = AppStore(api: api, store: memory)
        try await app.loadRepos()
        app.openProject("third")
        app.openProject("fourth")
        #expect(app.openProjects == ["cv-page", "third", "fourth"])

        // llm-hunter is closed: the project moves just before the tab that follows it.
        app.moveProject("fourth", to: 0)
        #expect(app.openProjects == ["fourth", "cv-page", "third"])
        #expect(names(app.repos) == ["fourth", "cv-page", "llm-hunter", "third"])
        #expect(memory.values[AppStore.Key.openProjects] == "fourth\ncv-page\nthird")
        await app.savingOrder?.value
        #expect(api.calls.last == "reorderRepos fourth,cv-page,llm-hunter,third")

        app.selectProject(at: 0)
        #expect(app.currentProject == "fourth")
    }

    @Test func movingATabLastPlacesItAfterTheTabBeforeIt() async throws {
        let app = AppStore(api: api, store: memory)
        try await app.loadRepos()
        app.openProject("third")

        // Past the end is clamped to the last place.
        app.moveProject("cv-page", to: 9)
        #expect(app.openProjects == ["third", "cv-page"])
        #expect(names(app.repos) == ["llm-hunter", "third", "cv-page", "fourth"])
        await app.savingOrder?.value
        #expect(api.calls.last == "reorderRepos llm-hunter,third,cv-page,fourth")

        app.moveProject("cv-page", to: -3)
        #expect(app.openProjects == ["cv-page", "third"])
        #expect(names(app.repos) == ["llm-hunter", "cv-page", "third", "fourth"])
    }

    @Test func aMoveNowhereOrOfAClosedTabChangesNothing() async throws {
        let app = AppStore(api: api, store: memory)
        try await app.loadRepos()
        app.openProject("third")

        app.moveProject("third", to: 1)
        app.moveProject("llm-hunter", to: 0)
        await app.savingOrder?.value

        #expect(app.openProjects == ["cv-page", "third"])
        #expect(!api.calls.contains { $0.hasPrefix("reorderRepos") })
    }

    @Test func beforeTheReposLoadNothingMoves() {
        memory.values[AppStore.Key.openProjects] = "cv-page\nthird"
        let app = AppStore(api: api, store: memory)

        app.moveProject("third", to: 0)

        #expect(app.openProjects == ["cv-page", "third"])
        #expect(app.savingOrder == nil)
    }

    @Test func savesRunOneAtATimeInOrder() async throws {
        let (gate, open) = AsyncStream<Void>.makeStream()
        api.set { $0.gates["reorderRepos"] = gate }
        let app = AppStore(api: api, store: memory)
        try await app.loadRepos()
        app.openProject("third")

        app.moveProject("third", to: 0)
        app.moveProject("cv-page", to: 0)
        #expect(app.openProjects == ["cv-page", "third"])
        open.finish()
        await app.savingOrder?.value

        #expect(
            api.calls.filter { $0.hasPrefix("reorderRepos") } == [
                "reorderRepos third,cv-page,llm-hunter,fourth",
                "reorderRepos cv-page,third,llm-hunter,fourth",
            ])
    }

    @Test func aFailedSaveShowsTheErrorAndReloadsTheRepos() async throws {
        let app = AppStore(api: api, store: memory)
        try await app.loadRepos()
        app.openProject("third")
        api.fail("reorderRepos")

        app.moveProject("third", to: 0)
        #expect(app.openProjects == ["third", "cv-page"])
        await app.savingOrder?.value
        await app.reloadingRepos?.value

        #expect(app.syncError == .server(status: 500, detail: "boom"))
        #expect(app.openProjects == ["cv-page", "third"])
        #expect(names(app.repos) == ["cv-page", "llm-hunter", "third", "fourth"])
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
            EventType.reposReordered, #"{"order": ["llm-hunter", "cv-page"]}"#, session: nil)
        #expect(event.body == .reposChanged)
    }
}
