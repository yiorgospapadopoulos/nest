import Foundation
import Synchronization

@testable import NestKit

/// A scripted `URLSessionWebSocketTask` stand-in that behaves like the real one: a
/// receive waits for a frame and fails once the server closed the socket or the task was
/// cancelled; after the server closed, the pong never comes.
final class FakeWebSocketTask: WebSocketTask {
    struct State {
        var frames: [URLSessionWebSocketTask.Message] = []
        /// The server closed the socket with this code; `.invalid` while it is open.
        var closeCode: URLSessionWebSocketTask.CloseCode = .invalid
        var closeReason: Data?
        var pingError: URLError?
        /// The pong never comes; only cancelling the task calls the handler.
        var pingHangs = false
        var pendingPing: (@Sendable ((any Error)?) -> Void)?
        var receiver: CheckedContinuation<URLSessionWebSocketTask.Message, any Error>?
        var resumed = false
        var cancelledWith: URLSessionWebSocketTask.CloseCode?
        var pings = 0

        /// Why a receive fails now, if it does.
        var failure: URLError? {
            if cancelledWith != nil {
                return URLError(.cancelled)
            }
            return closeCode != .invalid ? URLError(.networkConnectionLost) : nil
        }
    }

    let state = Mutex(State())

    var closeCode: URLSessionWebSocketTask.CloseCode { state.withLock { $0.closeCode } }
    var closeReason: Data? { state.withLock { $0.closeReason } }

    func resume() {
        state.withLock { $0.resumed = true }
    }

    func receive() async throws -> URLSessionWebSocketTask.Message {
        try await withCheckedThrowingContinuation { continuation in
            let answer: Result<URLSessionWebSocketTask.Message, URLError>? = state.withLock {
                state in
                if !state.frames.isEmpty {
                    return .success(state.frames.removeFirst())
                }
                if let failure = state.failure {
                    return .failure(failure)
                }
                state.receiver = continuation
                return nil
            }
            if let answer {
                continuation.resume(with: answer)
            }
        }
    }

    func sendPing(pongReceiveHandler: @escaping @Sendable ((any Error)?) -> Void) {
        let (answered, error): (Bool, (any Error)?) = state.withLock { state in
            state.pings += 1
            if state.cancelledWith != nil {
                return (true, URLError(.cancelled))
            }
            guard state.pingHangs || state.closeCode != .invalid else {
                return (true, state.pingError)
            }
            state.pendingPing = pongReceiveHandler
            return (false, nil)
        }
        if answered {
            pongReceiveHandler(error)
        }
    }

    func cancel(with closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        let (ping, receiver) = state.withLock { state in
            state.cancelledWith = closeCode
            defer {
                state.pendingPing = nil
                state.receiver = nil
            }
            return (state.pendingPing, state.receiver)
        }
        ping?(URLError(.cancelled))
        receiver?.resume(throwing: URLError(.cancelled))
    }

    /// A frame from the server.
    func send(_ message: URLSessionWebSocketTask.Message) {
        let receiver = state.withLock { state in
            defer { state.receiver = nil }
            if state.receiver == nil {
                state.frames.append(message)
            }
            return state.receiver
        }
        receiver?.resume(returning: message)
    }

    /// The server closes the socket, as the daemon does with 4401 right after accepting.
    func serverCloses(code: Int, reason: String? = nil) {
        let receiver = state.withLock { state in
            state.closeCode = URLSessionWebSocketTask.CloseCode(rawValue: code)!
            state.closeReason = reason.map { Data($0.utf8) }
            defer { state.receiver = nil }
            return state.receiver
        }
        receiver?.resume(throwing: URLError(.networkConnectionLost))
    }
}

/// One scripted websocket: text frames, then the way it ends.
final class FakeConnection: WebSocketConnection {
    enum Ending: Sendable {
        case closed(Int)
        case dropped
        /// Waits until the socket is closed. Like `URLSessionWebSocketTask.receive()`, it
        /// ignores task cancellation.
        case hang
    }

    private struct State {
        var frames: [String]
        var closed = false
        var waiter: CheckedContinuation<Void, Never>?
    }

    private let state: Mutex<State>
    let ending: Ending

    init(_ frames: [String], then ending: Ending) {
        state = Mutex(State(frames: frames))
        self.ending = ending
    }

    var isClosed: Bool { state.withLock { $0.closed } }

    func receive() async throws -> String {
        if let frame = state.withLock({ $0.frames.isEmpty ? nil : $0.frames.removeFirst() }) {
            return frame
        }
        switch ending {
        case .closed(let code): throw WebSocketClosed(code: code, reason: nil)
        case .dropped: throw URLError(.networkConnectionLost)
        case .hang:
            await withCheckedContinuation { continuation in
                let closed = state.withLock { state in
                    if !state.closed {
                        state.waiter = continuation
                    }
                    return state.closed
                }
                if closed {
                    continuation.resume()
                }
            }
            throw URLError(.cancelled)
        }
    }

    func close() {
        state.withLock { state in
            state.closed = true
            defer { state.waiter = nil }
            return state.waiter
        }?.resume()
    }
}

/// Hands out scripted connections in order; `nil` entries refuse the connection.
final class FakeConnector: WebSocketConnector {
    private let script: Mutex<[FakeConnection?]>
    let requests = Mutex<[URLRequest]>([])

    init(_ script: [FakeConnection?]) {
        self.script = Mutex(script)
    }

    func connect(_ request: URLRequest) async throws -> any WebSocketConnection {
        requests.withLock { $0.append(request) }
        let next: FakeConnection? = script.withLock { $0.isEmpty ? nil : $0.removeFirst() }
        guard let next else {
            throw URLError(.cannotConnectToHost)
        }
        return next
    }
}

/// Records requested delays and returns at once.
final class FakeSleeper: Sleeper {
    let delays = Mutex<[Double]>([])

    func sleep(seconds: Double) async throws {
        delays.withLock { $0.append(seconds) }
        try Task.checkCancellation()
    }
}

func eventFrame(id: Int?, type: String = "session.state", session: String = "s1") -> String {
    let idJSON = id.map(String.init) ?? "null"
    return """
        {"id": \(idJSON), "type": "\(type)", "ts": "2026-10-06T09:00:00Z", "session_id": "\(session)", "payload": {"state": "running", "error": null}}
        """
}
