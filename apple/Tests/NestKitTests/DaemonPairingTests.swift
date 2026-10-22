import Foundation
import Security
import Testing

@testable import NestKit

@MainActor
@Suite struct DaemonPairingTests {
    let transport = FakeTransport()
    let keychain = MemoryKeychain()
    let daemons: DaemonList
    let now = Date(timeIntervalSince1970: 1_792_598_000)

    static let health = #"{"status": "ok", "version": "0.1.0", "machine": "Mac mini"}"#
    static let redeemed = """
        {"device": {"id": "dev-air", "name": "MacBook Air", "is_local": false,
          "created_at": "2026-10-21T18:00:00Z", "last_seen_at": null, "revoked_at": null},
         "token": "tok-remote"}
        """

    init() {
        daemons = DaemonList(
            local: DaemonLocation(environment: [:]), store: MemoryStore(), keychain: keychain)
    }

    func pairing(address: String = "mac-mini.ts.net") -> DaemonPairing {
        let pairing = DaemonPairing(
            daemons: daemons, deviceName: "MacBook Air", address: address, transport: transport,
            now: { [now] in now })
        pairing.code = "k7qm-r4xp"
        return pairing
    }

    @Test func codesKeepOnlyTheirAlphabetAndLength() {
        #expect(DaemonPairing.normalize("k7qm-r4xp") == "K7QMR4XP")
        #expect(DaemonPairing.normalize("abc0o1il defghjkmnp") == "ABCDEFGH")
        let pairing = pairing()
        pairing.code = "a b-c"
        #expect(pairing.code == "ABC")
        #expect(DaemonPairing.codeLength == 8)
    }

    @Test func pairsSavesTheTokenAndSelectsTheDaemon() async throws {
        transport.reply(200, Self.health)
        transport.reply(200, Self.redeemed)
        let pairing = pairing()
        #expect(pairing.canPair)

        let daemon = try #require(await pairing.pair())
        #expect(daemon.machine == "Mac mini")
        #expect(daemon.baseURL == URL(string: "https://mac-mini.ts.net")!)
        #expect(daemon.deviceID == "dev-air")
        #expect(daemon.deviceName == "MacBook Air")
        #expect(daemon.pairedAt == now)
        #expect(daemon.lastConnected == nil)
        #expect(daemons.selection == .remote(daemon))
        #expect(keychain.token(for: "https://mac-mini.ts.net") == "tok-remote")
        #expect(pairing.found == "Mac mini")
        #expect(pairing.error == nil)
        #expect(!pairing.isBusy)

        let health = transport.requests[0]
        #expect(health.httpMethod == "GET")
        #expect(health.url?.absoluteString == "https://mac-mini.ts.net/api/health")
        #expect(health.value(forHTTPHeaderField: "Authorization") == nil)
        let redeem = transport.requests[1]
        #expect(redeem.httpMethod == "POST")
        #expect(redeem.target == "/api/pairing/redeem")
        #expect(redeem.bodyText == #"{"code":"K7QMR4XP","device_name":"MacBook Air"}"#)
        #expect(redeem.value(forHTTPHeaderField: "Authorization") == nil)
    }

    /// After a revoke on that machine: the same entry, with the new token and device.
    @Test func pairingAgainUpdatesTheToken() async throws {
        let old = daemons.save(
            RemoteDaemon(
                machine: "Old name", baseURL: URL(string: "https://mac-mini.ts.net")!,
                deviceID: "dev-old", deviceName: "Air", pairedAt: .distantPast))
        try daemons.tokens(for: old).save("tok-old")
        transport.reply(200, Self.health)
        transport.reply(200, Self.redeemed)

        let daemon = try #require(await pairing(address: "https://mac-mini.ts.net/").pair())
        #expect(daemon.id == old.id)
        #expect(daemons.remotes.count == 1)
        #expect(daemon.deviceID == "dev-air")
        #expect(keychain.token(for: "https://mac-mini.ts.net") == "tok-remote")
    }

    @Test func checkFindsTheMachineOrSaysWhy() async {
        let pairing = pairing()
        transport.reply(200, Self.health)
        await pairing.check()
        #expect(pairing.found == "Mac mini")
        #expect(pairing.foundText == "Found Nest on Mac mini")

        pairing.address = "studio.ts.net"
        #expect(pairing.found == nil)
        #expect(pairing.foundText == nil)
        transport.fail(.cannotFindHost)
        await pairing.check()
        #expect(pairing.error == "studio.ts.net did not answer at this address")

        pairing.address = "studio.ts.net"
        #expect(pairing.error == nil)
        transport.reply(404, #"{"detail": "Not Found"}"#)
        await pairing.check()
        #expect(pairing.error == "This address is not a Nest daemon")

        transport.reply(200, "<html></html>")
        await pairing.check()
        #expect(pairing.error == "This address is not a Nest daemon")

        pairing.address = "http://mac-mini.ts.net"
        await pairing.check()
        #expect(pairing.error == DaemonAddressError.insecure.message)
        #expect(transport.requests.count == 4)
    }

    /// A daemon from before B105 gives no machine name: its host stands in.
    @Test func anOlderDaemonIsNamedByItsHost() async {
        let pairing = pairing()
        transport.reply(200, #"{"status": "ok", "version": "0.1.0"}"#)
        await pairing.check()
        #expect(pairing.found == "mac-mini.ts.net")
    }

    @Test func aWrongCodeOrTooManyTriesSayWhatToDo() async {
        let pairing = pairing()
        transport.reply(200, Self.health)
        transport.reply(400, #"{"detail": "invalid or expired pairing code"}"#)
        #expect(await pairing.pair() == nil)
        #expect(pairing.error == "This code is wrong or has expired (codes last 5 minutes)")
        #expect(pairing.found == "Mac mini")

        transport.reply(200, Self.health)
        transport.reply(429, #"{"detail": "too many"}"#, headers: ["retry-after": "60"])
        #expect(await pairing.pair() == nil)
        #expect(pairing.error == "Too many tries, wait 60 s")

        transport.reply(200, Self.health)
        transport.reply(429, #"{"detail": "too many"}"#)
        #expect(await pairing.pair() == nil)
        #expect(pairing.error == "Too many tries, wait a minute")

        transport.reply(200, Self.health)
        transport.reply(500, #"{"detail": "boom"}"#)
        #expect(await pairing.pair() == nil)
        #expect(pairing.error == "boom")

        transport.reply(200, Self.health)
        transport.fail(.networkConnectionLost)
        #expect(await pairing.pair() == nil)
        #expect(pairing.error == "mac-mini.ts.net did not answer at this address")
        #expect(daemons.remotes.isEmpty)
    }

    @Test func anUnreachableAddressIsNotRedeemed() async {
        let pairing = pairing()
        transport.fail(.timedOut)
        #expect(await pairing.pair() == nil)
        #expect(transport.requests.count == 1)
    }

    @Test func aKeychainFailureKeepsTheDaemonUnsaved() async {
        let pairing = pairing()
        transport.reply(200, Self.health)
        transport.reply(200, Self.redeemed)
        keychain.failure.withLock { $0 = KeychainError(status: errSecAuthFailed) }
        #expect(await pairing.pair() == nil)
        #expect(pairing.error?.hasPrefix("Could not keep the token: the Keychain refused") == true)
        #expect(daemons.remotes.isEmpty)
    }

    @Test func pairingNeedsTheWholeForm() {
        let pairing = pairing()
        #expect(pairing.canPair)
        pairing.code = "K7QM"
        #expect(!pairing.canPair)
        pairing.code = "K7QMR4XP"
        pairing.deviceName = "  "
        #expect(!pairing.canPair)
        pairing.deviceName = "Air"
        pairing.address = " "
        #expect(!pairing.canPair)
    }

    @Test func thePublicInitTalksOverTheNetwork() {
        let pairing = DaemonPairing(daemons: daemons, deviceName: "Air")
        #expect(pairing.transport is URLSessionTransport)
        #expect(pairing.address == "")
        #expect(pairing.now().timeIntervalSinceNow < 5)
    }
}
