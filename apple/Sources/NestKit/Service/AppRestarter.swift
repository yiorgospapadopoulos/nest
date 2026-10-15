import Foundation
import Observation

/// Starts a program in the background and does not wait for it.
public protocol ProcessSpawner: Sendable {
    func spawn(_ executable: String, _ arguments: [String]) throws
}

/// Starts programs with `Process`, its output discarded. The program keeps running after
/// this app quits.
public struct DetachedSpawner: ProcessSpawner {
    public init() {}

    public func spawn(_ executable: String, _ arguments: [String]) throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try process.run()
    }
}

/// How the app reopens itself: a shell waits until this process has quit, then opens the
/// app's bundle again (an `open` while it still runs would only bring it forward).
public enum AppRelaunch {
    public static let shell = "/bin/sh"

    public static func arguments(appPath: String, pid: Int32) -> [String] {
        [
            "-c",
            "while kill -0 \(pid) 2>/dev/null; do sleep 0.2; done; open "
                + DaemonService.quoted(appPath),
        ]
    }
}

public enum AppRestartResult: Sendable, Equatable {
    /// The service restarted and the app reopens once it quits: quit now.
    case relaunching
    /// Nothing reopens; the app stays open and shows why.
    case failed(String)
}

/// Settings' Restart Nest (B60): restarts the daemon's service with `ServiceStarter`
/// (`kickstart -k`), then starts the relaunch, after which the app quits.
@MainActor @Observable
public final class AppRestarter {
    /// The service restarted and the relaunch is waiting for the app to quit.
    public private(set) var restarting = false

    let service: ServiceStarter
    let spawner: any ProcessSpawner
    let appPath: String
    let pid: Int32

    public init(service: ServiceStarter, spawner: any ProcessSpawner, appPath: String, pid: Int32) {
        self.service = service
        self.spawner = spawner
        self.appPath = appPath
        self.pid = pid
    }

    /// For this running app.
    public static func local(service: ServiceStarter) -> AppRestarter {
        AppRestarter(
            service: service, spawner: DetachedSpawner(), appPath: Bundle.main.bundleURL.path,
            pid: getpid())
    }

    public func restart() async -> AppRestartResult {
        guard await service.start() else {
            switch service.state {
            case .notInstalled(let command):
                return .failed("The Nest service is not installed. Install it with: \(command)")
            case .failed(let reason):
                return .failed(reason)
            default:
                return .failed("The Nest service is already starting. Try again in a moment.")
            }
        }
        do {
            try spawner.spawn(AppRelaunch.shell, AppRelaunch.arguments(appPath: appPath, pid: pid))
        } catch {
            return .failed("Could not reopen Nest: \(error.localizedDescription)")
        }
        restarting = true
        return .relaunching
    }
}
