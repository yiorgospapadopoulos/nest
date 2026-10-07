import Foundation
import HarnessKit
import Observation

/// Starts the app: reads the device token, builds the stores and keeps the live
/// connection to the daemon running.
@MainActor @Observable
final class AppController {
    enum Phase: Equatable {
        case loading
        case ready
        /// The daemon has not stored this Mac's device token yet.
        case noToken
        case failed(String)
    }

    private(set) var phase = Phase.loading
    private(set) var shell: Shell?
    /// Starts the daemon's launchd service when the daemon cannot be reached.
    let service: ServiceStarter
    @ObservationIgnored private var liveTask: Task<Void, Never>?
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

    /// The harness checkout this app was built from, for the service install command;
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
        do {
            guard let model = try AppModel.local() else {
                phase = .noToken
                return
            }
            let shell = Shell(model: model)
            self.shell = shell
            phase = .ready
            notifier = Notifier(shell: shell)
            notifier?.start()
            visibility = VisibilityMonitor(reporter: model.visibility)
            visibility?.start()
            connect()
        } catch TokenStoreError.keychain(let status) {
            phase = .failed("The Keychain refused to share the device token (status \(status)).")
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

    /// Drops the current connection and connects again at once.
    func connect() {
        guard let shell else { return }
        liveTask?.cancel()
        liveTask = Task { await shell.model.live.run() }
    }
}
