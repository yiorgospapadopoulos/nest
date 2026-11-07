import Foundation
import Observation

/// Starts a program in the background and does not wait for it.
public protocol ProcessSpawner: Sendable {
    func spawn(_ executable: String, _ arguments: [String]) throws
}

/// Starts programs in a session of their own, with no input or output and none of this app's
/// open files, so they outlive the app and whatever ends its session, as the Linux app's
/// `detach`. Waited for on a thread of its own, so none is left a zombie while the app runs.
public struct DetachedSpawner: ProcessSpawner {
    public struct Failure: Error, LocalizedError {
        let code: Int32
        public var errorDescription: String? { String(cString: strerror(code)) }
    }

    public init() {}

    public func spawn(_ executable: String, _ arguments: [String]) throws {
        var attributes: posix_spawnattr_t?
        posix_spawnattr_init(&attributes)
        defer { posix_spawnattr_destroy(&attributes) }
        posix_spawnattr_setflags(
            &attributes, Int16(POSIX_SPAWN_SETSID | POSIX_SPAWN_CLOEXEC_DEFAULT))
        var actions: posix_spawn_file_actions_t?
        posix_spawn_file_actions_init(&actions)
        defer { posix_spawn_file_actions_destroy(&actions) }
        posix_spawn_file_actions_addopen(&actions, 0, "/dev/null", O_RDONLY, 0)
        posix_spawn_file_actions_addopen(&actions, 1, "/dev/null", O_WRONLY, 0)
        posix_spawn_file_actions_addopen(&actions, 2, "/dev/null", O_WRONLY, 0)
        let argv = ([executable] + arguments).map { strdup($0) } + [nil]
        defer { argv.forEach { free($0) } }
        var pid: pid_t = 0
        let code = posix_spawn(&pid, executable, &actions, &attributes, argv, environ)
        guard code == 0 else { throw Failure(code: code) }
        let child = pid
        Thread.detachNewThread {
            var status: Int32 = 0
            waitpid(child, &status, 0)
        }
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

    /// For the swap to a release's app (B130), a zip made with `ditto`, once this app quit.
    /// What it does goes to `log`, as it starts detached with no output of its own.
    public static func swapping(
        appPath: String, zipPath: String, pid: Int32, environment: [String: String], log: String
    ) -> [String] {
        let start = "say swapping to \(DaemonService.quoted(zipPath)) once Nest \(pid) quits"
        let script =
            logging(to: log) + [start, waitForQuit(pid)] + swap(appPath, zipPath, pid, environment)
        return ["-c", script.joined(separator: "\n")]
    }

    /// Relaunch to update with a new app (B130): waits for this app to quit, then up to
    /// `openWithin` for the daemon to answer `/api/health` with `version`, then swaps to
    /// `zipPath` and opens it, once. The old daemon can still answer for a moment after the
    /// relaunch, so another version counts as the update going back only once `updateFile` no
    /// longer says `updating`; then the old app opens as it is. So does a daemon slower than
    /// that, as one that crashes and goes back, so Nest is never gone for long: the old app
    /// shows the update's progress and swaps itself once the new daemon answers. An app the
    /// user opened meanwhile is left to do that too, never swapped while it runs. What it
    /// does goes to `log`.
    public static func afterUpdate(
        appPath: String, zipPath: String, version: String, pid: Int32, daemon: URL,
        updateFile: String, environment: [String: String], log: String,
        openWithin: TimeInterval = newAppWait
    ) -> [String] {
        let health = DaemonService.quoted(daemon.appending(path: "api/health").absoluteString)
        let opening = open(appPath: appPath, environment: environment)
        // The whole command line, so this script, which holds the path too, is not taken for it.
        let running = DaemonService.quoted(Self.literal(appPath + "/Contents/MacOS/Nest") + "( .*)?")
        let waiting = [
            "say Nest \(pid) asked for \(DaemonService.quoted(version)): waiting for it to quit",
            waitForQuit(pid),
            "start=$(date +%s); new=\(DaemonService.quoted(version)); next=wait",
            "answered() { /usr/bin/curl -fs --noproxy '*' -m 2 \(health)"
                + #" | /usr/bin/sed -n 's/.*"version" *: *"\([^"]*\)".*/\1/p'; }"#,
            #"updating() { /usr/bin/grep -Eq '"updating" *: *\{' "#
                + "\(DaemonService.quoted(updateFile)) 2>/dev/null; }",
            "while [ $(($(date +%s) - start)) -lt \(Int(openWithin.rounded(.up))) ]; do",
            "answer=$(answered)",
            #"if [ "$answer" = "$new" ]; then next=new; break; fi"#,
            #"if [ -n "$answer" ] && ! updating; then next=old; break; fi"#,
            "sleep 0.5",
            "done",
            #"if [ "$next" = old ]; then say "the daemon is back on $answer: opening this app"; "#
                + opening + "; exit 0; fi",
            #"if [ "$next" = wait ]; then say "the daemon is not back yet: opening this app, "#
                + #"which follows the update itself"; "# + opening + "; exit 0; fi",
            "if /usr/bin/pgrep -fx \(running) >/dev/null; then say \"Nest is open already: "
                + "it swaps itself\"; exit 0; fi",
            #"say "the daemon answers on $new""#,
        ]
        let script = logging(to: log) + waiting + swap(appPath, zipPath, pid, environment)
        return ["-c", script.joined(separator: "\n")]
    }

    /// How long the helper waits for the new daemon before it opens the old app, which then
    /// shows the update's progress; most updates answer in a few seconds.
    public static let newAppWait: TimeInterval = 10

    /// `text` matched as itself in an extended regular expression.
    static func literal(_ text: String) -> String {
        text.reduce(into: "") { result, character in
            if #"\.[]()*+?{}|^$"#.contains(character) {
                result.append("\\")
            }
            result.append(character)
        }
    }

    private static func waitForQuit(_ pid: Int32) -> String {
        "while kill -0 \(pid) 2>/dev/null; do sleep 0.2; done"
    }

    /// The helper's own lines in `log`, `say` with the time. A log that cannot be written
    /// leaves the output where it was, as a failed `exec` would end the shell.
    private static func logging(to log: String) -> [String] {
        let file = DaemonService.quoted(log)
        let folder = DaemonService.quoted((log as NSString).deletingLastPathComponent)
        return [
            "if /bin/mkdir -p \(folder) 2>/dev/null && : >>\(file) 2>/dev/null; then "
                + "exec >>\(file) 2>&1; fi",
            #"say() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }"#,
        ]
    }

    /// Beside the app, so a move is one step: unpacks the zip, moves the old app aside and the
    /// new one in, and opens it. The old app stays until the new one has opened, and whatever
    /// fails puts it back and opens it, so Nest always comes up. A test build keeps its daemon
    /// through `environment`.
    private static func swap(
        _ appPath: String, _ zipPath: String, _ pid: Int32, _ environment: [String: String]
    ) -> [String] {
        let app = DaemonService.quoted(appPath)
        let folder = (appPath as NSString).deletingLastPathComponent
        let work = DaemonService.quoted("\(folder)/.nest-swap-\(pid)")
        let opening = open(appPath: appPath, environment: environment)
        return [
            "app=\(app); work=\(work)",
            "rm -rf \"$work\"",
            "if mkdir \"$work\" && /usr/bin/ditto -x -k \(DaemonService.quoted(zipPath)) \"$work/new\""
                + " && [ -x \"$work/new/Nest.app/Contents/MacOS/Nest\" ]"
                + " && mv \"$app\" \"$work/old\"; then",
            "if mv \"$work/new/Nest.app\" \"$app\" && \(opening); then say \"opened the new app\"; "
                + "rm -rf \"$work\"; exit 0; fi",
            "say \"the new app did not open: putting the old one back\"",
            "rm -rf \"$app\"",
            "mv \"$work/old\" \"$app\"",
            "else say \"the new app could not be unpacked: keeping the old one\"",
            "fi",
            opening,
            "rm -rf \"$work\"",
        ]
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
