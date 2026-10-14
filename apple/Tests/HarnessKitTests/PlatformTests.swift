import Foundation
import Synchronization
import Testing

@testable import HarnessKit

/// Answers URLSession requests in-process, so the real transport runs without a network.
final class StubProtocol: URLProtocol {
    static let reply = Mutex<(status: Int, headers: [String: String], body: Data)?>(nil)
    static let seen = Mutex<[URLRequest]>([])

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.seen.withLock { $0.append(request) }
        guard let reply = Self.reply.withLock({ $0 }) else {
            client?.urlProtocol(self, didFailWithError: URLError(.cannotConnectToHost))
            return
        }
        let response = HTTPURLResponse(
            url: request.url!, statusCode: reply.status, httpVersion: "HTTP/1.1",
            headerFields: reply.headers)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: reply.body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}

    static var session: URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubProtocol.self]
        return URLSession(configuration: configuration)
    }
}

@Suite(.serialized) struct URLSessionTransportTests {
    @Test func returnsStatusLowercasedHeadersAndBody() async throws {
        StubProtocol.reply.withLock {
            $0 = (429, ["Retry-After": "5", "Content-Type": "application/json"], Data("{}".utf8))
        }
        let transport = URLSessionTransport(session: StubProtocol.session)

        let response = try await transport.send(
            URLRequest(url: URL(string: "http://127.0.0.1:8765/api/health")!))

        #expect(response.status == 429)
        #expect(response.headers["retry-after"] == "5")
        #expect(response.body == Data("{}".utf8))
    }

    @Test func connectionFailuresThrow() async {
        StubProtocol.reply.withLock { $0 = nil }
        let transport = URLSessionTransport(session: StubProtocol.session)
        await #expect(throws: URLError.self) {
            _ = try await transport.send(URLRequest(url: URL(string: "http://127.0.0.1:8765/")!))
        }
    }

    @Test func defaultsToTheSharedSession() {
        #expect(URLSessionTransport().session === URLSession.shared)
    }
}

@Suite struct UserDefaultsStoreTests {
    @Test func storesAndRemovesStrings() throws {
        let suite = "harness-tests-\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = UserDefaultsStore(defaults: defaults)

        store.set("dark", forKey: "theme")
        #expect(store.string(forKey: "theme") == "dark")
        store.set(nil, forKey: "theme")
        #expect(store.string(forKey: "theme") == nil)
        #expect(UserDefaultsStore().defaults === UserDefaults.standard)
    }
}
