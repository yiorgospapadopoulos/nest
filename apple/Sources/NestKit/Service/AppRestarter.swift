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
/// Settings' Restart uses it plainly, after `kickstart`.
public enum AppRelaunch {
    public static let shell = "/bin/sh"

    public static func arguments(appPath: String, pid: Int32) -> [String] {
        [
            "-c",
            "while kill -0 \(pid) 2>/dev/null; do sleep 0.2; done; open "
                + DaemonService.quoted(appPath),
        ]
    }

    /// For a restart the daemon does itself (Relaunch to update, Undo update): reopens only
    /// once the daemon went down and answers again on `daemon`, so the new app finds it up.
    /// A daemon already back is missed, so the wait for it to go down ends after 5 seconds;
    /// after 60 the app opens anyway. A test build keeps its daemon through `environment`.
    public static func afterDaemonRestart(
        appPath: String, pid: Int32, daemon: URL, environment: [String: String]
    ) -> [String] {
        let health = DaemonService.quoted(daemon.appending(path: "api/health").absoluteString)
        let script = [
            "start=$(date +%s)",
            "up() { /usr/bin/curl -fs --noproxy '*' -m 1 -o /dev/null \(health); }",
            "passed() { [ $(($(date +%s) - start)) -ge \"$1\" ]; }",
            "while kill -0 \(pid) 2>/dev/null; do sleep 0.2; done",
            "while up && ! passed 5; do sleep 0.2; done",
            "until up || passed 60; do sleep 0.2; done",
            open(appPath: appPath, environment: environment),
        ]
        return ["-c", script.joined(separator: "; ")]
    }

    /// For the swap to a release's app (B130), a zip made with `ditto`. Beside the app, so a
    /// move is one step: unpacks it, moves the old app aside and the new one in, and opens it.
    /// The old app stays until the new one has opened, and whatever fails puts it back and
    /// opens it, so Nest always comes up. A test build keeps its daemon through `environment`.
    public static func swapping(
        appPath: String, zipPath: String, pid: Int32, environment: [String: String]
    ) -> [String] {
        let app = DaemonService.quoted(appPath)
        let folder = (appPath as NSString).deletingLastPathComponent
        let work = DaemonService.quoted("\(folder)/.nest-swap-\(pid)")
        let opening = open(appPath: appPath, environment: environment)
        let script = [
            "while kill -0 \(pid) 2>/dev/null; do sleep 0.2; done",
            "app=\(app); work=\(work)",
            "rm -rf \"$work\"",
            "if mkdir \"$work\" && /usr/bin/ditto -x -k \(DaemonService.quoted(zipPath)) \"$work/new\""
                + " && [ -x \"$work/new/Nest.app/Contents/MacOS/Nest\" ]"
                + " && mv \"$app\" \"$work/old\"; then",
            "if mv \"$work/new/Nest.app\" \"$app\" && \(opening); then rm -rf \"$work\"; exit 0; fi",
            "rm -rf \"$app\"",
            "mv \"$work/old\" \"$app\"",
            "fi",
            opening,
            "rm -rf \"$work\"",
        ]
        return ["-c", script.joined(separator: "\n")]
    }

    /// `open` starts the app through launchd, which does not pass this process's environment on.
    private static func open(appPath: String, environment: [String: String]) -> String {
        let kept = ["NEST_DAEMON_URL", "NEST_DATA_DIR"].compactMap { name in
            environment[name].flatMap { value in
                value.isEmpty ? nil : "--env " + DaemonService.quoted("\(name)=\(value)")
            }
        }
        let flags = kept.isEmpty ? [] : ["-n"] + kept
        return (["open"] + flags + [DaemonService.quoted(appPath)]).joined(separator: " ")
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
