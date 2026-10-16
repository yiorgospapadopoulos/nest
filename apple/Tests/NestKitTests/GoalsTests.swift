import Foundation
import Testing

@testable import NestKit

/// The Goals card: what each chat of the project is working towards (B47, D092).
@MainActor
@Suite struct GoalsTests {
    let api = FakeAPI()
    let store: ActivityStore

    init() {
        store = ActivityStore(api: api)
    }

    static func task(_ id: String, _ status: TaskStatus, active: String? = nil) -> TrackedTask {
        TrackedTask(
            id: id, subject: "Task \(id)", description: nil, activeForm: active, status: status)
    }

    static func at(_ minutes: Double) -> Date {
        Date(timeIntervalSince1970: 100_000 + minutes * 60)
    }

    func tasksEvent(_ session: String, _ tasks: [TrackedTask]) -> Event {
        Fixture.event(
            EventType.sessionTasks, "{\"tasks\": \(Fixture.json(tasks))}", session: session)
    }

    func ids(_ sessions: [Session]) -> [String] {
        store.goalEntries(sessions).map(\.id)
    }

    @Test func loadsTheProjectsChatsWorkingFirstThenMostRecent() async throws {
        let sessions = [
            Fixture.session("idle-new", state: .idle, updatedAt: Self.at(9)),
            Fixture.session("waiting-old", state: .waiting, updatedAt: Self.at(1)),
            Fixture.session("running-new", state: .running, updatedAt: Self.at(5)),
            Fixture.session("idle-old", state: .idle, updatedAt: Self.at(2)),
            Fixture.session("idle-plain", state: .idle, updatedAt: Self.at(8)),
            Fixture.session("dropped", state: .idle, updatedAt: Self.at(7)),
            Fixture.session("archived", state: .idle, archived: true, updatedAt: Self.at(6)),
            Fixture.session("starting", state: .starting, updatedAt: Self.at(3)),
        ]
        api.set {
            $0.goals["cv-page"] = [
                SessionGoals(sessionID: "running-new", tasks: [Self.task("1", .inProgress)]),
                SessionGoals(sessionID: "waiting-old", tasks: []),
                SessionGoals(sessionID: "starting", tasks: []),
                SessionGoals(
                    sessionID: "idle-new",
                    tasks: [Self.task("1", .completed), Self.task("2", .deleted)]),
                SessionGoals(sessionID: "idle-old", tasks: [Self.task("1", .pending)]),
                // An older daemon might list these; the card still leaves them out.
                SessionGoals(sessionID: "dropped", tasks: [Self.task("1", .deleted)]),
                SessionGoals(sessionID: "archived", tasks: [Self.task("1", .pending)]),
            ]
        }

        try await store.loadGoals(repo: "cv-page", sessions: sessions)

        #expect(api.calls == ["goals cv-page"])
        #expect(
            ids(sessions) == ["running-new", "starting", "waiting-old", "idle-new", "idle-old"])
        #expect(ids(sessions.reversed()) == ids(sessions))
        let entries = store.goalEntries(sessions)
        #expect(entries[0].session.title == "A chat")
        #expect(entries[0].goals.current?.id == "1")
        #expect(entries[1].goals.tasks.isEmpty)
        // Deleted tasks never show.
        #expect(entries[3].goals.tasks.map(\.id) == ["1"])
    }

    @Test func equalTimesKeepAStableOrder() {
        let sessions = [
            Fixture.session("a", state: .running),
            Fixture.session("b", state: .running),
        ]
        #expect(ids(sessions) == ["b", "a"])
        #expect(ids(sessions.reversed()) == ["b", "a"])
    }

    @Test func liveTaskListsAddAndRemoveIdleChats() {
        let sessions = [Fixture.session("s1", state: .idle)]
        #expect(ids(sessions).isEmpty)

        store.apply(tasksEvent("s1", [Self.task("1", .completed)]))
        #expect(ids(sessions) == ["s1"])

        // The user's next message clears the finished list.
        store.apply(tasksEvent("s1", []))
        #expect(ids(sessions).isEmpty)

        store.apply(tasksEvent("s1", [Self.task("1", .deleted)]))
        #expect(ids(sessions).isEmpty)
    }

    @Test func aChatThatStartsWorkingJoinsWithoutAPlan() {
        var session = Fixture.session("s1", state: .idle)
        #expect(ids([session]).isEmpty)
        session.state = .running
        let entries = store.goalEntries([session])
        #expect(entries.map(\.id) == ["s1"])
        #expect(entries[0].goals.tasks.isEmpty)
    }

    @Test func aDeletedChatLeaves() {
        store.apply(tasksEvent("s1", [Self.task("1", .pending)]))
        let sessions = [Fixture.session("s1", state: .idle)]
        #expect(ids(sessions) == ["s1"])
        store.apply(
            Fixture.event(EventType.sessionDeleted, #"{"session_id": "s1"}"#, session: nil))
        #expect(ids(sessions).isEmpty)
    }

    @Test func eachProjectShowsItsOwnChats() async throws {
        let cv = [Fixture.session("c1", repo: "cv-page", state: .idle)]
        let hunter = [Fixture.session("h1", repo: "llm-hunter", state: .idle)]
        api.set {
            $0.goals["cv-page"] = [SessionGoals(sessionID: "c1", tasks: [Self.task("1", .pending)])]
            $0.goals["llm-hunter"] = [
                SessionGoals(sessionID: "h1", tasks: [Self.task("1", .completed)])
            ]
        }

        try await store.loadGoals(repo: "cv-page", sessions: cv)
        #expect(ids(cv) == ["c1"])
        #expect(ids(hunter).isEmpty)

        try await store.loadGoals(repo: "llm-hunter", sessions: hunter)
        #expect(ids(hunter) == ["h1"])
        #expect(ids(cv) == ["c1"])
        #expect(api.calls == ["goals cv-page", "goals llm-hunter"])
    }

    @Test func aReloadDropsListsClearedWhileAway() async throws {
        let sessions = [
            Fixture.session("s1", state: .idle, updatedAt: Self.at(2)),
            Fixture.session("s2", state: .idle, updatedAt: Self.at(1)),
        ]
        api.set {
            $0.goals["cv-page"] = [
                SessionGoals(sessionID: "s1", tasks: [Self.task("1", .completed)]),
                SessionGoals(sessionID: "s2", tasks: [Self.task("1", .pending)]),
            ]
        }
        try await store.loadGoals(repo: "cv-page", sessions: sessions)
        #expect(ids(sessions) == ["s1", "s2"])

        // Missed while disconnected: s1's list was cleared by the user's next message.
        api.set {
            $0.goals["cv-page"] = [
                SessionGoals(sessionID: "s2", tasks: [Self.task("1", .inProgress)])
            ]
        }
        try await store.loadGoals(repo: "cv-page", sessions: sessions)
        #expect(ids(sessions) == ["s2"])
        #expect(store.goals(session: "s2").inProgress == 1)
    }

    @Test func aFailedLoadKeepsWhatWasThere() async throws {
        let sessions = [Fixture.session("s1", state: .idle)]
        api.set {
            $0.goals["cv-page"] = [SessionGoals(sessionID: "s1", tasks: [Self.task("1", .pending)])]
        }
        try await store.loadGoals(repo: "cv-page", sessions: sessions)
        api.fail("goals")
        await #expect(throws: APIError.self) {
            try await store.loadGoals(repo: "cv-page", sessions: sessions)
        }
        #expect(ids(sessions) == ["s1"])
    }

    @Test func eventsDuringALoadApplyOnTopOfIt() async throws {
        let sessions = [Fixture.session("s1", state: .idle)]
        let (gate, open) = AsyncStream<Void>.makeStream()
        api.set {
            $0.goals["cv-page"] = [SessionGoals(sessionID: "s1", tasks: [Self.task("1", .pending)])]
            $0.gates["goals"] = gate
        }
        let loading = Task { try await store.loadGoals(repo: "cv-page", sessions: sessions) }
        try await waitFor { api.calls.count == 1 }
        // Published after the daemon read the goals: only the live copy brings it.
        store.apply(tasksEvent("s1", []))
        open.finish()
        try await loading.value
        #expect(ids(sessions).isEmpty)
    }
}
