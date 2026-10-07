import Foundation
import Security
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

@Suite struct KeychainTokenStoreTests {
    @Test func queriesTheDaemonsGenericPassword() throws {
        let seen = Mutex<[String: String]>([:])
        let store = KeychainTokenStore(service: "harness", account: "local-device-token") {
            query, result in
            let dictionary = query as NSDictionary
            seen.withLock {
                $0["class"] = dictionary[kSecClass] as? String
                $0["service"] = dictionary[kSecAttrService] as? String
                $0["account"] = dictionary[kSecAttrAccount] as? String
                $0["data"] = (dictionary[kSecReturnData] as? Bool).map(String.init)
            }
            result?.pointee = Data("tok-abc".utf8) as CFData
            return errSecSuccess
        }

        #expect(try store.deviceToken() == "tok-abc")
        #expect(
            seen.withLock { $0 } == [
                "class": kSecClassGenericPassword as String, "service": "harness",
                "account": "local-device-token", "data": "true",
            ])
    }

    @Test func missingItemMeansNoToken() throws {
        let store = KeychainTokenStore(service: "s", account: "a") { _, _ in errSecItemNotFound }
        #expect(try store.deviceToken() == nil)
    }

    @Test func otherKeychainErrorsThrow() {
        let store = KeychainTokenStore(service: "s", account: "a") { _, _ in errSecAuthFailed }
        #expect(throws: TokenStoreError.keychain(errSecAuthFailed)) { try store.deviceToken() }
    }

    @Test func dataThatIsNotTextThrows() {
        let store = KeychainTokenStore(service: "s", account: "a") { _, result in
            result?.pointee = Data([0xFF, 0xFE]) as CFData
            return errSecSuccess
        }
        #expect(throws: TokenStoreError.notText) { try store.deviceToken() }
    }

    /// Reads the real Keychain for an item that cannot exist; nothing is written.
    @Test func realKeychainReportsAMissingItem() throws {
        let store = KeychainTokenStore(
            service: "harness-tests-\(UUID().uuidString)", account: "none",
            copyMatching: SecItemCopyMatching)
        #expect(try store.deviceToken() == nil)
    }

    @Test func defaultsToTheDaemonsItem() {
        let store = KeychainTokenStore()
        #expect(store.service == "harness")
        #expect(store.account == "local-device-token")
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
