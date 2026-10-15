import Foundation
import Testing

@testable import NestKit

/// Stopping one background task or subagent (B59): the control waits for the task's end,
/// a task already gone refreshes the rows, and a chat with no run open hides the control.
@MainActor @Suite struct TaskStopTests {
    let api = FakeAPI()
    let store: ActivityStore
    let sessionID = Fixture.sessionDetail.id

    init() {
        store = ActivityStore(api: api)
        let detail = Fixture.sessionDetail
        api.set { $0.details[detail.id] = detail }
    }

    private func finished(_ task: String, tool: String?) -> Event {
        let toolJSON = tool.map { "\"\($0)\"" } ?? "null"
        return Fixture.event(
            EventType.sessionAgentTask,
            #"{"task_id": "\#(task)", "phase": "finished", "tool_use_id": \#(toolJSON), "status": "stopped"}"#,
            session: sessionID)
    }

    @Test func aStopWaitsForTheTasksEnd() async throws {
        #expect(store.canStop(session: sessionID))
        try await store.stop(task: "toolu_09", session: sessionID)
        #expect(api.calls.last == "stopTask \(sessionID) toolu_09")
        #expect(store.isStopping("toolu_09", session: sessionID))
        #expect(!store.isStopping("toolu_10", session: sessionID))

        // A second tap while it stops sends nothing.
        try await store.stop(task: "toolu_09", session: sessionID)
        #expect(api.calls.count { $0.hasPrefix("stopTask") } == 1)

        store.apply(finished("t1", tool: "toolu_09"))
        #expect(!store.isStopping("toolu_09", session: sessionID))
    }

    /// The end names the task by its own id when the row used it.
    @Test func theEndMatchesTheTaskIDToo() async throws {
        try await store.stop(task: "t7", session: sessionID)
        store.apply(finished("t7", tool: nil))
        #expect(!store.isStopping("t7", session: sessionID))
    }

    @Test func aTaskAlreadyGoneRefreshesTheRows() async throws {
        api.fail("stopTask", with: APIError.notFound("session 'x' has no running task 't9'"))
        try await store.stop(task: "t9", session: sessionID)
        #expect(!store.isStopping("t9", session: sessionID))
        #expect(api.calls.contains("session \(sessionID)"))
        #expect(store.canStop(session: sessionID))
    }

    @Test func aChatWithNoRunHidesTheControlUntilItRunsAgain() async throws {
        api.fail("stopTask", with: APIError.conflict("session 'x' has no agent running"))
        try await store.stop(task: "t9", session: sessionID)
        #expect(!store.canStop(session: sessionID))
        #expect(!store.isStopping("t9", session: sessionID))

        store.apply(
            Fixture.event(EventType.sessionState, #"{"state": "running"}"#, session: sessionID))
        #expect(store.canStop(session: sessionID))
    }

    @Test func otherFailuresAreReported() async throws {
        api.fail("stopTask")
        await #expect(throws: APIError.server(status: 500, detail: "boom")) {
            try await store.stop(task: "t9", session: sessionID)
        }
        #expect(!store.isStopping("t9", session: sessionID))
    }

    @Test func aDeletedSessionForgetsItsStops() async throws {
        try await store.stop(task: "t1", session: sessionID)
        api.fail("stopTask", with: APIError.conflict("no agent"))
        try await store.stop(task: "t2", session: sessionID)
        store.apply(
            Fixture.event(
                EventType.sessionDeleted, #"{"session_id": "\#(sessionID)"}"#, session: nil))
        #expect(!store.isStopping("t1", session: sessionID))
        #expect(store.canStop(session: sessionID))
    }
}
