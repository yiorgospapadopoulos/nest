import Foundation
import Synchronization
import Testing

@testable import NestKit

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
            $0.accounts = Fixture.accounts
        }
        model = AppModel(api: api, events: source, preferences: MemoryStore())
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

    /// B96: a connect reads the shown project's branch map again, and a branches event
    /// reads it and the repos (the folder's branch may have changed).
    @Test func branchMapsLoadOnConnectAndFollowEvents() async throws {
        api.set { $0.branchMaps = ["todo-ui": BranchMapFixture.map] }
        await model.branchMaps.show("todo-ui")
        await model.live.refresh()
        #expect(api.calls.filter { $0 == "repoBranchMap todo-ui" }.count == 2)

        let repos = api.calls.filter { $0 == "repos" }.count
        model.live.route(
            Fixture.event(
                EventType.repoBranchesChanged, #"{"name": "todo-ui"}"#, id: nil, session: nil))
        await model.branchMaps.refreshing?.value
        await model.app.reloadingRepos?.value
        #expect(api.calls.filter { $0 == "repoBranchMap todo-ui" }.count == 3)
        #expect(api.calls.filter { $0 == "repos" }.count == repos + 1)
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

    @Test func aRetryAfterTheTokenWasRefusedAsksTheDaemonAgain() async throws {
        let daemon = ChangingTokens("old")
        let model = try await AppModel.local(tokens: daemon)
        let client = try #require(model.api as? APIClient)
        let stream = try #require(model.live.source as? EventStream)
        daemon.token.withLock { $0 = "new" }

        // Only a refused token is read again.
        #expect(try await model.rereadToken() == false)
        #expect(client.token == "old")

        model.app.connection = .unauthorized
        #expect(try await model.rereadToken() == true)
        #expect(client.token == "new")
        #expect(stream.request().value(forHTTPHeaderField: "Authorization") == "Bearer new")

        // The same token again is no change.
        #expect(try await model.rereadToken() == false)
        // A daemon that stopped (no socket) leaves the last token in use.
        daemon.token.withLock { $0 = nil }
        #expect(try await model.rereadToken() == false)
        #expect(stream.token == "new")
        // The socket read blocks, so it never runs on the main thread (BUG-81).
        #expect(daemon.readsOnMain.withLock { $0 } == [false, false, false, false])
    }

    @Test func aModelWithoutATokenSourceKeepsItsToken() async throws {
        #expect(model.hasDeviceToken)
        model.app.connection = .unauthorized
        #expect(try await model.rereadToken() == false)
        #expect(model.app.connection == .unauthorized)
    }

    @Test func theLocalModelAsksTheDaemonForTheToken() async throws {
        let model = try await AppModel.local(tokens: TokenStub(token: "tok"))
        let client = try #require(model.api as? APIClient)
        #expect(client.token == "tok")
        #expect(client.baseURL == APIClient.defaultBaseURL)
        #expect((model.live.source as? EventStream)?.token == "tok")
        #expect(model.settings.store is UserDefaultsStore)
        #expect(model.hasDeviceToken)
    }

    /// The daemon is not running: the app starts without a token (and so shows the daemon
    /// as unreachable, with the offer to start it), then asks again on the next connect.
    @Test func aModelStartedBeforeTheDaemonAsksForTheTokenWhenConnecting() async throws {
        let daemon = ChangingTokens(nil)
        let model = try await AppModel.local(tokens: daemon)
        let client = try #require(model.api as? APIClient)
        #expect(!model.hasDeviceToken)
        #expect(client.token == "")

        daemon.token.withLock { $0 = "tok" }
        #expect(try await model.rereadToken() == true)

        #expect(client.token == "tok")
        #expect(model.hasDeviceToken)
    }

    @Test func connectingRunsTheLiveSync() async throws {
        #expect(await model.connect() == nil)
        source.continuation.yield(.connected(resumed: false))
        try await waitFor { model.app.connection == .connected }
    }

    /// A token the daemon cannot give is reported, and the connection still runs with the
    /// one in use.
    @Test func aRetryWhoseTokenReadFailsStillConnects() async throws {
        let daemon = ChangingTokens("old")
        daemon.failure.withLock { $0 = .noAnswer }
        model.tokens = (daemon, DeviceToken("old"))
        model.app.connection = .unauthorized

        let failure = await model.connect()

        #expect(failure as? TokenStoreError == .noAnswer)
        source.continuation.yield(.connected(resumed: false))
        try await waitFor { model.app.connection == .connected }
    }

    /// The daemon came up after the app, or made a new token: the refused token is asked for
    /// again, and a different one connects at once, without a Retry.
    @Test func aRefusedTokenIsAskedForAgainAndANewOneReconnects() async throws {
        let source = ReconnectingSource()
        let model = AppModel(api: api, events: source, preferences: MemoryStore())
        let daemon = ChangingTokens(nil)
        let token = DeviceToken("")
        model.tokens = (daemon, token)
        let run = Task { await model.runLive() }
        await source.until(count: 1)

        daemon.token.withLock { $0 = "tok" }
        source.latest?.finish(throwing: EventStreamError.unauthorized)
        await source.until(count: 2)
        #expect(token.current == "tok")

        source.latest?.yield(.connected(resumed: false))
        try await waitFor { model.app.connection == .connected }
        run.cancel()
        source.latest?.finish()
        await run.value
    }

    @Test func aRefusedTokenTheDaemonStillGivesStaysRefused() async throws {
        let source = ReconnectingSource()
        let model = AppModel(api: api, events: source, preferences: MemoryStore())
        model.tokens = (TokenStub(token: "same"), DeviceToken("same"))
        let run = Task { await model.runLive() }
        await source.until(count: 1)

        source.latest?.finish(throwing: EventStreamError.unauthorized)
        await run.value

        #expect(model.app.connection == .unauthorized)
        #expect(source.count == 1)
    }

    @Test func aRefusedTokenWhoseReadFailsStaysRefused() async throws {
        let source = ReconnectingSource()
        let model = AppModel(api: api, events: source, preferences: MemoryStore())
        let daemon = ChangingTokens("new")
        daemon.failure.withLock { $0 = .noAnswer }
        model.tokens = (daemon, DeviceToken("old"))
        let run = Task { await model.runLive() }
        await source.until(count: 1)

        source.latest?.finish(throwing: EventStreamError.unauthorized)
        await run.value

        #expect(model.app.connection == .unauthorized)
        #expect(source.count == 1)
    }
}

/// A source whose every `updates()` is a new stream; the test drives the latest one.
final class ReconnectingSource: EventSource {
    typealias Continuation = AsyncThrowingStream<EventStreamUpdate, any Error>.Continuation
    private let streams = Mutex<[Continuation]>([])
    private let changes = Changes()

    var count: Int { streams.withLock { $0.count } }
    var latest: Continuation? { streams.withLock { $0.last } }

    /// Ends once `count` streams were asked for.
    func until(count: Int) async {
        await changes.until { [self] in self.count >= count }
    }

    func updates() -> AsyncThrowingStream<EventStreamUpdate, any Error> {
        let (stream, continuation) = AsyncThrowingStream<EventStreamUpdate, any Error>
            .makeStream()
        streams.withLock { $0.append(continuation) }
        changes.note()
        return stream
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
