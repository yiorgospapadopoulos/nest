import Foundation
import Synchronization

/// The websocket closed; `code` is the close code (4401 means not authenticated).
public struct WebSocketClosed: Error, Sendable, Equatable {
    public let code: Int
    public let reason: String?

    public init(code: Int, reason: String?) {
        self.code = code
        self.reason = reason
    }
}

/// One open websocket that delivers text frames.
public protocol WebSocketConnection: Sendable {
    /// The next text frame; throws `WebSocketClosed` when the server closed the socket.
    func receive() async throws -> String
    func close()
}

/// Opens websockets; tests replace it with a scripted fake.
public protocol WebSocketConnector: Sendable {
    func connect(_ request: URLRequest) async throws -> any WebSocketConnection
}

/// The parts of `URLSessionWebSocketTask` the connection uses, so its handling of frames
/// and close codes can be tested without a server.
protocol WebSocketTask: AnyObject, Sendable {
    var closeCode: URLSessionWebSocketTask.CloseCode { get }
    var closeReason: Data? { get }
    func resume()
    func receive() async throws -> URLSessionWebSocketTask.Message
    func sendPing(pongReceiveHandler: @escaping @Sendable ((any Error)?) -> Void)
    func cancel(with closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?)
}

extension URLSessionWebSocketTask: WebSocketTask {}

public struct URLSessionWebSocketConnector: WebSocketConnector {
    public static let maximumMessageSize = 16 * 1024 * 1024
    /// How long opening may take, in seconds, before it counts as failed.
    public static let openTimeout: Double = 10

    let makeTask: @Sendable (URLRequest) -> any WebSocketTask
    let timeout: Double
    let sleeper: any Sleeper

    public init(session: URLSession = .shared) {
        self.init { request in
            let task = session.webSocketTask(with: request)
            // Large tool results arrive in single frames; the default limit is 1 MB.
            task.maximumMessageSize = URLSessionWebSocketConnector.maximumMessageSize
            return task
        }
    }

    init(
        timeout: Double = openTimeout, sleeper: any Sleeper = TaskSleeper(),
        makeTask: @escaping @Sendable (URLRequest) -> any WebSocketTask
    ) {
        self.timeout = timeout
        self.sleeper = sleeper
        self.makeTask = makeTask
    }

    /// Resolves once the socket shows it is open: a ping's pong, or a first frame. A
    /// server that closes right after accepting (the daemon refusing a token) never
    /// answers the ping, so the first receive failing ends the wait too, as does the
    /// timeout. The first frame is kept for the connection's first `receive()`.
    public func connect(_ request: URLRequest) async throws -> any WebSocketConnection {
        let connection = TaskConnection(task: makeTask(request))
        connection.task.resume()
        let first = connection.receiveFirst()
        let opening = Opening()
        let timer = Task { [sleeper, timeout] in
            try await sleeper.sleep(seconds: timeout)
            opening.finish(URLError(.timedOut))
        }
        defer { timer.cancel() }
        do {
            // Closing the socket ends the ping and the first receive.
            try await withTaskCancellationHandler {
                try await withCheckedThrowingContinuation {
                    (continuation: CheckedContinuation<Void, any Error>) in
                    opening.start(continuation)
                    connection.task.sendPing { error in opening.finish(error) }
                    Task {
                        do {
                            _ = try await first.value
                            opening.finish(nil)
                        } catch {
                            opening.finish(error)
                        }
                    }
                }
            } onCancel: {
                connection.close()
            }
        } catch {
            let failure = connection.closedError(or: error)
            connection.close()
            throw failure
        }
        return connection
    }
}

/// The wait for a socket to open, ended once by whichever answer comes first.
private final class Opening: Sendable {
    private let waiter = Mutex<CheckedContinuation<Void, any Error>?>(nil)

    func start(_ continuation: CheckedContinuation<Void, any Error>) {
        waiter.withLock { $0 = continuation }
    }

    func finish(_ error: (any Error)?) {
        let continuation = waiter.withLock { waiter in
            defer { waiter = nil }
            return waiter
        }
        if let error {
            continuation?.resume(throwing: error)
        } else {
            continuation?.resume()
        }
    }
}

final class TaskConnection: WebSocketConnection {
    let task: any WebSocketTask
    /// The receive started while opening, until `receive()` takes it.
    private let first = Mutex<Task<URLSessionWebSocketTask.Message, any Error>?>(nil)

    init(task: any WebSocketTask) {
        self.task = task
    }

    /// Starts the first receive, which `receive()` then answers from.
    func receiveFirst() -> Task<URLSessionWebSocketTask.Message, any Error> {
        let pending = Task { [task] in try await task.receive() }
        first.withLock { $0 = pending }
        return pending
    }

    func receive() async throws -> String {
        let message: URLSessionWebSocketTask.Message
        do {
            let pending = first.withLock { first in
                defer { first = nil }
                return first
            }
            if let pending {
                message = try await pending.value
            } else {
                message = try await task.receive()
            }
        } catch {
            throw closedError(or: error)
        }
        // The daemon sends text frames; binary frames are read as UTF-8 text.
        var text = ""
        if case .string(let value) = message {
            text = value
        }
        if case .data(let data) = message {
            text = String(decoding: data, as: UTF8.self)
        }
        return text
    }

    func close() {
        task.cancel(with: .normalClosure, reason: nil)
    }

    /// The server's close code when it closed the socket, otherwise the error itself.
    func closedError(or error: any Error) -> any Error {
        guard task.closeCode != .invalid else {
            return error
        }
        let reason = task.closeReason.map { String(decoding: $0, as: UTF8.self) }
        return WebSocketClosed(code: task.closeCode.rawValue, reason: reason)
    }
}
