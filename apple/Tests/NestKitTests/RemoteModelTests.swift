import Foundation
import Testing

@testable import NestKit

@MainActor
@Suite struct RemoteModelTests {
    let api = FakeAPI()
    let source = ManualEventSource()
    let mini = RemoteDaemon(
        id: "mini", machine: "Mac mini", baseURL: URL(string: "https://mac-mini.ts.net")!,
        deviceID: "dev-air", deviceName: "MacBook Air",
        pairedAt: Date(timeIntervalSince1970: 1_792_598_000),
        lastConnected: Date(timeIntervalSince1970: 1_792_598_100))

    static func device(_ id: String, _ name: String, local: Bool = false) -> Device {
        Device(id: id, name: name, isLocal: local, createdAt: .distantPast)
    }

    @Test func theLocalModelIsThisMac() async throws {
        let model = try await AppModel.local(tokens: TokenStub(token: "tok"))
        #expect(!model.isRemote)
        #expect(model.machineName == "This Mac")
        #expect(model.link.remote == nil)
        #expect(model.link.baseURL == nil)
        #expect(model.link.lastConnected == nil)
    }

    @Test func theRemoteModelTalksToItsDaemonWithItsToken() async throws {
        let preferences = MemoryStore(["projects.open": "local-tab"])
        let model = try await AppModel.remote(
            mini, tokens: TokenStub(token: "tok-remote"), preferences: preferences)
        let client = try #require(model.api as? APIClient)
        #expect(client.baseURL == mini.baseURL)
        #expect(client.token == "tok-remote")
        let stream = try #require(model.live.source as? EventStream)
        #expect(stream.request().url?.absoluteString == "wss://mac-mini.ts.net/api/events")
        #expect(model.isRemote)
        #expect(model.machineName == "Mac mini")
        #expect(model.link.baseURL == mini.baseURL)
        #expect(model.link.lastConnected == mini.lastConnected)
        #expect(model.devices.thisMacDevice == "dev-air")
        // Its open tabs are its own; the look of the app is shared.
        #expect(model.app.openProjects.isEmpty)
        model.app.openProject("homelab")
        #expect(preferences.values["daemon.mini.projects.open"] == "homelab")
        #expect(preferences.values["projects.open"] == "local-tab")
        #expect(model.settings.store === preferences)
    }

    /// The Keychain item may be gone: the model starts without a token, so the daemon
    /// refuses it and the banner offers to pair again.
    @Test func aRemoteWithoutATokenStartsWithoutOne() async throws {
        let model = try await AppModel.remote(mini, tokens: TokenStub(token: nil))
        #expect(!model.hasDeviceToken)
    }

    @Test func eachConnectRefreshesTheMachineName() async throws {
        api.set { $0.health = DaemonHealth(status: "ok", version: "1", machine: "Mac mini M4") }
        let now = Date(timeIntervalSince1970: 1_792_599_000)
        let model = AppModel(
            api: api, events: source, preferences: MemoryStore(), now: { now },
            link: DaemonLink(remote: mini))
        var seen: [(String, Date)] = []
        model.link.onSeen = { seen.append(($0, $1)) }
        let run = Task { await model.live.run() }
        defer { run.cancel() }

        source.continuation.yield(.connected(resumed: false))
        try await waitFor { !seen.isEmpty }
        #expect(model.machineName == "Mac mini M4")
        #expect(model.link.lastConnected == now)
        #expect(seen.first?.0 == "Mac mini M4")
        #expect(seen.first?.1 == now)
        #expect(api.calls.contains("health"))
    }

    /// An unreadable health answer keeps the saved name, and the connect still counts.
    @Test func aFailedHealthReadKeepsTheName() async throws {
        api.set { $0.failures["health"] = APIError.transport("down") }
        let model = AppModel(
            api: api, events: source, preferences: MemoryStore(), link: DaemonLink(remote: mini))
        var seen: [String] = []
        model.link.onSeen = { name, _ in seen.append(name) }
        await model.noteConnected()
        #expect(seen == ["Mac mini"])
        #expect(model.machineName == "Mac mini")
    }

    @Test func theLocalModelDoesNotAskForItsName() async {
        let model = AppModel(api: api, events: source, preferences: MemoryStore())
        await model.noteConnected()
        #expect(!api.calls.contains("health"))
        model.link.seen(machine: "x", at: .now)
        #expect(model.machineName == "This Mac")
    }

    /// Switching daemons: the old model stops its live sync and tells its daemon the app
    /// is no longer on screen there.
    @Test func closingStopsTheLiveSyncAndTheVisibility() async throws {
        let model = AppModel(api: api, events: source, preferences: MemoryStore())
        model.visibility.update(visible: true)
        await model.connect()
        source.continuation.yield(.connected(resumed: false))
        try await waitFor { model.app.connection == .connected }

        model.close()
        try await waitFor { model.app.connection == .disconnected }
        await model.visibility.flush()
        #expect(api.calls.contains("reportVisibility false mac"))
        #expect(!model.visibility.isVisible)
    }

    @Test func restartAsksTheDaemon() async throws {
        let model = AppModel(
            api: api, events: source, preferences: MemoryStore(), link: DaemonLink(remote: mini))
        try await model.restartDaemon()
        #expect(api.calls.contains("restartService"))
    }

    @Test func devicesAreNamedForTheDaemonTheyArePairedWith() {
        let local = DevicesStore(api: api)
        let daemonDevice = Self.device("dev-mini", "Mac mini (daemon)", local: true)
        let air = Self.device("dev-air", "MacBook Air")
        let phone = Self.device("dev-phone", "iPhone")
        #expect(local.title(daemonDevice) == "Mac mini (daemon)")
        #expect(local.detail(daemonDevice) == "This Mac")
        #expect(local.detail(phone) == "Not seen yet")
        #expect(!local.canRevoke(daemonDevice))
        #expect(local.canRevoke(air))
        #expect(local.pairedWith == "Paired with This Mac")

        let remote = DevicesStore(api: api, link: DaemonLink(remote: mini))
        #expect(remote.thisMacDevice == "dev-air")
        #expect(remote.title(daemonDevice) == "Mac mini")
        #expect(remote.detail(daemonDevice) == "The daemon's machine")
        #expect(remote.title(air) == "MacBook Air")
        #expect(remote.detail(air) == "This Mac")
        #expect(remote.detail(phone) == "Not seen yet")
        #expect(!remote.canRevoke(daemonDevice))
        // Revoking this Mac there would lock this app out; Remove is the way.
        #expect(!remote.canRevoke(air))
        #expect(remote.canRevoke(phone))
        #expect(remote.pairedWith == "Paired with Mac mini")
    }
}

@Suite struct DaemonTextTests {
    let calendar: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Europe/Athens")!
        return calendar
    }()

    @Test func theBannerKeepsTodaysWordsForThisMac() {
        #expect(DaemonText.banner(.connected, machine: nil) == nil)
        #expect(DaemonText.banner(.connecting, machine: nil) == nil)
        #expect(
            DaemonText.banner(.disconnected, machine: nil) == "Not connected to the Nest daemon")
        #expect(
            DaemonText.banner(.reconnecting(attempt: 2, delay: 7.2), machine: nil)
                == "Can't reach the Nest daemon. Trying again in 8s")
        #expect(
            DaemonText.banner(.reconnecting(attempt: 1, delay: 1), machine: nil)
                == "Reconnecting to the Nest daemon")
        #expect(
            DaemonText.banner(.unauthorized, machine: nil)
                == "The daemon did not accept this Mac's device token")
        #expect(
            DaemonText.banner(.forbiddenOrigin, machine: nil)
                == "The daemon refused this connection")
    }

    @Test func theBannerNamesTheRemoteMachine() {
        let mini = "Mac mini"
        #expect(DaemonText.banner(.connected, machine: mini) == nil)
        #expect(DaemonText.banner(.disconnected, machine: mini) == "Not connected to Mac mini")
        #expect(
            DaemonText.banner(.reconnecting(attempt: 3, delay: 8), machine: mini)
                == "Can't reach Mac mini. Trying again in 8s")
        #expect(
            DaemonText.banner(.reconnecting(attempt: 1, delay: 1), machine: mini)
                == "Reconnecting to Mac mini")
        #expect(
            DaemonText.banner(.unauthorized, machine: mini)
                == "Mac mini did not accept this Mac's device token")
        #expect(
            DaemonText.banner(.forbiddenOrigin, machine: mini) == "Mac mini refused this connection"
        )
    }

    @Test func theBannerOffersWhatFitsTheDaemon() {
        #expect(
            DaemonText.actions(.disconnected, remote: false, starting: false, offersStart: true)
                == [.retry, .startService])
        #expect(
            DaemonText.actions(.unauthorized, remote: false, starting: false, offersStart: false)
                == [.retry])
        #expect(
            DaemonText.actions(.disconnected, remote: false, starting: true, offersStart: false)
                == [])
        #expect(
            DaemonText.actions(.disconnected, remote: true, starting: false, offersStart: true)
                == [.retry, .useThisMac])
        #expect(
            DaemonText.actions(.unauthorized, remote: true, starting: false, offersStart: false)
                == [.pairAgain, .useThisMac])
    }

    @Test func unreachableMeansNotConnectedOrReconnecting() {
        #expect(ConnectionState.disconnected.isUnreachable)
        #expect(ConnectionState.reconnecting(attempt: 1, delay: 1).isUnreachable)
        for state in [ConnectionState.connected, .connecting, .unauthorized, .forbiddenOrigin] {
            #expect(!state.isUnreachable)
        }
    }

    @Test func theUnreachableNoteSaysWhatToCheckThere() {
        #expect(
            DaemonText.unreachableNote("Mac mini")
                == "Check that Mac mini is awake, the Nest service is running there and"
                + " `tailscale serve` is on.")
        let url = URL(string: "https://mac-mini.ts.net")!
        let seen = Date(timeIntervalSince1970: 1_792_597_320)  // 18:42 in Athens
        #expect(
            DaemonText.addressLine(url, lastConnected: seen, calendar: calendar)
                == "https://mac-mini.ts.net · last connected 18:42")
        #expect(
            DaemonText.addressLine(url, lastConnected: nil, calendar: calendar)
                == "https://mac-mini.ts.net")
    }

    @Test func theDaemonRowsSayWhereAndWhen() {
        #expect(
            DaemonText.localDetail(DaemonLocation(environment: [:]))
                == "127.0.0.1:8765 · the default")
        #expect(
            DaemonText.localDetail(
                DaemonLocation(environment: ["NEST_DAEMON_URL": "http://127.0.0.1:8812"]))
                == "http://127.0.0.1:8812")
        let mini = RemoteDaemon(
            machine: "Mac mini", baseURL: URL(string: "https://mac-mini.ts.net")!,
            deviceID: "d", deviceName: "MacBook Air",
            pairedAt: Date(timeIntervalSince1970: 1_792_598_520))
        #expect(
            DaemonText.remoteDetail(mini, calendar: calendar)
                == "https://mac-mini.ts.net · paired 21 Oct as \"MacBook Air\"")
        #expect(DaemonText.thisMac == "This Mac")
        #expect(DaemonText.removeMessage("Mac mini").contains("revoke this Mac"))
        #expect(DaemonText.removeMessage("Mac mini").contains("on Mac mini"))
        #expect(!DaemonText.daemonsNote.isEmpty)
    }

    @Test func localOnlyFeaturesSayWhyTheyAreOff() {
        #expect(
            DaemonText.appsOff("Mac mini")
                == "These open apps on the daemon's machine, so they are off while connected"
                + " to Mac mini.")
        #expect(
            DaemonText.terminalOff("Mac mini")
                == "Terminal and the browser pane's local servers run on this Mac, not on"
                + " Mac mini.")
        #expect(DaemonText.copyPath("Mac mini") == "Copy folder path on Mac mini")
        #expect(DaemonText.folder("Mac mini") == "Folder on Mac mini")
        #expect(
            DaemonText.signInNote("Mac mini")
                == "Sign in on Mac mini itself; the sign-in page opens there. In Terminal on"
                + " Mac mini run:")
        #expect(DaemonText.signInCommand(ProviderInfo.claude) == "claude auth login")
        #expect(DaemonText.signInCommand("codex") == "codex login")
    }
}
