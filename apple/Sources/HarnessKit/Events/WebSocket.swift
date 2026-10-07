import Foundation

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

    let makeTask: @Sendable (URLRequest) -> any WebSocketTask

    public init(session: URLSession = .shared) {
        self.makeTask = { request in
            let task = session.webSocketTask(with: request)
            // Large tool results arrive in single frames; the default limit is 1 MB.
            task.maximumMessageSize = URLSessionWebSocketConnector.maximumMessageSize
            return task
        }
    }

    init(makeTask: @escaping @Sendable (URLRequest) -> any WebSocketTask) {
        self.makeTask = makeTask
    }

    /// Resolves once a ping round trip shows the socket is open.
    public func connect(_ request: URLRequest) async throws -> any WebSocketConnection {
        let connection = TaskConnection(task: makeTask(request))
        connection.task.resume()
        do {
            try await withCheckedThrowingContinuation {
                (continuation: CheckedContinuation<Void, any Error>) in
                connection.task.sendPing { error in
                    if let error {
                        continuation.resume(throwing: error)
                    } else {
                        continuation.resume()
                    }
                }
            }
        } catch {
            throw connection.closedError(or: error)
        }
        return connection
    }
}

struct TaskConnection: WebSocketConnection {
    let task: any WebSocketTask

    func receive() async throws -> String {
        let message: URLSessionWebSocketTask.Message
        do {
            message = try await task.receive()
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
