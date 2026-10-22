import Foundation
import Security
import Synchronization
import Testing

@testable import NestKit

/// Keychain items in memory, by service and account; `failure` fails every call.
final class MemoryKeychain: KeychainItems {
    let items = Mutex<[String: Data]>([:])
    let failure = Mutex<KeychainError?>(nil)

    private func key(_ service: String, _ account: String) -> String { "\(service)|\(account)" }

    private func check() throws {
        if let failure = failure.withLock({ $0 }) {
            throw failure
        }
    }

    func read(service: String, account: String) throws -> Data? {
        try check()
        return items.withLock { $0[key(service, account)] }
    }

    func write(_ data: Data, service: String, account: String) throws {
        try check()
        items.withLock { $0[key(service, account)] = data }
    }

    func delete(service: String, account: String) throws {
        try check()
        _ = items.withLock { $0.removeValue(forKey: key(service, account)) }
    }

    func token(for url: String) -> String? {
        items.withLock { $0["nest|remote-device-token \(url)"] }.map {
            String(decoding: $0, as: UTF8.self)
        }
    }
}

@Suite struct DaemonAddressTests {
    @Test func aNameAloneMeansHTTPS() throws {
        let cases = [
            "mac-mini.tail1a2b.ts.net": "https://mac-mini.tail1a2b.ts.net",
            "  https://Mac-Mini.tail1a2b.ts.net/ ": "https://mac-mini.tail1a2b.ts.net",
            "HTTPS://mac-mini.ts.net:8443": "https://mac-mini.ts.net:8443",
            "mac-mini.ts.net:8443/": "https://mac-mini.ts.net:8443",
            "100.64.0.7": "https://100.64.0.7",
        ]
        for (text, url) in cases {
            #expect(try DaemonAddress.parse(text) == URL(string: url)!, "\(text)")
        }
    }

    /// Plain http only reaches a daemon on this Mac, such as a test daemon.
    @Test func plainHTTPIsOnlyForLoopback() throws {
        #expect(
            try DaemonAddress.parse("http://127.0.0.1:8812/") == URL(
                string: "http://127.0.0.1:8812")!)
        #expect(
            try DaemonAddress.parse("http://localhost:8812") == URL(
                string: "http://localhost:8812")!)
        #expect(try DaemonAddress.parse("http://[::1]:8812") == URL(string: "http://[::1]:8812")!)
        #expect(throws: DaemonAddressError.insecure) {
            try DaemonAddress.parse("http://mac-mini.tail1a2b.ts.net")
        }
    }

    @Test func refusesWhatIsNotAPlainAddress() {
        let cases: [(String, DaemonAddressError)] = [
            ("", .empty), ("   ", .empty),
            ("ftp://mac-mini.ts.net", .scheme), ("ws://127.0.0.1:8812", .scheme),
            ("https://user:pw@mac-mini.ts.net", .credentials),
            ("https://user@mac-mini.ts.net", .credentials),
            ("https://mac-mini.ts.net/api", .extra), ("https://mac-mini.ts.net/?a=1", .extra),
            ("https://mac-mini.ts.net/#x", .extra),
            ("https://", .invalid), ("mac mini", .invalid),
            ("https://mac-mini.ts.net:port", .invalid),
            ("https://mac%20mini", .invalid),
        ]
        for (text, error) in cases {
            #expect(throws: error, "\(text)") { try DaemonAddress.parse(text) }
        }
    }

    @Test func eachRefusalSaysWhatToFix() {
        let errors: [DaemonAddressError] = [
            .empty, .invalid, .scheme, .insecure, .credentials, .extra,
        ]
        let messages = errors.map(\.message)
        #expect(Set(messages).count == errors.count)
        #expect(messages.allSatisfy { !$0.isEmpty && !$0.contains("\u{2014}") })
        #expect(DaemonAddressError.insecure.errorDescription == DaemonAddressError.insecure.message)
    }

    @Test func showsAnAddressWithoutItsScheme() {
        #expect(DaemonAddress.display(URL(string: "https://mac-mini.ts.net")!) == "mac-mini.ts.net")
        #expect(DaemonAddress.display(URL(string: "http://127.0.0.1:8765")!) == "127.0.0.1:8765")
    }
}

@Suite struct KeychainTokenStoreTests {
    let keychain = MemoryKeychain()
    let url = URL(string: "https://mac-mini.ts.net")!

    @Test func savesReadsAndDeletesOneItemPerDaemon() throws {
        let store = KeychainTokenStore(baseURL: url, items: keychain)
        let other = KeychainTokenStore(
            baseURL: URL(string: "https://studio.ts.net")!, items: keychain)
        #expect(store.account == "remote-device-token https://mac-mini.ts.net")
        #expect(try store.deviceToken() == nil)

        try store.save("tok-1")
        try other.save("tok-2")
        #expect(try store.deviceToken() == "tok-1")
        try store.save("tok-3")
        #expect(try store.deviceToken() == "tok-3")
        #expect(try other.deviceToken() == "tok-2")

        try store.delete()
        #expect(try store.deviceToken() == nil)
        #expect(try other.deviceToken() == "tok-2")
    }

    @Test func aStoredValueThatIsNotATokenIsRefused() throws {
        let store = KeychainTokenStore(baseURL: url, items: keychain)
        try keychain.write(Data([0xff, 0xfe]), service: "nest", account: store.account)
        #expect(throws: TokenStoreError.malformed) { try store.deviceToken() }
        try keychain.write(Data("  \n".utf8), service: "nest", account: store.account)
        #expect(try store.deviceToken() == nil)
    }

    @Test func keychainFailuresAreThrown() {
        keychain.failure.withLock { $0 = KeychainError(status: errSecInteractionNotAllowed) }
        let store = KeychainTokenStore(baseURL: url, items: keychain)
        #expect(throws: KeychainError(status: errSecInteractionNotAllowed)) {
            try store.deviceToken()
        }
    }

    @Test func statusesBecomeErrorsWithTheSystemsWords() throws {
        try SystemKeychain.check(errSecSuccess)
        #expect(throws: KeychainError(status: errSecAuthFailed)) {
            try SystemKeychain.check(errSecAuthFailed)
        }
        let message = KeychainError(status: errSecAuthFailed).message
        #expect(message.hasPrefix("the Keychain refused: "))
        #expect(KeychainError(status: errSecAuthFailed).errorDescription == message)
        #expect(KeychainError(status: -999_999).message.contains("-999999"))
    }

    /// The login Keychain itself, under a service of its own that is removed again.
    @Test func roundTripsThroughTheLoginKeychain() throws {
        let service = "nest-test-\(UUID().uuidString)"
        let store = KeychainTokenStore(service: service, baseURL: url, items: SystemKeychain())
        defer { try? store.delete() }
        #expect(try store.deviceToken() == nil)
        try store.save("first")
        #expect(try store.deviceToken() == "first")
        try store.save("second")
        #expect(try store.deviceToken() == "second")
        try store.delete()
        #expect(try store.deviceToken() == nil)
        try store.delete()
    }

    @Test func thePublicStoreUsesTheNestService() {
        let store = KeychainTokenStore(baseURL: url)
        #expect(store.service == "nest")
        #expect(store.items is SystemKeychain)
    }
}

@MainActor
@Suite struct DaemonListTests {
    let defaults = MemoryStore()
    let keychain = MemoryKeychain()
    let local = DaemonLocation(environment: [:])
    let paired = Date(timeIntervalSince1970: 1_792_598_000)

    func list() -> DaemonList {
        DaemonList(local: local, store: defaults, keychain: keychain)
    }

    func remote(_ url: String, machine: String = "Mac mini", device: String = "dev-air")
        -> RemoteDaemon
    {
        RemoteDaemon(
            machine: machine, baseURL: URL(string: url)!, deviceID: device,
            deviceName: "MacBook Air", pairedAt: paired)
    }

    @Test func startsWithThisMacOnly() {
        let daemons = list()
        #expect(daemons.remotes.isEmpty)
        #expect(daemons.selected == nil)
        #expect(daemons.selection == .local)
        #expect(daemons.local == local)
    }

    @Test func addsSelectsAndPersistsRemotes() throws {
        let daemons = list()
        let mini = daemons.save(remote("https://mac-mini.ts.net"))
        let studio = daemons.save(remote("https://studio.ts.net", machine: "Studio"))
        #expect(daemons.remotes.map(\.machine) == ["Mac mini", "Studio"])
        daemons.select(studio.id)
        #expect(daemons.selection == .remote(studio))

        let again = list()
        #expect(again.remotes == [mini, studio])
        #expect(again.selection == .remote(studio))
        #expect(again.remote(mini.id) == mini)
        daemons.select(nil)
        #expect(list().selection == .local)
    }

    /// Pairing again the same address (after a revoke) keeps its entry and id.
    @Test func theSameAddressReplacesItsEntry() {
        let daemons = list()
        let first = daemons.save(remote("https://mac-mini.ts.net"))
        let second = daemons.save(
            remote("https://mac-mini.ts.net", machine: "Mini", device: "dev-2"))
        #expect(second.id == first.id)
        #expect(daemons.remotes == [second])
        #expect(second.deviceID == "dev-2")
    }

    @Test func aSelectionNamingAMissingRemoteMeansThisMac() {
        defaults.set(#"{"remotes": [], "selected": "gone"}"#, forKey: DaemonList.key)
        #expect(list().selection == .local)
        defaults.set("not json", forKey: DaemonList.key)
        #expect(list().remotes.isEmpty)
        let daemons = list()
        daemons.select("gone")
        #expect(daemons.selection == .local)
    }

    @Test func removeDeletesTheEntryAndItsToken() throws {
        let daemons = list()
        let mini = daemons.save(remote("https://mac-mini.ts.net"))
        let studio = daemons.save(remote("https://studio.ts.net", machine: "Studio"))
        try KeychainTokenStore(baseURL: mini.baseURL, items: keychain).save("tok")
        daemons.select(mini.id)

        try daemons.remove(mini.id)
        #expect(daemons.remotes == [studio])
        #expect(daemons.selection == .local)
        #expect(keychain.token(for: "https://mac-mini.ts.net") == nil)
        #expect(list().remotes == [studio])

        daemons.select(studio.id)
        try daemons.remove("unknown")
        #expect(daemons.selection == .remote(studio))
    }

    @Test func removeForgetsTheDaemonsTabsAndPanes() throws {
        let daemons = list()
        let mini = daemons.save(remote("https://mac-mini.ts.net"))
        let studio = daemons.save(remote("https://studio.ts.net", machine: "Studio"))
        PrefixedStore(defaults, prefix: mini.preferencesPrefix).set("[]", forKey: "projects.open")
        PrefixedStore(defaults, prefix: studio.preferencesPrefix).set("[]", forKey: "projects.open")
        defaults.set("[]", forKey: "projects.open")

        try daemons.remove(mini.id)
        #expect(defaults.string(forKey: mini.preferencesPrefix + "projects.open") == nil)
        #expect(defaults.string(forKey: studio.preferencesPrefix + "projects.open") == "[]")
        #expect(defaults.string(forKey: "projects.open") == "[]")
    }

    @Test func aKeychainFailureOnRemoveIsThrownAfterTheEntryGoes() {
        let daemons = list()
        let mini = daemons.save(remote("https://mac-mini.ts.net"))
        keychain.failure.withLock { $0 = KeychainError(status: errSecAuthFailed) }
        #expect(throws: KeychainError(status: errSecAuthFailed)) { try daemons.remove(mini.id) }
        #expect(daemons.remotes.isEmpty)
    }

    @Test func aConnectRecordsTheMachineAndTime() {
        let daemons = list()
        let mini = daemons.save(remote("https://mac-mini.ts.net"))
        let now = paired.addingTimeInterval(60)
        daemons.seen(mini.id, machine: "Mac mini 2", at: now)
        #expect(daemons.remote(mini.id)?.machine == "Mac mini 2")
        #expect(list().remote(mini.id)?.lastConnected == now)
        daemons.seen("unknown", machine: "X", at: now)
        #expect(daemons.remotes.count == 1)
    }

    @Test func tokensComeFromTheKeychainItemOfTheDaemon() throws {
        let daemons = list()
        let mini = daemons.save(remote("https://mac-mini.ts.net"))
        try daemons.tokens(for: mini).save("tok")
        #expect(keychain.token(for: "https://mac-mini.ts.net") == "tok")
    }

    @Test func thePublicListReadsUserDefaults() {
        let suite = "nest-test-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let daemons = DaemonList(local: local, defaults: defaults)
        #expect(daemons.keychain is SystemKeychain)
        #expect(daemons.remotes.isEmpty)
    }
}

@Suite struct PrefixedStoreTests {
    @Test func keepsItsKeysApart() {
        let base = MemoryStore(["projects.open": "local"])
        let store = PrefixedStore(base, prefix: "daemon.x.")
        #expect(store.string(forKey: "projects.open") == nil)
        store.set("remote", forKey: "projects.open")
        #expect(base.values == ["projects.open": "local", "daemon.x.projects.open": "remote"])
        #expect(store.string(forKey: "projects.open") == "remote")
    }

    @Test func removesOnlyItsOwnKeys() {
        let base = MemoryStore([
            "projects.open": "local", "daemon.x.projects.open": "x", "daemon.y.projects.open": "y",
        ])
        PrefixedStore(base, prefix: "daemon.x.").removeAll(prefixed: "projects.")
        #expect(base.values == ["projects.open": "local", "daemon.y.projects.open": "y"])
    }

    @Test func userDefaultsRemovesKeysByPrefix() {
        let suite = "nest-test-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = UserDefaultsStore(defaults: defaults)
        store.set("x", forKey: "daemon.x.projects.open")
        store.set("local", forKey: "projects.open")
        store.removeAll(prefixed: "daemon.x.")
        #expect(store.string(forKey: "daemon.x.projects.open") == nil)
        #expect(store.string(forKey: "projects.open") == "local")
    }

    @Test func aRemoteKeepsItsPreferencesUnderItsID() {
        let daemon = RemoteDaemon(
            id: "abc", machine: "Mac mini", baseURL: URL(string: "https://m.ts.net")!,
            deviceID: "d", deviceName: "Air", pairedAt: Date(timeIntervalSince1970: 0))
        #expect(daemon.preferencesPrefix == "daemon.abc.")
    }
}
