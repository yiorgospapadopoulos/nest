import AppKit
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
    /// A `nest://` link that came before the window had a shell (B151), opened once it has.
    private var pendingLink: NestLink?
    /// Starts the daemon's launchd service when the daemon cannot be reached.
    let service: ServiceStarter
    /// This Mac and the paired remotes, with the one selected.
    let daemons: DaemonList
    /// Settings > Devices' Pair a daemon sheet while it is open.
    var pairing: DaemonPairing?
    /// The pixies around the notch (B114), for the window's daemon.
    private(set) var island: IslandController?
    private var glow: ComputerGlow?
    /// The device token is being asked for, for the first start.
    @ObservationIgnored private var starting = false
    @ObservationIgnored private var notifier: Notifier?
    @ObservationIgnored private var visibility: VisibilityMonitor?
    /// Once a launch, whichever window model asks.
    @ObservationIgnored private lazy var swapper = AppSwapper.local(
        dataFolder: daemons.local.dataFolder)

    init() {
        let environment = ProcessInfo.processInfo.environment
        let local = DaemonLocation(environment: environment)
        daemons = DaemonList(local: local)
        service = .local(
            repoPath: AppBuild.checkout,
            releaseURL: ReleasedInstall(dataFolder: local.dataFolder, environment: environment)
                .releaseURL)
    }

    /// This Mac's install, read from its data folder while the daemon is down.
    var install: ReleasedInstall {
        ReleasedInstall(
            dataFolder: daemons.local.dataFolder, environment: ProcessInfo.processInfo.environment)
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
            // An update under way shows at once, before the first try can show the banner.
            _ = shell?.noteUpdate(install.updating())
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
            let model = try await Self.localModel(daemons.local)
            model.updates.reopen = { [weak self, daemon = daemons.local.baseURL] newApp in
                self?.reopen(daemon: daemon, newApp: newApp)
            }
            model.updates.followApp = { [weak self] file in self?.follow(file) }
            return model
        case .remote(let daemon):
            let model = try await AppModel.remote(daemon, tokens: daemons.tokens(for: daemon))
            model.link.onSeen = { [daemons] machine, date in
                daemons.seen(daemon.id, machine: machine, at: date)
            }
            return model
        }
    }

    /// Quits so the app reopens once `daemon` restarted: with a new app, the swap's helper
    /// opens that one once the daemon answers on its version, or this one again when the
    /// daemon takes longer (`AppRelaunch.afterUpdate`). A reopen that cannot start leaves the
    /// app running, which then reconnects.
    private func reopen(daemon: URL, newApp: String?) {
        if let newApp, swapper.afterUpdate(to: newApp, daemon: daemon) {
            NSApp.terminate(nil)
            return
        }
        let arguments = AppRelaunch.afterDaemonRestart(
            appPath: Bundle.main.bundleURL.path, pid: getpid(), daemon: daemon,
            environment: ProcessInfo.processInfo.environment)
        guard (try? DetachedSpawner().spawn(AppRelaunch.shell, arguments)) != nil else { return }
        NSApp.terminate(nil)
    }

    /// Swaps to the app that belongs to This Mac's daemon, quitting for it.
    private func follow(_ file: AppFile) {
        switch swapper.follow(file) {
        case .none: break
        case .swapping: NSApp.terminate(nil)
        case .failed(let version):
            shell?.show("Nest could not update its app to \(version)", kind: .failed)
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
    /// notifications, its visibility reports and its island, and its terminal and browser
    /// panes end.
    /// Settings stays open on its page.
    private func install(_ model: AppModel) {
        let shell = Shell(model: model)
        if let old = self.shell {
            visibility?.stop()
            old.model.close()
            old.tools.keep([])
            old.webPanes.closeAll()
            shell.keepSettings(of: old)
        }
        self.shell = shell
        shell.island = { [weak self] in self?.island?.trusted == true }
        notifier = Notifier(shell: shell)
        notifier?.start()
        visibility = VisibilityMonitor(reporter: model.visibility)
        visibility?.start()
        island?.stop()
        island = IslandController(shell: shell)
        island?.start()
        glow?.stop()
        glow = ComputerGlow(store: model.computer)
        glow?.start()
        if let link = pendingLink {
            pendingLink = nil
            shell.reveal(chat: link.chat, in: link.project)
        }
    }

    /// Opens the chat of a `nest://chat/<id>?project=<name>` link, as `nest open` sends one
    /// (B151); any other link is ignored.
    func open(_ url: URL) {
        guard let link = NestLink(url) else { return }
        NSApp.activate()
        guard let shell else {
            pendingLink = link
            return
        }
        shell.reveal(chat: link.chat, in: link.project)
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
            await runService()
            connect()
        }
    }

    private func runService() async {
        // A test daemon is not the service: launchd would restart the real one.
        guard daemons.local.baseURL == APIClient.defaultBaseURL, await service.start() else {
            return
        }
        // launchd returns before the daemon listens; give it a moment.
        try? await Task.sleep(for: .seconds(1.5))
    }

    /// The window's connection changed. This Mac's daemon down at launch gets its service
    /// started once by the app itself before the window asks the user for anything (B130).
    func noteConnection(_ connection: ConnectionState) {
        guard let shell else { return }
        let update = connection.isUnreachable ? install.updating() : nil
        if shell.noteConnection(connection, update: update) {
            startServiceOnce()
        }
    }

    /// While an update has the daemon down: its note read again, and the daemon tried again,
    /// so the window moves on as soon as it is back.
    func followUpdate() {
        guard let shell else { return }
        if shell.noteUpdate(install.updating()) {
            startServiceOnce()
        } else {
            connect()
        }
    }

    private func startServiceOnce() {
        Task {
            await runService()
            shell?.serviceStartFinished()
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
