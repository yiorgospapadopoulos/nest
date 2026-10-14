import Foundation
import Observation

/// A finished command's exit status and its output (stdout and stderr together).
public struct CommandOutput: Sendable, Equatable {
    public var status: Int32
    public var output: String

    public init(status: Int32, output: String) {
        self.status = status
        self.output = output
    }
}

/// Runs a program to completion away from the main actor.
public protocol CommandRunner: Sendable {
    func run(_ executable: String, _ arguments: [String]) async -> CommandOutput
}

/// Runs commands with `Process`. Meant for short commands such as `launchctl`. The output
/// is read while the process runs, since one that fills the pipe waits until it is read.
public struct ProcessRunner: CommandRunner {
    public init() {}

    public func run(_ executable: String, _ arguments: [String]) async -> CommandOutput {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        let reader = pipe.fileHandleForReading
        let (exits, exited) = AsyncStream<Int32>.makeStream()
        process.terminationHandler = { finished in
            exited.yield(finished.terminationStatus)
            exited.finish()
        }
        do {
            try process.run()
        } catch {
            return CommandOutput(status: -1, output: error.localizedDescription)
        }
        // On its own thread: the read blocks until the program closes its output.
        let data = await withCheckedContinuation { continuation in
            DispatchQueue.global().async {
                continuation.resume(returning: reader.readDataToEndOfFile())
            }
        }
        var status: Int32 = -1
        for await code in exits {
            status = code
        }
        return CommandOutput(
            status: status,
            output: String(decoding: data, as: UTF8.self)
                .trimmingCharacters(in: .whitespacesAndNewlines))
    }
}

/// The daemon's launchd user agent, as `nestd service install` sets it up.
public enum DaemonService {
    public static let label = "com.nest.daemon"
    public static let launchctl = "/bin/launchctl"

    public static func plistPath(home: URL) -> String {
        home.appending(path: "Library/LaunchAgents/\(label).plist").path
    }

    /// The Terminal command that installs the service, run in the Nest repository.
    public static func installCommand(repoPath: String?) -> String {
        let daemon = repoPath.map { quoted($0 + "/daemon") } ?? "<Nest repository>/daemon"
        return "cd \(daemon) && uv run nestd service install"
    }

    /// Single-quoted for the shell, so paths with spaces work when pasted.
    static func quoted(_ text: String) -> String {
        "'" + text.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }
}

public enum ServiceStartState: Sendable, Equatable {
    case idle
    case starting
    /// launchctl started the service; the app connects again.
    case started
    /// No plist to load: the service was never installed. Holds the install command.
    case notInstalled(command: String)
    case failed(String)
}

/// Starts or restarts the daemon's launchd service when the app cannot reach it:
/// `kickstart -k` (re)starts a loaded service; when launchd does not have it, `bootstrap`
/// loads it from its plist; without a plist, the user is shown how to install it.
@MainActor @Observable
public final class ServiceStarter {
    public private(set) var state = ServiceStartState.idle

    let runner: any CommandRunner
    let domain: String
    let plistPath: String
    let installCommand: String
    let fileExists: @Sendable (String) -> Bool

    public init(
        runner: any CommandRunner, uid: UInt32, home: URL, repoPath: String?,
        fileExists: @escaping @Sendable (String) -> Bool
    ) {
        self.runner = runner
        domain = "gui/\(uid)"
        plistPath = DaemonService.plistPath(home: home)
        installCommand = DaemonService.installCommand(repoPath: repoPath)
        self.fileExists = fileExists
    }

    /// For this user's service, run with `Process`.
    public static func local(repoPath: String?) -> ServiceStarter {
        ServiceStarter(
            runner: ProcessRunner(), uid: getuid(),
            home: FileManager.default.homeDirectoryForCurrentUser, repoPath: repoPath,
            fileExists: { FileManager.default.fileExists(atPath: $0) })
    }

    var kickstart: [String] { ["kickstart", "-k", "\(domain)/\(DaemonService.label)"] }
    var bootstrap: [String] { ["bootstrap", domain, plistPath] }

    /// Whether the connection banner offers to start the service.
    public func offersStart(when connection: ConnectionState) -> Bool {
        switch connection {
        case .disconnected, .reconnecting: state != .starting
        default: false
        }
    }

    /// Starts the service; true when it started and the app should connect again.
    @discardableResult
    public func start() async -> Bool {
        guard state != .starting else { return false }
        state = .starting
        if await runner.run(DaemonService.launchctl, kickstart).status == 0 {
            state = .started
            return true
        }
        guard fileExists(plistPath) else {
            state = .notInstalled(command: installCommand)
            return false
        }
        let loaded = await runner.run(DaemonService.launchctl, bootstrap)
        guard loaded.status == 0 else {
            let reason = loaded.output.split(separator: "\n").last.map(String.init)
            state = .failed(
                "launchctl could not load the service: "
                    + (reason ?? "exit status \(loaded.status)"))
            return false
        }
        state = .started
        return true
    }

    /// Back to the plain offer, as once the daemon is reachable again.
    public func reset() {
        state = .idle
    }
}
