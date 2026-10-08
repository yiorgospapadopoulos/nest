import Foundation
import Synchronization

/// Waits between reconnect attempts; tests use a fake that returns at once.
public protocol Sleeper: Sendable {
    func sleep(seconds: Double) async throws
}

public struct TaskSleeper: Sleeper {
    public init() {}

    public func sleep(seconds: Double) async throws {
        try await Task.sleep(for: .seconds(seconds))
    }
}

/// Capped exponential backoff: `initial`, doubled per failed attempt, at most `maximum`.
public struct Backoff: Sendable, Equatable {
    public var initial: Double
    public var maximum: Double

    public init(initial: Double = 0.5, maximum: Double = 30) {
        self.initial = initial
        self.maximum = maximum
    }

    /// The delay before reconnect attempt `attempt` (1 for the first retry).
    public func delay(attempt: Int) -> Double {
        min(maximum, initial * pow(2, Double(max(0, attempt - 1))))
    }
}

public enum EventStreamUpdate: Sendable, Equatable {
    /// Connected; `resumed` when the daemon replays what was missed since the last stored
    /// event seen. Without it, events published while disconnected never arrive.
    case connected(resumed: Bool)
    case event(Event)
    /// The socket dropped; the stream reconnects after `delay` seconds.
    case reconnecting(attempt: Int, delay: Double)
}

/// Ends the stream: retrying cannot help.
public enum EventStreamError: Error, Sendable, Equatable {
    /// The daemon rejected the device token (close code 4401).
    case unauthorized
    /// The daemon refused the connection's origin (close code 4403).
    case forbiddenOrigin
}

/// Something that delivers the daemon's live updates; `LiveSync` consumes it.
public protocol EventSource: Sendable {
    func updates() -> AsyncThrowingStream<EventStreamUpdate, any Error>
}

/// The daemon's websocket event stream. It resumes after the last stored event it saw,
/// reconnects with backoff, and stops when the token or origin is rejected.
public final class EventStream: EventSource {
    public static let unauthenticatedCloseCode = 4401
    public static let forbiddenOriginCloseCode = 4403

    let baseURL: URL
    let deviceToken: DeviceToken
    let connector: any WebSocketConnector
    let sleeper: any Sleeper
    let backoff: Backoff
    private let cursor: Cursor

    public convenience init(
        token: String, baseURL: URL = APIClient.defaultBaseURL,
        connector: any WebSocketConnector = URLSessionWebSocketConnector(),
        sleeper: any Sleeper = TaskSleeper(), backoff: Backoff = Backoff(), after: Int? = nil
    ) {
        self.init(
            token: DeviceToken(token), baseURL: baseURL, connector: connector, sleeper: sleeper,
            backoff: backoff, after: after)
    }

    init(
        token: DeviceToken, baseURL: URL,
        connector: any WebSocketConnector = URLSessionWebSocketConnector(),
        sleeper: any Sleeper = TaskSleeper(), backoff: Backoff = Backoff(), after: Int? = nil
    ) {
        deviceToken = token
        self.baseURL = baseURL
        self.connector = connector
        self.sleeper = sleeper
        self.backoff = backoff
        self.cursor = Cursor(after)
    }

    var token: String { deviceToken.current }

    /// The id of the last stored event received; reconnects replay from there.
    public var lastEventID: Int? { cursor.value }

    public func updates() -> AsyncThrowingStream<EventStreamUpdate, any Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    try await run(continuation)
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    func request() -> URLRequest {
        var components = URLComponents(
            url: baseURL.appending(path: "api/events"), resolvingAgainstBaseURL: false)!
        components.scheme = components.scheme == "https" ? "wss" : "ws"
        if let after = cursor.value {
            components.queryItems = [URLQueryItem(name: "after", value: "\(after)")]
        }
        var request = URLRequest(url: components.url!)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        return request
    }

    /// Runs until cancelled; throws only when the daemon refuses the connection.
    private func run(
        _ continuation: AsyncThrowingStream<EventStreamUpdate, any Error>.Continuation
    ) async throws {
        var attempt = 0
        while !Task.isCancelled {
            do {
                let resumed = cursor.value != nil
                let connection = try await connector.connect(request())
                defer { connection.close() }
                attempt = 0
                continuation.yield(.connected(resumed: resumed))
                while true {
                    // URLSessionWebSocketTask.receive() ignores task cancellation; closing
                    // the socket ends it.
                    let text = try await withTaskCancellationHandler {
                        try await connection.receive()
                    } onCancel: {
                        connection.close()
                    }
                    if let event = read(text) {
                        continuation.yield(.event(event))
                    }
                }
            } catch let closed as WebSocketClosed {
                if let error = Self.terminalError(closeCode: closed.code) {
                    throw error
                }
            } catch {
                // Dropped, refused or cancelled.
            }
            guard !Task.isCancelled else { break }
            attempt += 1
            let delay = backoff.delay(attempt: attempt)
            continuation.yield(.reconnecting(attempt: attempt, delay: delay))
            // A cancelled sleep ends the loop through its condition.
            try? await sleeper.sleep(seconds: delay)
        }
    }

    /// Close codes that end the stream; any other close, such as 1013 (try again later),
    /// reconnects.
    static func terminalError(closeCode: Int) -> EventStreamError? {
        switch closeCode {
        case unauthenticatedCloseCode: .unauthorized
        case forbiddenOriginCloseCode: .forbiddenOrigin
        default: nil
        }
    }

    /// A frame that is not an event is skipped rather than ending the stream.
    private func read(_ text: String) -> Event? {
        guard let event = try? HarnessJSON.decoder.decode(Event.self, from: Data(text.utf8)) else {
            return nil
        }
        if let id = event.id {
            cursor.advance(to: id)
        }
        return event
    }
}

/// The resume cursor, shared between the stream's task and readers.
private final class Cursor: Sendable {
    private let state: Mutex<Int?>

    init(_ value: Int?) {
        state = Mutex(value)
    }

    var value: Int? { state.withLock { $0 } }

    func advance(to id: Int) {
        state.withLock { $0 = max($0 ?? id, id) }
    }
}
