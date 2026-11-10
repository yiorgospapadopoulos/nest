import Foundation
import Synchronization
import Testing

@testable import NestKit

/// Records what would be started in the background, or fails to start it.
final class FakeSpawner: ProcessSpawner {
    struct Failure: Error, LocalizedError {
        var errorDescription: String? { "no shell" }
    }

    private let state = Mutex<[[String]]>([])
    let fails: Bool

    init(fails: Bool = false) {
        self.fails = fails
    }

    var spawned: [[String]] { state.withLock { $0 } }

    func spawn(_ executable: String, _ arguments: [String]) throws {
        if fails {
            throw Failure()
        }
        state.withLock { $0.append([executable] + arguments) }
    }
}

/// Settings' Restart Nest (B60): the service restarts, then the app reopens itself once
/// it has quit.
@MainActor
@Suite struct AppRestarterTests {
    static let app = "/Users/me/My apps/Nest.app"
    static let kickstart = ServiceStarterTests.kickstart
    static let relaunch = [
        "/bin/sh", "-c",
        "while kill -0 4242 2>/dev/null; do sleep 0.2; done; open '/Users/me/My apps/Nest.app'",
    ]

    func restarter(
        _ runner: any CommandRunner, _ spawner: FakeSpawner, plistExists: Bool = true,
        daemon: DaemonRestart? = nil
    ) -> AppRestarter {
        let service = ServiceStarter(
            runner: runner, uid: 501, home: ServiceStarterTests.home, repoPath: "/r",
            fileExists: { [plist = ServiceStarterTests.plist] in $0 == plist && plistExists })
        return AppRestarter(
            service: service, daemon: daemon, spawner: spawner, appPath: Self.app, pid: 4242)
    }

    struct Down: Error {}

    /// A daemon that takes the restart, or is down, or answers only after `delay`, and how
    /// often it was asked.
    final class FakeDaemon: Sendable {
        private let count = Mutex(0)
        let answers: Bool
        let url: URL
        let delay: Duration?

        init(answers: Bool, url: URL = APIClient.defaultBaseURL, delay: Duration? = nil) {
            self.answers = answers
            self.url = url
            self.delay = delay
        }

        var asked: Int { count.withLock { $0 } }

        func restart() async throws {
            count.withLock { $0 += 1 }
            if let delay { try await Task.sleep(for: delay) }
            if !answers { throw Down() }
        }

        var restarting: DaemonRestart {
            DaemonRestart(
                daemon: url, environment: [:], timeLimit: .milliseconds(100),
                request: { try await self.restart() })
        }
    }

    /// B159 recheck 3 problem 2: `kickstart -k` skips the daemon's clean stop, so a few
    /// restarts soon after an update rolled a healthy update back.
    @Test func aDaemonThatAnswersRestartsItselfWithoutKickstart() async throws {
        let runner = FakeRunner([])
        let spawner = FakeSpawner()
        let daemon = FakeDaemon(answers: true)
        let restarter = restarter(runner, spawner, daemon: daemon.restarting)

        #expect(await restarter.restart() == .relaunching)

        #expect(daemon.asked == 1)
        #expect(runner.calls.isEmpty)
        let script = try #require(spawner.spawned.first?.last)
        #expect(script.contains("api/health"))
        #expect(restarter.restarting)
    }

    @Test func aDaemonThatIsDownIsRestartedWithKickstart() async {
        let runner = FakeRunner([CommandOutput(status: 0, output: "")])
        let spawner = FakeSpawner()
        let daemon = FakeDaemon(answers: false)
        let restarter = restarter(runner, spawner, daemon: daemon.restarting)

        #expect(await restarter.restart() == .relaunching)

        #expect(daemon.asked == 1)
        #expect(runner.calls == [Self.kickstart])
        #expect(spawner.spawned == [Self.relaunch])
    }

    /// B159 recheck 4 problem 3: a stuck daemon kept the spinner up for the request's
    /// default 60 seconds before the fallback.
    @Test func aDaemonThatDoesNotAnswerInTimeIsRestartedWithKickstart() async {
        let runner = FakeRunner([CommandOutput(status: 0, output: "")])
        let spawner = FakeSpawner()
        let daemon = FakeDaemon(answers: true, delay: .seconds(3))
        let restarter = restarter(runner, spawner, daemon: daemon.restarting)

        #expect(await restarter.restart() == .relaunching)

        #expect(runner.calls == [Self.kickstart])
        #expect(spawner.spawned == [Self.relaunch])
    }

    /// B159 recheck 4 problem 4: a test build whose test daemon is down must not restart
    /// the live service.
    @Test func aTestDaemonThatIsDownNeverRestartsTheService() async {
        let runner = FakeRunner([CommandOutput(status: 0, output: "")])
        let spawner = FakeSpawner()
        let daemon = FakeDaemon(answers: false, url: URL(string: "http://127.0.0.1:41010")!)
        let restarter = restarter(runner, spawner, daemon: daemon.restarting)

        guard case .failed = await restarter.restart() else {
            Issue.record("a test daemon's restart went on")
            return
        }
        #expect(runner.calls.isEmpty)
        #expect(spawner.spawned.isEmpty)
        #expect(!restarter.restarting)
    }

    @Test func restartsTheServiceThenReopensTheAppOnceItQuits() async {
        let runner = FakeRunner([CommandOutput(status: 0, output: "")])
        let spawner = FakeSpawner()
        let restarter = restarter(runner, spawner)

        #expect(await restarter.restart() == .relaunching)

        #expect(runner.calls == [Self.kickstart])
        #expect(spawner.spawned == [Self.relaunch])
        #expect(restarter.restarting)
    }

    @Test func theAppPathIsQuotedForTheShell() {
        #expect(
            AppRelaunch.arguments(appPath: "/a/it's.app", pid: 7) == [
                "-c", "while kill -0 7 2>/dev/null; do sleep 0.2; done; open '/a/it'\\''s.app'",
            ])
        #expect(AppRelaunch.shell == "/bin/sh")
    }

    /// The reopen after a restart the daemon does itself, and its last command.
    private func opening(_ environment: [String: String]) throws -> String {
        let arguments = AppRelaunch.afterDaemonRestart(
            appPath: Self.app, pid: 7, daemon: try #require(URL(string: "http://127.0.0.1:41060")),
            environment: environment)
        let script = try #require(arguments.last)
        #expect(arguments.first == "-c")
        #expect(script.contains("kill -0 7 "))
        #expect(script.contains("'http://127.0.0.1:41060/api/health'"))
        return try #require(script.components(separatedBy: "; ").last)
    }

    @Test func aPlainAppReopensWithAPlainOpen() throws {
        #expect(try opening([:]) == "open '/Users/me/My apps/Nest.app'")
        #expect(
            try opening(["NEST_DAEMON_URL": "", "NEST_DATA_DIR": ""])
                == "open '/Users/me/My apps/Nest.app'")
    }

    @Test func aTestBuildKeepsItsDaemon() throws {
        let opened = try opening([
            "NEST_DAEMON_URL": "http://127.0.0.1:41060", "NEST_DATA_DIR": "/tmp/my test's data",
            "HOME": "/Users/me",
        ])
        #expect(
            opened
                == "open -n --env 'NEST_DAEMON_URL=http://127.0.0.1:41060' "
                + "--env 'NEST_DATA_DIR=/tmp/my test'\\''s data' '/Users/me/My apps/Nest.app'")
    }

    @Test func aServiceThatCannotRestartKeepsTheAppOpen() async {
        let runner = FakeRunner([
            ServiceStarterTests.notFound, CommandOutput(status: 5, output: "Input/output error"),
        ])
        let spawner = FakeSpawner()
        let restarter = restarter(runner, spawner)

        #expect(
            await restarter.restart()
                == .failed("launchctl could not load the service: Input/output error"))

        #expect(spawner.spawned.isEmpty)
        #expect(!restarter.restarting)
    }

    @Test func aServiceThatIsNotInstalledSaysHowToInstallIt() async {
        let restarter = restarter(
            FakeRunner([ServiceStarterTests.notFound]), FakeSpawner(), plistExists: false)

        #expect(
            await restarter.restart()
                == .failed(
                    "The Nest service is not installed. Install it with: "
                        + "cd '/r/daemon' && uv run nestd service install"))
    }

    @Test func anAppThatCannotBeReopenedStaysOpen() async {
        let restarter = restarter(FakeRunner([]), FakeSpawner(fails: true))

        #expect(await restarter.restart() == .failed("Could not reopen Nest: no shell"))
        #expect(!restarter.restarting)
    }

    @Test func aServiceAlreadyStartingIsSaidSo() async {
        let runner = SlowRunner()
        let restarter = restarter(runner, FakeSpawner())
        let first = Task { await restarter.service.start() }
        await runner.waitForCall()

        #expect(
            await restarter.restart()
                == .failed("The Nest service is already starting. Try again in a moment."))

        runner.finish()
        #expect(await first.value)
    }
}

@Suite struct DetachedSpawnerTests {
    @Test func startsAProgramWithoutWaitingForIt() throws {
        let marker = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: marker) }

        try DetachedSpawner().spawn("/usr/bin/touch", [marker.path])

        let deadline = Date().addingTimeInterval(5)
        while !FileManager.default.fileExists(atPath: marker.path) && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.05)
        }
        #expect(FileManager.default.fileExists(atPath: marker.path))
    }

    @Test func reportsAProgramThatCannotStart() {
        #expect(throws: (any Error).self) {
            try DetachedSpawner().spawn("/no/such/program", [])
        }
    }

    /// The helpers and `nest uninstall` lead a session of their own (B130), so they outlive
    /// the app and whatever ends its session.
    @Test func theProgramLeadsASessionOfItsOwn() throws {
        let marker = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: marker) }

        try DetachedSpawner().spawn(
            "/bin/sh",
            [
                "-c", "/bin/ps -o stat= -p $$ > \"$1.part\"; mv \"$1.part\" \"$1\"", "sh",
                marker.path,
            ])

        let deadline = Date().addingTimeInterval(5)
        while !FileManager.default.fileExists(atPath: marker.path) && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.05)
        }
        // `s` in ps's state: the session leader.
        #expect(try String(contentsOf: marker, encoding: .utf8).contains("s"))
    }
}
