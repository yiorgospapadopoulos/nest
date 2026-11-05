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
        _ runner: any CommandRunner, _ spawner: FakeSpawner, plistExists: Bool = true
    ) -> AppRestarter {
        let service = ServiceStarter(
            runner: runner, uid: 501, home: ServiceStarterTests.home, repoPath: "/r",
            fileExists: { [plist = ServiceStarterTests.plist] in $0 == plist && plistExists })
        return AppRestarter(service: service, spawner: spawner, appPath: Self.app, pid: 4242)
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
}
