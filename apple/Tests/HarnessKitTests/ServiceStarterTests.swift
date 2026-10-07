import Foundation
import Synchronization
import Testing

@testable import HarnessKit

/// Answers launchctl calls with queued results and records them.
final class FakeRunner: CommandRunner {
    private let state: Mutex<(calls: [[String]], results: [CommandOutput])>

    init(_ results: [CommandOutput]) {
        state = Mutex((calls: [], results: results))
    }

    var calls: [[String]] { state.withLock { $0.calls } }

    func run(_ executable: String, _ arguments: [String]) async -> CommandOutput {
        state.withLock { state in
            state.calls.append([executable] + arguments)
            return state.results.isEmpty
                ? CommandOutput(status: 0, output: "") : state.results.removeFirst()
        }
    }
}

@MainActor
@Suite struct ServiceStarterTests {
    static let home = URL(fileURLWithPath: "/Users/me")
    static let plist = "/Users/me/Library/LaunchAgents/com.harness.daemon.plist"
    static let kickstart = [
        "/bin/launchctl", "kickstart", "-k", "gui/501/com.harness.daemon",
    ]
    static let bootstrap = ["/bin/launchctl", "bootstrap", "gui/501", plist]
    static let notFound = CommandOutput(
        status: 113, output: "Could not find service \"com.harness.daemon\" in domain")

    func starter(_ runner: FakeRunner, plistExists: Bool = true) -> ServiceStarter {
        ServiceStarter(
            runner: runner, uid: 501, home: Self.home, repoPath: "/Users/me/My code/harness",
            fileExists: { [plist = Self.plist] in $0 == plist && plistExists })
    }

    @Test func kickstartsALoadedService() async {
        let runner = FakeRunner([CommandOutput(status: 0, output: "")])
        let starter = starter(runner)

        #expect(await starter.start())

        #expect(starter.state == .started)
        #expect(runner.calls == [Self.kickstart])
    }

    @Test func bootstrapsTheServiceWhenLaunchdDoesNotHaveIt() async {
        let runner = FakeRunner([Self.notFound, CommandOutput(status: 0, output: "")])
        let starter = starter(runner)

        #expect(await starter.start())

        #expect(starter.state == .started)
        #expect(runner.calls == [Self.kickstart, Self.bootstrap])
    }

    @Test func showsTheInstallCommandWithoutAPlist() async {
        let runner = FakeRunner([Self.notFound])
        let starter = starter(runner, plistExists: false)

        #expect(!(await starter.start()))

        let command = "cd '/Users/me/My code/harness/daemon' && uv run harness service install"
        #expect(starter.state == .notInstalled(command: command))
        #expect(runner.calls == [Self.kickstart])
    }

    @Test func reportsTheLastLineOfAFailedBootstrap() async {
        let runner = FakeRunner([
            Self.notFound,
            CommandOutput(status: 5, output: "Bootstrap failed: 5\nInput/output error"),
        ])
        let starter = starter(runner)

        #expect(!(await starter.start()))

        #expect(
            starter.state == .failed("launchctl could not load the service: Input/output error"))
    }

    @Test func reportsTheExitStatusOfASilentFailure() async {
        let runner = FakeRunner([Self.notFound, CommandOutput(status: 37, output: "")])
        let starter = starter(runner)

        await starter.start()

        #expect(starter.state == .failed("launchctl could not load the service: exit status 37"))
    }

    @Test func ignoresASecondStartWhileStarting() async {
        let runner = SlowRunner()
        let slow = ServiceStarter(
            runner: runner, uid: 501, home: Self.home, repoPath: nil, fileExists: { _ in true })
        let first = Task { await slow.start() }
        await runner.waitForCall()
        #expect(slow.state == .starting)
        #expect(!slow.offersStart(when: .disconnected))

        #expect(!(await slow.start()))

        runner.finish()
        #expect(await first.value)
        #expect(runner.callCount == 1)
        #expect(slow.state == .started)
    }

    @Test func offersToStartOnlyWhileTheDaemonIsUnreachable() async {
        let starter = starter(FakeRunner([Self.notFound]), plistExists: false)

        #expect(starter.offersStart(when: .disconnected))
        #expect(starter.offersStart(when: .reconnecting(attempt: 2, delay: 4)))
        #expect(!starter.offersStart(when: .connected))
        #expect(!starter.offersStart(when: .connecting))
        #expect(!starter.offersStart(when: .unauthorized))
        #expect(!starter.offersStart(when: .forbiddenOrigin))

        await starter.start()
        #expect(starter.offersStart(when: .disconnected))
        starter.reset()
        #expect(starter.state == .idle)
    }

    @Test func theLocalStarterUsesThisUsersDomainAndLaunchAgents() {
        let starter = ServiceStarter.local(repoPath: nil)
        let home = FileManager.default.homeDirectoryForCurrentUser.path

        #expect(starter.kickstart == ["kickstart", "-k", "gui/\(getuid())/com.harness.daemon"])
        let plist = "\(home)/Library/LaunchAgents/com.harness.daemon.plist"
        #expect(starter.bootstrap == ["bootstrap", "gui/\(getuid())", plist])
        #expect(starter.fileExists(home))
        #expect(!starter.fileExists("\(home)/no such file \(UUID())"))
        #expect(starter.runner is ProcessRunner)
    }

    @Test func installCommandsQuoteThePath() {
        #expect(
            DaemonService.installCommand(repoPath: "/a/it's")
                == "cd '/a/it'\\''s/daemon' && uv run harness service install")
        #expect(
            DaemonService.installCommand(repoPath: nil)
                == "cd <harness repository>/daemon && uv run harness service install")
    }
}

/// Holds its one call until `finish()`.
final class SlowRunner: CommandRunner {
    private let state = Mutex<(calls: Int, release: CheckedContinuation<Void, Never>?)>((0, nil))
    private let (called, calledContinuation) = AsyncStream<Void>.makeStream()

    var callCount: Int { state.withLock { $0.calls } }

    func run(_ executable: String, _ arguments: [String]) async -> CommandOutput {
        await withCheckedContinuation { continuation in
            state.withLock {
                $0.calls += 1
                $0.release = continuation
            }
            calledContinuation.yield()
        }
        return CommandOutput(status: 0, output: "")
    }

    func waitForCall() async {
        for await _ in called {
            return
        }
    }

    func finish() {
        state.withLock { $0.release }?.resume()
    }
}

@Suite struct ProcessRunnerTests {
    @Test func runsAProgramAndCollectsItsOutputAndStatus() async {
        let result = await ProcessRunner().run(
            "/bin/sh", ["-c", "echo out; echo err >&2; exit 3"])

        #expect(result.status == 3)
        #expect(result.output == "out\nerr")
    }

    @Test func reportsAProgramThatCannotStart() async {
        let result = await ProcessRunner().run("/no/such/program", [])

        #expect(result.status == -1)
        #expect(!result.output.isEmpty)
    }
}
