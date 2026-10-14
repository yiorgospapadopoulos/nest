import Foundation
import NestKit
import Observation

/// Starts the app: reads the device token, builds the stores and keeps the live
/// connection to the daemon running.
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
    /// The device token is being asked for, for the first start.
    @ObservationIgnored private var starting = false
    @ObservationIgnored private var notifier: Notifier?
    @ObservationIgnored private var visibility: VisibilityMonitor?

    init() {
        service = .local(repoPath: Self.repositoryPath)
    }

    /// A controller around a prepared shell, for snapshots.
    init(shell: Shell, service: ServiceStarter) {
        self.shell = shell
        self.service = service
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

    /// Asks the daemon for the device token (away from the main thread) and builds the
    /// window's model. A daemon that is not running gives none: the window opens showing it
    /// as unreachable, with the offer to start the service, and asks again on connect.
    private func open() async {
        do {
            let model = try await AppModel.local()
            let shell = Shell(model: model)
            self.shell = shell
            phase = .ready
            notifier = Notifier(shell: shell)
            notifier?.start()
            visibility = VisibilityMonitor(reporter: model.visibility)
            visibility?.start()
            connect()
        } catch {
            phase = .failed(Shell.describe(error))
        }
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
