import Foundation
import Synchronization

@testable import HarnessKit

/// Records requests and answers them from a queue (200 with `{}` when empty).
final class FakeTransport: HTTPTransport {
    private let state = Mutex<(requests: [URLRequest], replies: [Result<HTTPResponse, URLError>])>(
        ([], []))

    func reply(_ status: Int = 200, _ body: String = "{}", headers: [String: String] = [:]) {
        state.withLock {
            $0.replies.append(
                .success(HTTPResponse(status: status, headers: headers, body: Data(body.utf8))))
        }
    }

    func reply(fixture name: String) {
        reply(200, Fixture.text(name))
    }

    func fail(_ code: URLError.Code) {
        state.withLock { $0.replies.append(.failure(URLError(code))) }
    }

    var requests: [URLRequest] { state.withLock { $0.requests } }

    var last: URLRequest { requests.last! }

    func send(_ request: URLRequest) async throws -> HTTPResponse {
        let reply = state.withLock { state in
            state.requests.append(request)
            return state.replies.isEmpty
                ? .success(HTTPResponse(status: 200, body: Data("{}".utf8)))
                : state.replies.removeFirst()
        }
        return try reply.get()
    }
}

extension URLRequest {
    /// Path and query as sent, such as `/api/sessions?archived=false`.
    var target: String {
        let components = URLComponents(url: url!, resolvingAgainstBaseURL: false)!
        let query = components.percentEncodedQuery.map { "?\($0)" } ?? ""
        return components.percentEncodedPath + query
    }

    var bodyText: String? {
        httpBody.map { String(decoding: $0, as: UTF8.self) }
    }
}
