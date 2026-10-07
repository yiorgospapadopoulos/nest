import Foundation
import Testing

@testable import HarnessKit

@MainActor
@Suite struct LiveSyncTests {
    let api = FakeAPI()
    let source = ManualEventSource()
    let model: AppModel

    init() {
        let session = Fixture.session("s1", state: .running)
        let review = Fixture.approval("ap-review")
        api.set {
            $0.sessions = [session, Fixture.session(review.sessionID, title: "Dark mode contrast")]
            $0.approvals = [review]
        }
        model = AppModel(api: api, events: source, preferences: MemoryStore())
    }

    @Test func connectingLoadsEverythingAndEventsUpdateTheStores() async throws {
        let run = Task { await model.live.run() }
        #expect(model.app.connection == .disconnected || model.app.connection == .connecting)

        source.continuation.yield(.connected)
        try await waitFor { model.usage.limits != nil }
        #expect(model.app.connection == .connected)
        #expect(model.app.openProjects == ["todo-ui"])
        #expect(model.sessions.session("s1")?.state == .running)
        #expect(model.approvals.pending.count == 1)
        #expect(model.connectors.connectors.count == 3)
        #expect(model.app.syncError == nil)

        let transcript = model.transcripts.transcript(for: "s1")
        try await transcript.load()
        model.app.update { $0.openChat("s1", in: CGSize(width: 800, height: 600)) }

        var notices: [Notice] = []
        model.live.onNotice = { notices.append($0) }
        let events = [
            Fixture.event(EventType.sessionState, #"{"state": "idle", "error": null}"#, id: 1),
            Fixture.event(EventType.sessionDelta, #"{"text": "Done"}"#, id: nil),
            Fixture.event(
                EventType.sessionTasks,
                #"{"tasks": [{"id": "1", "subject": "S", "description": null, "active_form": null, "status": "completed"}]}"#,
                id: 2),
            Fixture.event(
                EventType.approvalResolved,
                "{\"approval\": \(Fixture.json(Fixture.approval("ap-review")))}", id: 3),
            Fixture.event(EventType.connectorsUpdated, #"{"connectors": []}"#, id: 4, session: nil),
            Fixture.event(
                EventType.usageUpdated,
                #"{"five_hour": {"utilization": 0.9, "resets_at": null}, "seven_day": null}"#,
                id: 5, session: nil),
            Fixture.event(
                EventType.notify,
                #"{"kind": "finished", "session_id": "s1", "repo": "todo-ui", "title": "A chat", "text": "Done"}"#,
                id: 6),
            Fixture.event(EventType.sessionDeleted, #"{"session_id": "s1"}"#, id: 7, session: nil),
        ]
        for event in events {
            source.continuation.yield(.event(event))
        }
        try await waitFor { model.sessions.session("s1") == nil }

        #expect(model.approvals.pending.isEmpty)
        #expect(model.connectors.connectors.isEmpty)
        #expect(model.usage.limits?.fiveHour?.utilization == 0.9)
        #expect(notices.map(\.kind) == [.finished])
        #expect(model.activity.goals(session: "s1").tasks.isEmpty)
        #expect(model.app.state(of: "todo-ui").layout.leaves.isEmpty)
        #expect(model.transcripts.transcript(for: "s1") !== transcript)

        source.continuation.yield(.reconnecting(attempt: 2, delay: 1))
        try await waitFor { model.app.connection == .reconnecting(attempt: 2, delay: 1) }

        source.continuation.finish()
        await run.value
        #expect(model.app.connection == .disconnected)
    }

    @Test func aRejectedTokenShowsUnauthorized() async {
        let run = Task { await model.live.run() }
        source.continuation.finish(throwing: EventStreamError.unauthorized)
        await run.value
        #expect(model.app.connection == .unauthorized)
    }

    @Test func aRefusedOriginShowsForbidden() async {
        let run = Task { await model.live.run() }
        source.continuation.finish(throwing: EventStreamError.forbiddenOrigin)
        await run.value
        #expect(model.app.connection == .forbiddenOrigin)
    }

    @Test func otherStreamErrorsShowDisconnected() async {
        let run = Task { await model.live.run() }
        source.continuation.finish(throwing: URLError(.badServerResponse))
        await run.value
        #expect(model.app.connection == .disconnected)
    }

    @Test func aFailedRefreshIsReported() async {
        api.fail("approvals", with: APIError.unauthorized("not authenticated"))
        await model.live.refresh()
        #expect(model.app.syncError == .unauthorized("not authenticated"))
        #expect(model.app.repos.count == 2)
    }

    @Test func unexpectedRefreshErrorsReadAsTransportErrors() async {
        api.fail("repos", with: CancellationError())
        await model.live.refresh()
        #expect(model.app.syncError == .transport("CancellationError()"))
    }

    @Test func noticesWithoutAHandlerAreDropped() {
        model.live.route(
            Fixture.event(
                EventType.notify,
                #"{"kind": "failed", "session_id": "s1", "repo": "r", "title": "t", "text": "x"}"#))
        #expect(model.sessions.sessions.isEmpty)
    }

    @Test func theLocalModelReadsTheKeychainToken() throws {
        #expect(try AppModel.local(tokens: TokenStub(token: nil)) == nil)
        let model = try #require(try AppModel.local(tokens: TokenStub(token: "tok")))
        let client = try #require(model.api as? APIClient)
        #expect(client.token == "tok")
        #expect(client.baseURL == APIClient.defaultBaseURL)
        #expect((model.live.source as? EventStream)?.token == "tok")
        #expect(model.settings.store is UserDefaultsStore)
    }
}

/// Polls a main-actor condition while other tasks run.
@MainActor
func waitFor(_ condition: () -> Bool) async throws {
    for _ in 0..<500 where !condition() {
        try await Task.sleep(for: .milliseconds(2))
    }
    #expect(condition())
}
