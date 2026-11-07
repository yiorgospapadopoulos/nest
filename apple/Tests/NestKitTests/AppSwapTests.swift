import Foundation
import Testing

@testable import NestKit

@MainActor
@Suite struct AppSwapperTests {
    static let data = URL(filePath: "/data", directoryHint: .isDirectory)
    static let file = AppFile(version: "1.2.0", path: "/data/daemon/1.2.0/app-file")

    let spawner = FakeSpawner()
    let store = MemoryStore()

    private func swapper(
        own: String? = "1.1.0", developer: Bool = false, spawner: FakeSpawner? = nil
    ) -> AppSwapper {
        AppSwapper(
            spawner: spawner ?? self.spawner, appPath: "/Applications/Nest.app", ownVersion: own,
            dataFolder: Self.data, pid: 7, environment: [:], preferences: store,
            developerBuild: developer, fileExists: { _ in true })
    }

    @Test func anotherVersionSwapsOnceALaunch() {
        let swapper = swapper()
        #expect(swapper.follow(Self.file) == .swapping)
        #expect(swapper.follow(Self.file) == .none)
        #expect(spawner.spawned.count == 1)
    }

    @Test func theSameVersionOrADeveloperBuildStays() {
        #expect(swapper(own: "1.2.0").follow(Self.file) == .none)
        #expect(swapper(developer: true).follow(Self.file) == .none)
        #expect(spawner.spawned.isEmpty)
    }

    @Test func aDaemonThatMovesWhileTheAppIsOpenIsStillFollowed() {
        // Regression: the first connect, at the app's own version, used up the launch's one try.
        let swapper = swapper(own: "1.2.0")
        let moved = AppFile(version: "1.3.0", path: "/data/daemon/1.3.0/app-file")

        #expect(swapper.follow(Self.file) == .none)
        #expect(swapper.follow(moved) == .swapping)
    }

    @Test func aFileOutsideThisInstallIsRefused() {
        let elsewhere = AppFile(version: "1.2.0", path: "/tmp/daemon/1.2.0/app-file")
        let renamed = AppFile(version: "1.2.0", path: "/data/daemon/1.2.0/evil")
        #expect(swapper().follow(elsewhere) == .none)
        #expect(swapper().follow(renamed) == .none)
        #expect(spawner.spawned.isEmpty)
    }

    /// Otherwise a Mac where it cannot work would quit and reopen forever.
    @Test func aSwapThatDidNotStickIsNotTriedAgainUntilItDid() {
        #expect(swapper().follow(Self.file) == .swapping)
        #expect(swapper().follow(Self.file) == .failed("1.2.0"))
        #expect(spawner.spawned.count == 1)
        #expect(swapper(own: "1.2.0").follow(Self.file) == .none)
        #expect(swapper().follow(Self.file) == .swapping)
    }

    @Test func aHelperThatCannotStartKeepsTheAppOpen() {
        #expect(swapper(spawner: FakeSpawner(fails: true)).follow(Self.file) == .failed("1.2.0"))
    }

    static let daemon = URL(string: "http://127.0.0.1:8765")!

    /// Relaunch to update with a new app starts the one helper that opens it once (B130).
    @Test func aRelaunchWithANewAppStartsTheHelperThatOpensItOnce() throws {
        #expect(swapper().afterUpdate(to: "1.2.0", daemon: Self.daemon))
        let arguments = try #require(spawner.spawned.first)
        #expect(arguments.first == AppRelaunch.shell)
        let script = try #require(arguments.last)
        #expect(script.contains("'/data/daemon/1.2.0/app-file'"))
        #expect(script.contains("'/data/daemon/update.json'"))
        #expect(script.contains("'http://127.0.0.1:8765/api/health'"))
    }

    @Test func aDeveloperBuildOrAStrangeVersionKeepsThePlainReopen() {
        #expect(!swapper(developer: true).afterUpdate(to: "1.2.0", daemon: Self.daemon))
        #expect(!swapper(own: "1.2.0").afterUpdate(to: "1.2.0", daemon: Self.daemon))
        #expect(!swapper().afterUpdate(to: "../../etc", daemon: Self.daemon))
        #expect(!swapper().afterUpdate(to: "1.2/../1.3", daemon: Self.daemon))
        #expect(
            !swapper(spawner: FakeSpawner(fails: true)).afterUpdate(
                to: "1.2.0", daemon: Self.daemon))
        #expect(spawner.spawned.isEmpty)
    }
}

/// The swap's script itself, run on real folders with spaces in their paths; only `open` is
/// a stand-in, which records what it was given.
@Suite struct AppSwapScriptTests {
    let root: URL
    let app: URL
    let zip: URL
    let opened: URL

    init() throws {
        root = FileManager.default.temporaryDirectory
            .appending(path: "nest swap \(UUID().uuidString)", directoryHint: .isDirectory)
        app = root.appending(path: "My Apps/Nest.app", directoryHint: .isDirectory)
        zip = root.appending(path: "the data/app-file")
        opened = root.appending(path: "opened")
        let manager = FileManager.default
        try manager.createDirectory(
            at: zip.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Self.makeApp(at: app, version: "old")
        let bin = root.appending(path: "bin", directoryHint: .isDirectory)
        try manager.createDirectory(at: bin, withIntermediateDirectories: true)
        try Self.tool(bin.appending(path: "open"), "printf '%s\\n' \"$@\" >> \"$OPENED\"")
    }

    private static func tool(_ path: URL, _ body: String) throws {
        try "#!/bin/sh\n\(body)\n".write(to: path, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: path.path)
    }

    private static func makeApp(at app: URL, version: String) throws {
        let binary = app.appending(path: "Contents/MacOS/Nest")
        try FileManager.default.createDirectory(
            at: binary.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Self.tool(binary, "echo \(version)")
    }

    private func version(of app: URL) throws -> String {
        try String(contentsOf: app.appending(path: "Contents/MacOS/Nest"), encoding: .utf8)
    }

    private func zipApp(version: String) throws {
        let new = root.appending(path: "built/Nest.app", directoryHint: .isDirectory)
        try Self.makeApp(at: new, version: version)
        try run("/usr/bin/ditto", ["-c", "-k", "--keepParent", new.path, zip.path])
    }

    @discardableResult
    private func run(_ program: String, _ arguments: [String]) throws -> Int32 {
        let process = Process()
        process.executableURL = URL(filePath: program)
        process.arguments = arguments
        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = root.appending(path: "bin").path + ":/usr/bin:/bin"
        environment["OPENED"] = opened.path
        process.environment = environment
        try process.run()
        process.waitUntilExit()
        return process.terminationStatus
    }

    /// Runs the script for a process that has already quit.
    private func swap() throws {
        let finished = Process()
        finished.executableURL = URL(filePath: "/usr/bin/true")
        try finished.run()
        finished.waitUntilExit()
        let arguments = AppRelaunch.swapping(
            appPath: app.path, zipPath: zip.path, pid: finished.processIdentifier, environment: [:],
            log: root.appending(path: "logs/app-update.log").path)
        try run(AppRelaunch.shell, arguments)
    }

    private var leftovers: [String] {
        let folder = app.deletingLastPathComponent().path
        let names = (try? FileManager.default.contentsOfDirectory(atPath: folder)) ?? []
        return names.filter { $0 != "Nest.app" }
    }

    private func openedPaths() throws -> [String] {
        try String(contentsOf: opened, encoding: .utf8).split(separator: "\n").map(String.init)
    }

    @Test func theNewAppReplacesTheOldAndOpens() throws {
        defer { try? FileManager.default.removeItem(at: root) }
        try zipApp(version: "new")
        try swap()
        #expect(try version(of: app).contains("echo new"))
        #expect(try openedPaths() == [app.path])
        #expect(leftovers.isEmpty)
    }

    @Test func aBrokenZipLeavesTheOldAppAndOpensIt() throws {
        defer { try? FileManager.default.removeItem(at: root) }
        try "not a zip".write(to: zip, atomically: true, encoding: .utf8)
        try swap()
        #expect(try version(of: app).contains("echo old"))
        #expect(try openedPaths() == [app.path])
        #expect(leftovers.isEmpty)
    }

    @Test func aZipWithNoAppInItLeavesTheOldApp() throws {
        defer { try? FileManager.default.removeItem(at: root) }
        let other = root.appending(path: "built/Other", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: other, withIntermediateDirectories: true)
        try run("/usr/bin/ditto", ["-c", "-k", "--keepParent", other.path, zip.path])
        try swap()
        #expect(try version(of: app).contains("echo old"))
        #expect(try openedPaths() == [app.path])
    }

    @Test func aNewAppThatCannotOpenPutsTheOldOneBack() throws {
        defer { try? FileManager.default.removeItem(at: root) }
        try zipApp(version: "new")
        // Fails the first time, as for a damaged app, and works the second.
        let once = root.appending(path: "failed")
        try Self.tool(
            root.appending(path: "bin/open"),
            "[ -e '\(once.path)' ] || { touch '\(once.path)'; exit 1; }\n"
                + "printf '%s\\n' \"$@\" >> \"$OPENED\"")
        try swap()
        #expect(try version(of: app).contains("echo old"))
        #expect(try openedPaths() == [app.path])
        #expect(leftovers.isEmpty)
    }
}

/// The helper after Relaunch to update (B130), run for real against a stand-in daemon that
/// serves `/api/health` from a folder, and a stand-in `open`.
@Suite(.serialized) struct AfterUpdateScriptTests {
    let root: URL
    let app: URL
    let zip: URL
    let opened: URL
    let health: URL
    let updateFile: URL
    let log: URL

    init() throws {
        root = FileManager.default.temporaryDirectory
            .appending(path: "nest after update \(UUID().uuidString)", directoryHint: .isDirectory)
        app = root.appending(path: "My Apps/Nest.app", directoryHint: .isDirectory)
        zip = root.appending(path: "the data/daemon/0.2.0/app-file")
        opened = root.appending(path: "opened")
        health = root.appending(path: "served/api/health")
        updateFile = root.appending(path: "the data/daemon/update.json")
        log = root.appending(path: "the data/logs/app-update.log")
        let manager = FileManager.default
        for folder in [zip, health] {
            try manager.createDirectory(
                at: folder.deletingLastPathComponent(), withIntermediateDirectories: true)
        }
        try Self.makeApp(at: app, version: "old")
        let new = root.appending(path: "built/Nest.app", directoryHint: .isDirectory)
        try Self.makeApp(at: new, version: "new")
        _ = try Self.run("/usr/bin/ditto", ["-c", "-k", "--keepParent", new.path, zip.path])
        let bin = root.appending(path: "bin", directoryHint: .isDirectory)
        try manager.createDirectory(at: bin, withIntermediateDirectories: true)
        try Self.tool(bin.appending(path: "open"), "printf '%s\\n' \"$@\" >> \"$OPENED\"")
    }

    private static func tool(_ path: URL, _ body: String) throws {
        try "#!/bin/sh\n\(body)\n".write(to: path, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: path.path)
    }

    private static func makeApp(at app: URL, version: String) throws {
        let binary = app.appending(path: "Contents/MacOS/Nest")
        try FileManager.default.createDirectory(
            at: binary.deletingLastPathComponent(), withIntermediateDirectories: true)
        try tool(binary, "echo \(version)")
    }

    private static func run(_ program: String, _ arguments: [String]) throws -> Process {
        let process = Process()
        process.executableURL = URL(filePath: program)
        process.arguments = arguments
        try process.run()
        process.waitUntilExit()
        return process
    }

    /// A plain HTTP server on a free port, serving `served/`; its port.
    private func serve() throws -> (Process, Int) {
        let portFile = root.appending(path: "port")
        let server = Process()
        server.executableURL = URL(filePath: "/usr/bin/python3")
        server.arguments = [
            "-c",
            "import http.server, os, sys\n"
                + "os.chdir(sys.argv[1])\n"
                + "class Quiet(http.server.SimpleHTTPRequestHandler):\n"
                + "    def log_message(self, *args): pass\n"
                + "s = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Quiet)\n"
                + "open(sys.argv[2], 'w').write(str(s.server_port))\n"
                + "s.serve_forever()\n",
            root.appending(path: "served").path, portFile.path,
        ]
        try server.run()
        let deadline = Date().addingTimeInterval(10)
        while Date() < deadline {
            if let text = try? String(contentsOf: portFile, encoding: .utf8), let port = Int(text) {
                return (server, port)
            }
            Thread.sleep(forTimeInterval: 0.05)
        }
        server.terminate()
        throw CocoaError(.fileReadNoSuchFile)
    }

    private func answer(_ version: String) throws {
        try #"{"status":"ok","version":"\#(version)","machine":"m"}"#
            .write(to: health, atomically: true, encoding: .utf8)
    }

    private func updating(_ on: Bool) throws {
        let note =
            on
            ? #"{"from_version":"0.1.0","to_version":"0.2.0","started_at":"2026-11-07T10:00:00+00:00"}"#
            : "null"
        try #"{"ready":null,"updating":\#(note),"previous":"0.1.0"}"#
            .write(to: updateFile, atomically: true, encoding: .utf8)
    }

    /// Starts the helper for a process that has already quit; it runs in the background.
    private func startHelper(port: Int, openWithin: TimeInterval = 20) throws -> Process {
        let finished = try Self.run("/usr/bin/true", [])
        let arguments = AppRelaunch.afterUpdate(
            appPath: app.path, zipPath: zip.path, version: "0.2.0",
            pid: finished.processIdentifier,
            daemon: try #require(URL(string: "http://127.0.0.1:\(port)")),
            updateFile: updateFile.path, environment: [:], log: log.path,
            openWithin: openWithin)
        let helper = Process()
        helper.executableURL = URL(filePath: AppRelaunch.shell)
        helper.arguments = arguments
        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = root.appending(path: "bin").path + ":/usr/bin:/bin"
        environment["OPENED"] = opened.path
        helper.environment = environment
        try helper.run()
        return helper
    }

    private func finish(_ helper: Process, within seconds: Double) -> Bool {
        let deadline = Date().addingTimeInterval(seconds)
        while helper.isRunning, Date() < deadline {
            Thread.sleep(forTimeInterval: 0.1)
        }
        let finished = !helper.isRunning
        if !finished {
            helper.terminate()
        }
        return finished
    }

    private func version() throws -> String {
        try String(contentsOf: app.appending(path: "Contents/MacOS/Nest"), encoding: .utf8)
    }

    private func openedPaths() -> [String] {
        ((try? String(contentsOf: opened, encoding: .utf8)) ?? "")
            .split(separator: "\n").map(String.init)
    }

    @Test func theNewVersionAnsweringSwapsAndOpensTheNewAppOnce() throws {
        defer { try? FileManager.default.removeItem(at: root) }
        let (server, port) = try serve()
        defer { server.terminate() }
        try updating(true)
        try answer("0.1.0")
        let helper = try startHelper(port: port)
        // Regression: the old daemon, still answering just after the relaunch, is not the
        // update going back.
        Thread.sleep(forTimeInterval: 1.5)
        #expect(helper.isRunning)
        #expect(openedPaths().isEmpty)

        try answer("0.2.0")
        #expect(finish(helper, within: 10))
        #expect(try version().contains("echo new"))
        #expect(openedPaths() == [app.path])
    }

    @Test func anUpdateThatWentBackOpensTheOldAppAsItIs() throws {
        defer { try? FileManager.default.removeItem(at: root) }
        let (server, port) = try serve()
        defer { server.terminate() }
        try updating(false)
        try answer("0.1.0")
        let helper = try startHelper(port: port)
        #expect(finish(helper, within: 10))
        #expect(try version().contains("echo old"))
        #expect(openedPaths() == [app.path])
    }

    /// Regression (B130, fix 27): a new daemon that crashed and went back took 33 seconds in
    /// the VM, with no Nest on screen the whole time, so the user opened it by hand. A daemon
    /// slower than the wait gets the old app back at once, which shows the update's progress
    /// and swaps itself later; the helper says what it did in its log.
    @Test func aSlowDaemonGetsTheOldAppBackAtOnce() throws {
        defer { try? FileManager.default.removeItem(at: root) }
        let (server, port) = try serve()
        defer { server.terminate() }
        try updating(true)
        try answer("0.1.0")
        let helper = try startHelper(port: port, openWithin: 1)
        #expect(finish(helper, within: 10))
        #expect(try version().contains("echo old"))
        #expect(openedPaths() == [app.path])
        let lines = try String(contentsOf: log, encoding: .utf8)
        #expect(lines.contains("the daemon is not back yet"))
    }

    /// An app the user opened while the helper waited swaps itself on connect: the helper
    /// never moves the bundle out from under it.
    @Test func anAppAlreadyOpenIsNotSwappedUnderIt() throws {
        defer { try? FileManager.default.removeItem(at: root) }
        let binary = app.appending(path: "Contents/MacOS/Nest")
        try FileManager.default.removeItem(at: binary)
        try FileManager.default.copyItem(atPath: "/bin/sleep", toPath: binary.path)
        let running = Process()
        running.executableURL = binary
        running.arguments = ["30"]
        try running.run()
        defer { running.terminate() }
        let (server, port) = try serve()
        defer { server.terminate() }
        try updating(true)
        try answer("0.2.0")
        let helper = try startHelper(port: port)
        #expect(finish(helper, within: 10))
        #expect(running.isRunning)
        #expect(openedPaths().isEmpty)
        #expect(FileManager.default.contentsEqual(atPath: binary.path, andPath: "/bin/sleep"))
        #expect(try String(contentsOf: log, encoding: .utf8).contains("Nest is open already"))
    }
}
