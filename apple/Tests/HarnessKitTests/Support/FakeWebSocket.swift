import Foundation
import Synchronization

@testable import HarnessKit

/// A scripted `URLSessionWebSocketTask` stand-in.
final class FakeWebSocketTask: WebSocketTask {
    struct State {
        var frames: [Result<URLSessionWebSocketTask.Message, URLError>] = []
        var closeCode: URLSessionWebSocketTask.CloseCode = .invalid
        var closeReason: Data?
        var pingError: URLError?
        var resumed = false
        var cancelledWith: URLSessionWebSocketTask.CloseCode?
    }

    let state = Mutex(State())

    var closeCode: URLSessionWebSocketTask.CloseCode { state.withLock { $0.closeCode } }
    var closeReason: Data? { state.withLock { $0.closeReason } }

    func resume() {
        state.withLock { $0.resumed = true }
    }

    func receive() async throws -> URLSessionWebSocketTask.Message {
        try state.withLock { state in
            state.frames.isEmpty
                ? .failure(URLError(.networkConnectionLost)) : state.frames.removeFirst()
        }.get()
    }

    func sendPing(pongReceiveHandler: @escaping @Sendable ((any Error)?) -> Void) {
        pongReceiveHandler(state.withLock { $0.pingError })
    }

    func cancel(with closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        state.withLock { $0.cancelledWith = closeCode }
    }
}

/// One scripted websocket: text frames, then the way it ends.
final class FakeConnection: WebSocketConnection {
    enum Ending: Sendable {
        case closed(Int)
        case dropped
        /// Waits until the stream is cancelled.
        case hang
    }

    private let frames: Mutex<[String]>
    let ending: Ending
    let closed = Mutex(false)

    init(_ frames: [String], then ending: Ending) {
        self.frames = Mutex(frames)
        self.ending = ending
    }

    func receive() async throws -> String {
        if let frame = frames.withLock({ $0.isEmpty ? nil : $0.removeFirst() }) {
            return frame
        }
        switch ending {
        case .closed(let code): throw WebSocketClosed(code: code, reason: nil)
        case .dropped: throw URLError(.networkConnectionLost)
        case .hang:
            try await Task.sleep(for: .seconds(3600))
            return ""
        }
    }

    func close() {
        closed.withLock { $0 = true }
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
