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

        source.continuation.yield(.connected(resumed: false))
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

    @Test func aConnectThatDidNotResumeCatchesUpTranscriptsAndFailedLoadsRetry() async throws {
        func message(_ id: Int, _ session: String) -> Event {
            Fixture.event(
                EventType.sessionUserMessage, #"{"text": "m\#(id)", "attachments": []}"#,
                id: id, session: session)
        }
        api.set { $0.events = ["s1": [message(1, "s1")], "s2": [message(1, "s2")]] }
        let open = model.transcripts.transcript(for: "s1")
        try await open.load()
        let chat = model.transcripts.transcript(for: ClaudeChat.panePrefix + "c1")
        try await chat.load()
        let failed = model.transcripts.transcript(for: "s2")
        api.fail("sessionEvents")
        await #expect(throws: APIError.self) { try await failed.load() }
        api.set {
            $0.failures = [:]
            $0.events["s1"]?.append(message(2, "s1"))
        }
        let run = Task { await model.live.run() }

        // A resumed stream replays what it missed; only the failed load runs again.
        source.continuation.yield(.connected(resumed: true))
        try await waitFor { failed.isLoaded }
        #expect(failed.lastEventID == 1)
        #expect(open.lastEventID == 1)

        // Otherwise events published meanwhile never arrive, so loaded session transcripts
        // fetch the ones after their newest; Claude Code chats reload on their own.
        source.continuation.yield(.connected(resumed: false))
        try await waitFor { open.lastEventID == 2 }
        #expect(api.calls.filter { $0.hasPrefix("claudeChatEvents") }.count == 1)
        source.continuation.finish()
        await run.value
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

    @Test func pixiesLoadOnConnectAndFollowEvents() async throws {
        api.set { $0.pixies = [Fixture.decode(Pixie.self, "pixie")] }
        await model.live.refresh()
        #expect(model.pixies.pixies.map(\.id) == ["p1"])

        model.live.route(Fixture.event(EventType.pixieDeleted, #"{"pixie_id": "p1"}"#))
        #expect(model.pixies.pixies.isEmpty)
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

    @Test func aRetryAfterTheTokenWasRefusedReadsTheKeychainAgain() async throws {
        let keychain = ChangingTokens("old")
        let model = try #require(try await AppModel.local(tokens: keychain))
        let client = try #require(model.api as? APIClient)
        let stream = try #require(model.live.source as? EventStream)
        keychain.token.withLock { $0 = "new" }

        // Only a refused token is read again.
        try await model.rereadTokenIfRefused()
        #expect(client.token == "old")

        model.app.connection = .unauthorized
        try await model.rereadTokenIfRefused()
        #expect(client.token == "new")
        #expect(stream.request().value(forHTTPHeaderField: "Authorization") == "Bearer new")

        // A token gone from the Keychain leaves the last one in use.
        keychain.token.withLock { $0 = nil }
        try await model.rereadTokenIfRefused()
        #expect(stream.token == "new")
        // The Keychain may show a prompt, so it is never read on the main thread (BUG-81).
        #expect(keychain.readsOnMain.withLock { $0 } == [false, false, false])
    }

    @Test func aModelWithoutTheKeychainKeepsItsToken() async throws {
        model.app.connection = .unauthorized
        try await model.rereadTokenIfRefused()
        #expect(model.app.connection == .unauthorized)
    }

    @Test func theLocalModelReadsTheKeychainToken() async throws {
        #expect(try await AppModel.local(tokens: TokenStub(token: nil)) == nil)
        let model = try #require(try await AppModel.local(tokens: TokenStub(token: "tok")))
        let client = try #require(model.api as? APIClient)
        #expect(client.token == "tok")
        #expect(client.baseURL == APIClient.defaultBaseURL)
        #expect((model.live.source as? EventStream)?.token == "tok")
        #expect(model.settings.store is UserDefaultsStore)
    }

    @Test func connectingRunsTheLiveSync() async throws {
        #expect(await model.connect() == nil)
        source.continuation.yield(.connected(resumed: false))
        try await waitFor { model.app.connection == .connected }
    }

    /// A token the Keychain cannot give is reported, and the connection still runs with
    /// the one in use.
    @Test func aRetryWhoseKeychainReadFailsStillConnects() async throws {
        let keychain = ChangingTokens("old")
        keychain.failure.withLock { $0 = .keychain(-25293) }
        model.keychain = (keychain, DeviceToken("old"))
        model.app.connection = .unauthorized

        let failure = await model.connect()

        #expect(failure as? TokenStoreError == .keychain(-25293))
        source.continuation.yield(.connected(resumed: false))
        try await waitFor { model.app.connection == .connected }
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
