import Foundation
import Testing

@testable import NestKit

@MainActor
@Suite struct ActivityStoreTests {
    let api = FakeAPI()
    let store: ActivityStore
    let sessionID = Fixture.sessionDetail.id

    init() {
        store = ActivityStore(api: api)
        let detail = Fixture.sessionDetail
        api.set { $0.details[detail.id] = detail }
    }

    @Test func loadsGoalsFromTheSessionDetail() async throws {
        try await store.load(session: sessionID)

        let goals = store.goals(session: sessionID)
        #expect(
            goals.tasks.map(\.subject) == ["Add zod schema", "Show inline errors", "Write tests"])
        #expect((goals.completed, goals.inProgress, goals.pending) == (1, 1, 1))
        #expect(goals.current?.subject == "Show inline errors")
        #expect(goals.progress == 1.0 / 3)
    }

    @Test func goalsOfAnUnknownSessionAreEmpty() {
        let goals = store.goals(session: "none")
        #expect(goals.tasks.isEmpty)
        #expect(goals.progress == 0)
        #expect(goals.current == nil)
        #expect(store.agents(session: "none").isEmpty)
    }

    @Test func aDetailWithoutTrackingLoadsEmpty() async throws {
        api.set { $0.sessions = [Fixture.session("plain")] }
        try await store.load(session: "plain")
        #expect(store.goals(session: "plain").tasks.isEmpty)
        #expect(store.agents(session: "plain").isEmpty)
    }

    @Test func listsTheMainAgentFirst() async throws {
        let main = Fixture.sessionDetail.agents![0]
        let sub = Fixture.sessionDetail.agents![1]
        store.apply(
            Fixture.event(
                EventType.sessionAgents,
                "{\"agents\": [\(Fixture.json(sub)), \(Fixture.json(main))]}",
                id: nil, session: sessionID))

        let agents = store.agents(session: sessionID)

        #expect(agents.map(\.id) == ["main", "toolu_09"])
    }

    @Test func followsLiveTaskSnapshotsAndDeletion() async throws {
        try await store.load(session: sessionID)
        store.apply(
            Fixture.event(
                EventType.sessionTasks,
                #"{"tasks": [{"id": "1", "subject": "Only", "description": null, "active_form": null, "status": "completed"}, {"id": "2", "subject": "Dropped", "description": null, "active_form": null, "status": "deleted"}]}"#,
                session: sessionID))
        #expect(store.goals(session: sessionID).tasks.map(\.subject) == ["Only"])
        #expect(store.goals(session: sessionID).progress == 1)

        store.apply(Fixture.event(EventType.sessionTasks, #"{"tasks": []}"#, session: nil))
        store.apply(Fixture.event(EventType.sessionAgents, #"{"agents": []}"#, session: nil))
        store.apply(Fixture.event("daemon.started", "{}"))
        #expect(store.agents(session: sessionID).count == 2)

        store.apply(
            Fixture.event(
                EventType.sessionDeleted, "{\"session_id\": \"\(sessionID)\"}", session: nil))
        #expect(store.goals(session: sessionID).tasks.isEmpty)
        #expect(store.agents(session: sessionID).isEmpty)
    }
}

@MainActor
@Suite struct AnsweredQuestionTests {
    @Test func aQuestionWithoutAnAnswerForItIsLeftOut() {
        var approval = Fixture.approval("ap-question")
        approval.resolution = .object([
            "answers": .object(["Store branches as a DAG or a tree?": .string("Tree")])
        ])
        #expect(
            approval.answeredQuestions == [
                QuestionAnswer(question: "Store branches as a DAG or a tree?", answer: "Tree")
            ])
        #expect(Fixture.approval("ap-review").answeredQuestions.isEmpty)
    }
}
