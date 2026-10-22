import Foundation
import NestKit
import Observation
import SystemConfiguration

/// Starts the app: reads the device token, builds the stores and keeps the live
/// connection to the daemon running. The window talks to one daemon at a time, This Mac's
/// or a paired remote's (B105); switching rebuilds the window's model for the chosen one.
@MainActor @Observable
final class AppController {
    enum Phase: Equatable {
        case loading
        case ready
        case failed(String)
    }

    private(set) var phase = Phase.loading
    private(set) var shell: Shell?
    /// Starts the daemon's launchd service when the daemon cannot be reached.
    let service: ServiceStarter
    /// This Mac and the paired remotes, with the one selected.
    let daemons: DaemonList
    /// Settings > Devices' Pair a daemon sheet while it is open.
    var pairing: DaemonPairing?
    /// The device token is being asked for, for the first start.
    @ObservationIgnored private var starting = false
    @ObservationIgnored private var notifier: Notifier?
    @ObservationIgnored private var visibility: VisibilityMonitor?

    init() {
        service = .local(repoPath: Self.repositoryPath)
        daemons = DaemonList(
            local: DaemonLocation(environment: ProcessInfo.processInfo.environment))
    }

    /// A controller around a prepared shell, for snapshots.
    init(shell: Shell, service: ServiceStarter, daemons: DaemonList? = nil) {
        self.shell = shell
        self.service = service
        self.daemons =
            daemons
            ?? DaemonList(
                local: DaemonLocation(environment: [:]),
                defaults: UserDefaults(suiteName: "local.nest.snapshots") ?? .standard)
        phase = .ready
    }

    /// The Nest checkout this app was built from, for the service install command;
    /// nil once it has moved.
    static var repositoryPath: String? {
        var url = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 {
            url.deleteLastPathComponent()
        }
        let daemon = url.appending(path: "daemon/pyproject.toml").path
        return FileManager.default.fileExists(atPath: daemon) ? url.path : nil
    }

    func start() {
        if shell != nil {
            connect()
            return
        }
        guard !starting else { return }
        starting = true
        Task {
            defer { starting = false }
            await open()
        }
    }

    /// Asks the selected daemon's token store for the device token (away from the main
    /// thread) and builds the window's model. This Mac's daemon, when not running, gives
    /// none: the window opens showing it as unreachable, with the offer to start the
    /// service, and asks again on connect. `NEST_DAEMON_URL` and `NEST_DATA_DIR` may point
    /// This Mac at a test daemon.
    private func open() async {
        do {
            install(try await model(for: daemons.selection))
            phase = .ready
            connect()
        } catch {
            phase = .failed(Shell.describe(error))
        }
    }

    /// The model for a daemon: This Mac's as the launch environment says
    /// (`DaemonLocation`), with the token from its socket; a remote's with the token from
    /// its Keychain item.
    private func model(for choice: DaemonChoice) async throws -> AppModel {
        switch choice {
        case .local:
            return try await Self.localModel(daemons.local)
        case .remote(let daemon):
            let model = try await AppModel.remote(daemon, tokens: daemons.tokens(for: daemon))
            model.link.onSeen = { [daemons] machine, date in
                daemons.seen(daemon.id, machine: machine, at: date)
            }
            return model
        }
    }

    /// The model for This Mac's daemon: the default one, or the test daemon the
    /// environment names.
    static func localModel(
        _ location: DaemonLocation = DaemonLocation(
            environment: ProcessInfo.processInfo.environment)
    ) async throws -> AppModel {
        try await AppModel.local(
            tokens: SocketTokenStore(dataFolder: location.dataFolder), baseURL: location.baseURL)
    }

    /// Puts a new model in the window. The old one stops first: its live sync, its
    /// notifications and its visibility reports, and its terminal and browser panes end.
    /// The Settings window keeps its page.
    private func install(_ model: AppModel) {
        let shell = Shell(model: model)
        if let old = self.shell {
            visibility?.stop()
            old.model.close()
            old.tools.keep([])
            shell.keepSettings(of: old)
        }
        self.shell = shell
        notifier = Notifier(shell: shell)
        notifier?.start()
        visibility = VisibilityMonitor(reporter: model.visibility)
        visibility?.start()
    }

    /// Connect, Pair and connect, Use This Mac and Remove of the selected daemon: the
    /// window switches to that daemon (nil is This Mac), and so does the next launch.
    func use(_ remote: String?) {
        daemons.select(remote)
        Task { await switchDaemon() }
    }

    private func switchDaemon() async {
        do {
            install(try await model(for: daemons.selection))
            service.reset()
            connect()
        } catch {
            shell?.show(error, doing: "Could not switch daemons")
        }
    }

    /// Forgets a remote and its token; the selected one switches the window to This Mac.
    func remove(_ remote: String) {
        let wasSelected = daemons.selected == remote
        do {
            try daemons.remove(remote)
        } catch {
            shell?.show(error, doing: "Could not delete the token from the Keychain")
        }
        if wasSelected {
            Task { await switchDaemon() }
        }
    }

    /// Opens the Pair a daemon sheet, with an address for Pair again.
    func beginPairing(address: String = "") {
        pairing = DaemonPairing(
            daemons: daemons, deviceName: Self.computerName, address: address)
    }

    /// The Mac's name in System Settings > General > Sharing, as pairing names it there.
    static var computerName: String {
        (SCDynamicStoreCopyComputerName(nil, nil) as String?) ?? "Mac"
    }

    /// Pair and connect: pairs, then switches the window to the daemon.
    func pair() {
        guard let pairing else { return }
        Task {
            guard let daemon = await pairing.pair() else { return }
            self.pairing = nil
            await switchDaemon()
            shell?.show("Paired with \(daemon.machine)", kind: .done)
        }
    }

    /// The banner's Pair again: Settings > Devices with the sheet filled in for the remote.
    func pairAgain() {
        guard let remote = shell?.model.link.remote else { return }
        shell?.openSettings(.devices)
        beginPairing(address: remote.baseURL.absoluteString)
    }

    /// Starts or restarts the daemon's service, then connects again once it is up.
    func startService() {
        Task {
            guard await service.start() else { return }
            // launchd returns before the daemon listens; give it a moment.
            try? await Task.sleep(for: .seconds(1.5))
            connect()
        }
    }

    /// Drops the current connection and connects again at once, asking the daemon for its
    /// token first when it refused the one in use or gave none yet (`AppModel.connect()`).
    func connect() {
        guard let shell else { return }
        Task {
            if let failure = await shell.model.connect() {
                shell.show(failure, doing: "Could not get the device token")
            }
        }
    }
}
