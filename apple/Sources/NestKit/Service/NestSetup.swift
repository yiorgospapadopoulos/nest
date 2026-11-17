import Foundation
import Observation

/// What a running program printed, line by line, and how it ended.
public enum StreamedOutput: Sendable, Equatable {
    /// A line of its standard output.
    case line(String)
    /// A line of its standard error.
    case problem(String)
    case exit(Int32)
}

/// Runs a program and gives its output as it comes, ending with its exit status.
public protocol LineRunner: Sendable {
    func run(_ executable: String, _ arguments: [String], environment: [String: String])
        -> AsyncStream<StreamedOutput>
}

/// Runs a program with `Process`, each pipe read on a thread of its own.
public struct ProcessLineRunner: LineRunner {
    public init() {}

    public func run(_ executable: String, _ arguments: [String], environment: [String: String])
        -> AsyncStream<StreamedOutput>
    {
        AsyncStream { continuation in
            let process = Process()
            process.executableURL = URL(fileURLWithPath: executable)
            process.arguments = arguments
            process.environment = environment
            process.standardInput = FileHandle.nullDevice
            let output = Pipe()
            let errors = Pipe()
            process.standardOutput = output
            process.standardError = errors
            do {
                try process.run()
            } catch {
                continuation.yield(.problem(error.localizedDescription))
                continuation.yield(.exit(-1))
                continuation.finish()
                return
            }
            let readers = DispatchGroup()
            for (pipe, isOutput) in [(output, true), (errors, false)] {
                let handle = pipe.fileHandleForReading
                readers.enter()
                DispatchQueue.global().async {
                    Self.readLines(handle) {
                        continuation.yield(isOutput ? .line($0) : .problem($0))
                    }
                    readers.leave()
                }
            }
            readers.notify(queue: .global()) {
                process.waitUntilExit()
                continuation.yield(.exit(process.terminationStatus))
                continuation.finish()
            }
        }
    }

    /// Blocks until the program closes its end, calling `line` for each whole line.
    static func readLines(_ handle: FileHandle, _ line: (String) -> Void) {
        var pending = Data()
        while case let chunk = handle.availableData, !chunk.isEmpty {
            pending.append(chunk)
            while let end = pending.firstIndex(of: UInt8(ascii: "\n")) {
                line(String(decoding: pending[pending.startIndex..<end], as: UTF8.self))
                pending.removeSubrange(pending.startIndex...end)
            }
        }
        if !pending.isEmpty {
            line(String(decoding: pending, as: UTF8.self))
        }
    }
}

/// The Mac app setting Nest up on a Mac that has none, for a Nest.app downloaded from a web
/// page: it runs the release's own install.sh, which it carries, the same script as the
/// terminal line. `NEST_SETUP_BY_APP` has the script leave this app alone, as it is already in
/// place and running; the daemon then names its app, which this one follows (`AppSwapper`).
@MainActor @Observable
public final class NestSetup {
    public enum Phase: Sendable, Equatable {
        case ready
        /// The step under way, from the script's `@step` and `@progress` lines.
        case running(SetupProgress)
        case failed(String)
        /// The script ended with the service running; the window connects.
        case finished
    }

    /// Where install.sh and updates keep the app.
    static let applications = "/Applications"

    public private(set) var phase = Phase.ready

    let runner: any LineRunner
    let script: String?
    let appPath: String
    let releaseURL: String
    let environment: [String: String]
    let developerBuild: Bool
    let isInstalled: @Sendable () -> Bool
    let clock: @Sendable () -> Date

    public init(
        runner: any LineRunner, script: String?, appPath: String, releaseURL: String,
        environment: [String: String], developerBuild: Bool,
        isInstalled: @escaping @Sendable () -> Bool,
        clock: @escaping @Sendable () -> Date = { Date() }
    ) {
        self.runner = runner
        self.script = script
        self.appPath = appPath
        self.releaseURL = releaseURL
        self.environment = environment
        self.developerBuild = developerBuild
        self.isInstalled = isInstalled
        self.clock = clock
    }

    /// For this app, with the install.sh in its Resources.
    public static func local(install: ReleasedInstall) -> NestSetup {
        let bundle = Bundle.main
        return NestSetup(
            runner: ProcessLineRunner(), script: bundle.path(forResource: "install", ofType: "sh"),
            appPath: bundle.bundleURL.path, releaseURL: install.releaseURL,
            environment: ProcessInfo.processInfo.environment,
            developerBuild: AppBuild.checkout != nil, isInstalled: { install.hasDaemon })
    }

    /// Whether the window offers setup instead of the line that repairs an install: a released
    /// app on a Mac with no released Nest, or a setup already begun here, which keeps its
    /// screen once the script has made the install.
    public var isOffered: Bool {
        phase != .ready || (!developerBuild && script != nil && !isInstalled())
    }

    /// Whether this app runs from Applications. One opened from Downloads or a disk image runs
    /// from a place of macOS's own, out of sight, and updates could not replace it.
    public var isInApplications: Bool {
        URL(fileURLWithPath: appPath).deletingLastPathComponent().standardizedFileURL.path
            == Self.applications
    }

    /// The same setup from Terminal.
    public var terminalLine: String { ReleasedInstall.installLine(releaseURL: releaseURL) }

    /// Runs install.sh; true once it ended with the service running.
    @discardableResult
    public func run() async -> Bool {
        if case .running = phase { return false }
        guard let script, isInApplications else { return false }
        var progress = SetupProgress(startedAt: clock())
        phase = .running(progress)
        let variables = environment.merging(
            [
                "NEST_SETUP_BY_APP": "1", "NEST_MAC_APP": appPath,
                "NEST_RELEASE_URL": releaseURL,
            ]
        ) { $1 }
        var problems: [String] = []
        var status: Int32 = -1
        for await output in runner.run("/bin/sh", [script], environment: variables) {
            switch output {
            case .line(let line):
                if progress.read(line.trimmingCharacters(in: .whitespaces), at: clock()) {
                    phase = .running(progress)
                }
            case .problem(let line):
                let line = line.trimmingCharacters(in: .whitespaces)
                if !line.isEmpty { problems.append(line) }
            case .exit(let code):
                status = code
            }
        }
        guard status == 0 else {
            phase = .failed(Self.reason(problems, status: status))
            return false
        }
        phase = .finished
        return true
    }

    /// Back to the offer, once the daemon answers; a setup under way goes on.
    public func reset() {
        if case .running = phase { return }
        phase = .ready
    }

    /// What went wrong in the script's own words: its last `Nest: ` line, else the last line
    /// it printed there.
    static func reason(_ problems: [String], status: Int32) -> String {
        let prefix = "Nest: "
        if let said = problems.last(where: { $0.hasPrefix(prefix) }) {
            return String(said.dropFirst(prefix.count))
        }
        return problems.last ?? "Setup stopped with exit status \(status)."
    }
}
