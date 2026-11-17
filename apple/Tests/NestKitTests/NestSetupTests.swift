import Foundation
import Synchronization
import Testing

@testable import NestKit

/// Plays a script's output and records how it was started.
final class FakeLineRunner: LineRunner {
    private let outputs: [StreamedOutput]
    private let started = Mutex<[(arguments: [String], environment: [String: String])]>([])

    init(_ outputs: [StreamedOutput]) {
        self.outputs = outputs
    }

    var runs: [(arguments: [String], environment: [String: String])] {
        started.withLock { $0 }
    }

    func run(_ executable: String, _ arguments: [String], environment: [String: String])
        -> AsyncStream<StreamedOutput>
    {
        started.withLock { $0.append(([executable] + arguments, environment)) }
        return AsyncStream { continuation in
            for output in outputs {
                continuation.yield(output)
            }
            continuation.finish()
        }
    }
}

/// Whether a released install exists, changed by the test as the script would.
final class InstallFlag: Sendable {
    private let state = Mutex(false)
    var value: Bool {
        get { state.withLock { $0 } }
        set { state.withLock { $0 = newValue } }
    }
}

@MainActor
@Suite struct NestSetupTests {
    static let script = "/Applications/Nest.app/Contents/Resources/install.sh"

    func setup(
        _ runner: FakeLineRunner, appPath: String = "/Applications/Nest.app",
        developerBuild: Bool = false, installed: InstallFlag = InstallFlag()
    ) -> NestSetup {
        NestSetup(
            runner: runner, script: Self.script, appPath: appPath,
            releaseURL: ReleasedInstall.defaultReleaseURL, environment: ["HOME": "/Users/me"],
            developerBuild: developerBuild, isInstalled: { installed.value })
    }

    @Test func runsTheBundledInstallerAsTheAppSoItLeavesTheAppAlone() async {
        let runner = FakeLineRunner([
            .line("Installing Nest 1.0.0"), .line("Starting Nest"),
            .line("Nest 1.0.0 is installed."), .exit(0),
        ])
        let setup = setup(runner)

        #expect(await setup.run())

        #expect(setup.phase == .finished)
        let run = runner.runs.first
        #expect(run?.arguments == ["/bin/sh", Self.script])
        #expect(run?.environment["NEST_SETUP_BY_APP"] == "1")
        #expect(run?.environment["NEST_MAC_APP"] == "/Applications/Nest.app")
        #expect(run?.environment["HOME"] == "/Users/me")
    }

    @Test func aFailureSaysWhatTheScriptSaidAndKeepsTheSetupScreen() async {
        let installed = InstallFlag()
        let runner = FakeLineRunner([
            .line("Installing Nest 1.0.0"), .problem("curl: (6) Could not resolve host"),
            .problem("Nest: Could not download nestd-1.0.0-py3-none-any.whl."), .exit(1),
        ])
        let setup = setup(runner, installed: installed)

        #expect(await setup.run() == false)
        // The script may have made the install before it stopped: still setup, not repair.
        installed.value = true

        #expect(setup.phase == .failed("Could not download nestd-1.0.0-py3-none-any.whl."))
        #expect(setup.isOffered)
        #expect(setup.terminalLine.hasPrefix("curl -fsSL "))
    }

    @Test func anAppOutsideApplicationsDoesNotRunTheInstaller() async {
        let path = "/private/var/folders/x/AppTranslocation/1/d/Nest.app"
        let runner = FakeLineRunner([.exit(0)])
        let setup = setup(runner, appPath: path)

        #expect(setup.isInApplications == false)
        #expect(await setup.run() == false)
        #expect(runner.runs.isEmpty)
        #expect(setup.phase == .ready)
    }

    @Test func onlyAReleasedAppOnAMacWithoutNestOffersSetup() {
        let installed = InstallFlag()
        #expect(setup(FakeLineRunner([]), installed: installed).isOffered)
        #expect(!setup(FakeLineRunner([]), developerBuild: true).isOffered)
        installed.value = true
        #expect(!setup(FakeLineRunner([]), installed: installed).isOffered)
    }

    @Test func theProcessRunnerGivesEachLineAsItComesAndTheExitStatus() async {
        var outputs: [StreamedOutput] = []
        let script = "echo one; echo oops >&2; printf last; exit 3"
        for await output in ProcessLineRunner().run(
            "/bin/sh", ["-c", script], environment: [:])
        {
            outputs.append(output)
        }

        #expect(
            outputs.filter { if case .line = $0 { true } else { false } } == [
                .line("one"), .line("last"),
            ])
        #expect(outputs.contains(.problem("oops")))
        #expect(outputs.last == .exit(3))
    }
}
