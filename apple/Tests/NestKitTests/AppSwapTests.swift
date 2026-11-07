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
            appPath: app.path, zipPath: zip.path, pid: finished.processIdentifier, environment: [:])
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
