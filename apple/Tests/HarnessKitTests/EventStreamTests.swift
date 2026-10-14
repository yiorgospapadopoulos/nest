import Foundation
import Testing

@testable import HarnessKit

/// Collects the first `count` updates (or all, when the stream ends earlier).
func collect(
    _ stream: AsyncThrowingStream<EventStreamUpdate, any Error>, count: Int
) async throws -> [EventStreamUpdate] {
    var updates: [EventStreamUpdate] = []
    for try await update in stream {
        updates.append(update)
        if updates.count == count {
            break
        }
    }
    return updates
}

extension EventStreamUpdate {
    var event: Event? {
        if case .event(let event) = self { event } else { nil }
    }
}

@Suite struct EventStreamTests {
    let sleeper = FakeSleeper()

    func stream(_ connector: FakeConnector, after: Int? = nil, base: String? = nil) -> EventStream {
        EventStream(
            token: "tok", baseURL: base.map { URL(string: $0)! } ?? APIClient.defaultBaseURL,
            connector: connector, sleeper: sleeper, after: after)
    }

    @Test func streamsEventsAndResumesAfterTheLastStoredOne() async throws {
        let first = FakeConnection(
            [eventFrame(id: 5), eventFrame(id: nil), eventFrame(id: 6), eventFrame(id: nil)],
            then: .dropped)
        let second = FakeConnection([eventFrame(id: 7)], then: .hang)
        let connector = FakeConnector([first, second])
        let events = stream(connector)

        let updates = try await collect(events.updates(), count: 8)

        #expect(updates[0] == .connected(resumed: false))
        #expect(
            updates[1...4].map { $0.event?.type } == Array(repeating: "session.state", count: 4))
        #expect(updates[1...4].map { $0.event?.id } == [5, nil, 6, nil])
        #expect(updates[5] == .reconnecting(attempt: 1, delay: 0.5))
        // The second connect resumes after the cursor, so nothing was missed.
        #expect(updates[6] == .connected(resumed: true))
        #expect(updates[7].event?.id == 7)
        #expect(events.lastEventID == 7)
        let requests = connector.requests.withLock { $0 }
        #expect(
            requests.map { $0.url?.absoluteString } == [
                "ws://127.0.0.1:8765/api/events", "ws://127.0.0.1:8765/api/events?after=6",
            ])
        #expect(requests[0].value(forHTTPHeaderField: "Authorization") == "Bearer tok")
        #expect(first.isClosed)
    }

    @Test func startsFromAGivenCursorOverTLS() async throws {
        let connector = FakeConnector([FakeConnection([], then: .hang)])
        let events = stream(connector, after: 41, base: "https://mac.tailnet.ts.net")

        let updates = try await collect(events.updates(), count: 1)

        #expect(updates == [.connected(resumed: true)])
        #expect(events.lastEventID == 41)
        #expect(
            connector.requests.withLock { $0 }.first?.url?.absoluteString
                == "wss://mac.tailnet.ts.net/api/events?after=41")
    }

    @Test func theCursorNeverMovesBackwards() async throws {
        let connector = FakeConnector([FakeConnection([eventFrame(id: 3)], then: .hang)])
        let events = stream(connector, after: 10)
        _ = try await collect(events.updates(), count: 2)
        #expect(events.lastEventID == 10)
    }

    @Test func aRejectedTokenStopsTheStream() async {
        let connector = FakeConnector([FakeConnection([], then: .closed(4401))])
        let events = stream(connector)

        await #expect(throws: EventStreamError.unauthorized) {
            _ = try await collect(events.updates(), count: 10)
        }
        #expect(connector.requests.withLock { $0.count } == 1)
    }

    @Test func aRefusedOriginStopsTheStream() async {
        let connector = FakeConnector([FakeConnection([], then: .closed(4403))])
        await #expect(throws: EventStreamError.forbiddenOrigin) {
            _ = try await collect(stream(connector).updates(), count: 10)
        }
    }

    @Test func tryAgainLaterReconnects() async throws {
        let connector = FakeConnector([
            FakeConnection([], then: .closed(1013)), FakeConnection([], then: .hang),
        ])

        let updates = try await collect(stream(connector).updates(), count: 3)

        #expect(
            updates == [
                .connected(resumed: false), .reconnecting(attempt: 1, delay: 0.5),
                .connected(resumed: false),
            ])
    }

    @Test func backoffGrowsWhileRefusedAndResetsOnConnect() async throws {
        let connector = FakeConnector([nil, nil, nil, FakeConnection([], then: .dropped), nil])

        let updates = try await collect(stream(connector).updates(), count: 6)

        #expect(
            updates == [
                .reconnecting(attempt: 1, delay: 0.5), .reconnecting(attempt: 2, delay: 1),
                .reconnecting(attempt: 3, delay: 2), .connected(resumed: false),
                .reconnecting(attempt: 1, delay: 0.5),
                .reconnecting(attempt: 2, delay: 1),
            ])
        #expect(sleeper.delays.withLock { $0 }.prefix(5) == [0.5, 1, 2, 0.5, 1])
    }

    @Test func framesThatAreNotEventsAreSkipped() async throws {
        let connector = FakeConnector([
            FakeConnection(["not json", #"{"type": "x"}"#, eventFrame(id: 1)], then: .hang)
        ])
        let updates = try await collect(stream(connector).updates(), count: 2)
        #expect(updates[0] == .connected(resumed: false))
        #expect(updates[1].event?.id == 1)
    }

    @Test func cancellingClosesTheSocket() async throws {
        let connection = FakeConnection([eventFrame(id: 1)], then: .hang)
        _ = try await collect(stream(FakeConnector([connection])).updates(), count: 2)
        try await waitUntil { connection.isClosed }
    }

    @Test func backoffIsCapped() {
        let backoff = Backoff(initial: 1, maximum: 10)
        #expect((1...6).map(backoff.delay(attempt:)) == [1, 2, 4, 8, 10, 10])
        #expect(Backoff().delay(attempt: 0) == 0.5)
        #expect(Backoff() == Backoff(initial: 0.5, maximum: 30))
    }

    @Test func taskSleeperSleeps() async throws {
        try await TaskSleeper().sleep(seconds: 0)
    }

    @Test func defaultsUseURLSessionAndTheLocalDaemon() {
        let events = EventStream(token: "t")
        #expect(events.baseURL == APIClient.defaultBaseURL)
        #expect(events.connector is URLSessionWebSocketConnector)
        #expect(events.sleeper is TaskSleeper)
        #expect(events.lastEventID == nil)
    }
}

/// Polls a condition that becomes true on another task.
func waitUntil(_ condition: @Sendable () -> Bool) async throws {
    for _ in 0..<500 where !condition() {
        try await Task.sleep(for: .milliseconds(2))
    }
    #expect(condition())
}

@Suite struct URLSessionWebSocketConnectorTests {
    let task = FakeWebSocketTask()
    var connector: URLSessionWebSocketConnector {
        let task = task
        return URLSessionWebSocketConnector { _ in task }
    }
    let request = URLRequest(url: URL(string: "ws://127.0.0.1:8765/api/events")!)

    @Test func connectsAfterAPingAndReadsTextAndDataFrames() async throws {
        task.state.withLock { $0.frames = [.string("one"), .data(Data("two".utf8))] }

        let connection = try await connector.connect(request)

        #expect(task.state.withLock { $0.resumed })
        #expect(try await connection.receive() == "one")
        #expect(try await connection.receive() == "two")
        connection.close()
        #expect(task.state.withLock { $0.cancelledWith } == .normalClosure)
    }

    @Test func aRefusedPingReportsTheCloseCode() async {
        task.state.withLock { $0.pingError = URLError(.networkConnectionLost) }
        task.serverCloses(code: 4401, reason: "not authenticated")
        await #expect(throws: WebSocketClosed(code: 4401, reason: "not authenticated")) {
            _ = try await connector.connect(request)
        }
    }

    /// The daemon accepts, then closes with 4401 at once: the pong never comes, so the
    /// first receive's failure has to end the wait (audit BUG-54).
    @Test func aServerThatClosesBeforeThePongReportsTheCloseCode() async throws {
        task.state.withLock { $0.pingHangs = true }
        let connector = connector
        let request = request
        let connecting = Task { try await connector.connect(request) }
        try await waitUntil { task.state.withLock { $0.pendingPing != nil } }

        task.serverCloses(code: 4401, reason: "not authenticated")

        let ended = Task { _ = try? await connecting.value }
        try await waitUntil { task.state.withLock { $0.cancelledWith != nil } }
        // Releases the ping if the connect is still waiting, so a failure cannot hang.
        task.cancel(with: .goingAway, reason: nil)
        await ended.value
        await #expect(throws: WebSocketClosed(code: 4401, reason: "not authenticated")) {
            _ = try await connecting.value
        }
    }

    @Test func aServerThatClosedBeforeTheConnectReportsTheCloseCode() async {
        task.serverCloses(code: 4403)
        await #expect(throws: WebSocketClosed(code: 4403, reason: nil)) {
            _ = try await connector.connect(request)
        }
        #expect(task.state.withLock { $0.cancelledWith } == .normalClosure)
    }

    @Test func aFrameBeforeThePongShowsTheSocketIsOpenAndIsReadFirst() async throws {
        task.state.withLock { $0.pingHangs = true }
        let connector = connector
        let request = request
        let connecting = Task { try await connector.connect(request) }
        try await waitUntil { task.state.withLock { $0.pendingPing != nil } }

        task.send(.string("first"))

        let connection = try await connecting.value
        #expect(try await connection.receive() == "first")
        task.send(.string("second"))
        #expect(try await connection.receive() == "second")
        #expect(task.state.withLock { $0.cancelledWith } == nil)
    }

    @Test func aConnectThatNeverOpensTimesOut() async throws {
        task.state.withLock { $0.pingHangs = true }
        let sleeper = FakeSleeper()
        let task = task
        let request = request
        let connector = URLSessionWebSocketConnector(timeout: 7, sleeper: sleeper) { _ in task }
        let connecting = Task { try await connector.connect(request) }
        // Without the timeout the connect would wait for ever: after a while the socket is
        // closed instead, so the test fails with another error rather than hanging.
        let watchdog = Task {
            try await Task.sleep(for: .seconds(5))
            task.cancel(with: .goingAway, reason: nil)
        }
        defer { watchdog.cancel() }
        await #expect(throws: URLError(.timedOut)) { _ = try await connecting.value }
        #expect(sleeper.delays.withLock { $0 } == [7])
        #expect(task.state.withLock { $0.cancelledWith } == .normalClosure)
    }

    /// The timeout can fire before the wait for the socket starts; that answer is kept, not
    /// lost, so the connect still ends (audit BUG-103).
    @Test func anAnswerBeforeTheWaitStartsIsKept() async {
        struct Late: Error {}
        let opening = Opening()
        opening.finish(URLError(.timedOut))
        opening.finish(nil)
        // Ends a wait that missed the early answer, so the test fails instead of hanging.
        let watchdog = Task {
            try await Task.sleep(for: .seconds(5))
            opening.finish(Late())
        }
        defer { watchdog.cancel() }
        await #expect(throws: URLError(.timedOut)) {
            try await withCheckedThrowingContinuation { opening.start($0) }
        }
    }

    @Test func onlyTheFirstAnswerEndsTheWait() async throws {
        let opening = Opening()
        let waiting = Task {
            try await withCheckedThrowingContinuation { opening.start($0) }
        }
        try await waitUntil { opening.isWaiting }
        opening.finish(nil)
        opening.finish(URLError(.timedOut))
        try await waiting.value
    }

    @Test func theDefaultConnectorWaitsTenSecondsAtMost() {
        let connector = URLSessionWebSocketConnector()
        #expect(connector.timeout == 10)
        #expect(connector.sleeper is TaskSleeper)
    }

    @Test func aFailedPingWithoutACloseCodeRethrows() async {
        task.state.withLock { $0.pingError = URLError(.cannotConnectToHost) }
        await #expect(throws: URLError.self) { _ = try await connector.connect(request) }
    }

    @Test func cancellingWhileWaitingForThePongClosesTheSocket() async throws {
        task.state.withLock { $0.pingHangs = true }
        let connector = connector
        let request = request
        let connecting = Task { try await connector.connect(request) }
        try await waitUntil { task.state.withLock { $0.pendingPing != nil } }

        connecting.cancel()

        try await waitUntil { task.state.withLock { $0.cancelledWith } != nil }
        #expect(task.state.withLock { $0.cancelledWith } == .normalClosure)
        try await expectConnectFails(connecting)
    }

    @Test func aConnectCancelledBeforeThePingClosesTheSocketAtOnce() async throws {
        task.state.withLock { $0.pingHangs = true }
        let connector = connector
        let request = request
        let connecting = Task {
            withUnsafeCurrentTask { $0?.cancel() }
            return try await connector.connect(request)
        }
        try await waitUntil {
            task.state.withLock { $0.cancelledWith != nil || $0.pendingPing != nil }
        }
        #expect(task.state.withLock { $0.cancelledWith } == .normalClosure)
        try await expectConnectFails(connecting)
    }

    /// Releases a ping still waiting (only without the fix), so a failure cannot hang.
    private func expectConnectFails(_ connecting: Task<any WebSocketConnection, any Error>)
        async throws
    {
        task.cancel(with: .goingAway, reason: nil)
        await #expect(throws: URLError.self) { _ = try await connecting.value }
    }

    @Test func aServerCloseWhileReadingReportsTheCode() async throws {
        let connection = try await connector.connect(request)
        task.serverCloses(code: 1013)
        await #expect(throws: WebSocketClosed(code: 1013, reason: nil)) {
            _ = try await connection.receive()
        }
    }

    @Test func theDefaultConnectorMakesURLSessionTasks() {
        let made = URLSessionWebSocketConnector().makeTask(request)
        let task = made as? URLSessionWebSocketTask
        #expect(task?.originalRequest?.url == request.url)
        #expect(task?.maximumMessageSize == 16 * 1024 * 1024)
        task?.cancel()
    }
}
