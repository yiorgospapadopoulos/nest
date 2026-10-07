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

        #expect(updates[0] == .connected)
        #expect(
            updates[1...4].map { $0.event?.type } == Array(repeating: "session.state", count: 4))
        #expect(updates[1...4].map { $0.event?.id } == [5, nil, 6, nil])
        #expect(updates[5] == .reconnecting(attempt: 1, delay: 0.5))
        #expect(updates[6] == .connected)
        #expect(updates[7].event?.id == 7)
        #expect(events.lastEventID == 7)
        let requests = connector.requests.withLock { $0 }
        #expect(
            requests.map { $0.url?.absoluteString } == [
                "ws://127.0.0.1:8765/api/events", "ws://127.0.0.1:8765/api/events?after=6",
            ])
        #expect(requests[0].value(forHTTPHeaderField: "Authorization") == "Bearer tok")
        #expect(first.closed.withLock { $0 })
    }

    @Test func startsFromAGivenCursorOverTLS() async throws {
        let connector = FakeConnector([FakeConnection([], then: .hang)])
        let events = stream(connector, after: 41, base: "https://mac.tailnet.ts.net")

        _ = try await collect(events.updates(), count: 1)

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

        #expect(updates == [.connected, .reconnecting(attempt: 1, delay: 0.5), .connected])
    }

    @Test func backoffGrowsWhileRefusedAndResetsOnConnect() async throws {
        let connector = FakeConnector([nil, nil, nil, FakeConnection([], then: .dropped), nil])

        let updates = try await collect(stream(connector).updates(), count: 6)

        #expect(
            updates == [
                .reconnecting(attempt: 1, delay: 0.5), .reconnecting(attempt: 2, delay: 1),
                .reconnecting(attempt: 3, delay: 2), .connected,
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
        #expect(updates[0] == .connected)
        #expect(updates[1].event?.id == 1)
    }

    @Test func cancellingClosesTheSocket() async throws {
        let connection = FakeConnection([eventFrame(id: 1)], then: .hang)
        _ = try await collect(stream(FakeConnector([connection])).updates(), count: 2)
        try await waitUntil { connection.closed.withLock { $0 } }
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
        task.state.withLock {
            $0.frames = [.success(.string("one")), .success(.data(Data("two".utf8)))]
        }

        let connection = try await connector.connect(request)

        #expect(task.state.withLock { $0.resumed })
        #expect(try await connection.receive() == "one")
        #expect(try await connection.receive() == "two")
        connection.close()
        #expect(task.state.withLock { $0.cancelledWith } == .normalClosure)
    }

    @Test func aRefusedPingReportsTheCloseCode() async {
        task.state.withLock {
            $0.pingError = URLError(.networkConnectionLost)
            $0.closeCode = URLSessionWebSocketTask.CloseCode(rawValue: 4401)!
            $0.closeReason = Data("not authenticated".utf8)
        }
        await #expect(throws: WebSocketClosed(code: 4401, reason: "not authenticated")) {
            _ = try await connector.connect(request)
        }
    }

    @Test func aFailedPingWithoutACloseCodeRethrows() async {
        task.state.withLock { $0.pingError = URLError(.cannotConnectToHost) }
        await #expect(throws: URLError.self) { _ = try await connector.connect(request) }
    }

    @Test func aServerCloseWhileReadingReportsTheCode() async throws {
        let connection = try await connector.connect(request)
        task.state.withLock { $0.closeCode = .init(rawValue: 1013)! }
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
