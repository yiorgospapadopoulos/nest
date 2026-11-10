import Foundation
import Testing

@testable import NestKit

/// What the app reads from a released install's data folder while the daemon is down, and
/// the folders Settings makes before opening them (B130). On real temporary folders.
@Suite struct ReleasedInstallTests {
    let root: URL

    init() throws {
        root = FileManager.default.temporaryDirectory
            .appending(path: "nest install \(UUID().uuidString)", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(
            at: root.appending(path: "data/daemon"), withIntermediateDirectories: true)
    }

    private var data: URL { root.appending(path: "data", directoryHint: .isDirectory) }

    private func write(_ text: String, to path: String) throws {
        let file = root.appending(path: path)
        try FileManager.default.createDirectory(
            at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try text.write(to: file, atomically: true, encoding: .utf8)
    }

    @Test func anUpdateUnderWayIsReadFromTheDaemonsFile() throws {
        defer { try? FileManager.default.removeItem(at: root) }
        let install = ReleasedInstall(dataFolder: data, environment: [:])
        #expect(install.updating() == nil)
        try write(#"{"ready":null,"updating":null,"refused":[]}"#, to: "data/daemon/update.json")
        #expect(install.updating() == nil)

        try write(
            #"{"ready":null,"updating":{"from_version":"0.1.1","to_version":"0.1.2","#
                + #""started_at":"2026-11-07T10:00:00.123456+00:00"},"previous":"0.1.1"}"#,
            to: "data/daemon/update.json")
        let started = try #require(
            ISO8601DateFormatter().date(from: "2026-11-07T10:00:00+00:00"))
        #expect(install.updating(at: started.addingTimeInterval(20))?.toVersion == "0.1.2")
        // Left over from long ago, not an update under way.
        #expect(install.updating(at: started.addingTimeInterval(600)) == nil)
    }

    @Test func theRepairLineUsesTheAddressTheInstallCameFrom() throws {
        defer { try? FileManager.default.removeItem(at: root) }
        #expect(
            ReleasedInstall(dataFolder: data, environment: [:]).releaseURL
                == ReleasedInstall.defaultReleaseURL)
        try write("http://192.168.64.1:41051/\n", to: "data/release-url")
        #expect(
            ReleasedInstall(dataFolder: data, environment: [:]).releaseURL
                == "http://192.168.64.1:41051")
        let chosen = ReleasedInstall(
            dataFolder: data, environment: ["NEST_RELEASE_URL": "http://127.0.0.1:41055"])
        #expect(chosen.releaseURL == "http://127.0.0.1:41055")
        #expect(
            ReleasedInstall.installLine(releaseURL: ReleasedInstall.defaultReleaseURL + "/")
                == "curl -fsSL https://yiorgospapadopoulos.github.io/nest/install.sh | sh")
    }

    /// What Uninstall runs: only a `nest` inside this install's own `daemon` folder.
    @Test func onlyANestCommandInsideTheDataFolderCounts() throws {
        defer { try? FileManager.default.removeItem(at: root) }
        let manager = FileManager.default
        #expect(ReleasedInstall(dataFolder: data, environment: [:]).nestCommand == nil)

        try write("#!/bin/sh\n", to: "elsewhere/bin/nest")
        let current = data.appending(path: "daemon/current")
        try manager.createSymbolicLink(
            at: current, withDestinationURL: root.appending(path: "elsewhere"))
        #expect(ReleasedInstall(dataFolder: data, environment: [:]).nestCommand == nil)

        try manager.removeItem(at: current)
        try write("#!/bin/sh\n", to: "data/daemon/0.1.2/bin/nest")
        try manager.createSymbolicLink(
            at: current, withDestinationURL: data.appending(path: "daemon/0.1.2"))
        let command = try #require(
            ReleasedInstall(dataFolder: data, environment: [:]).nestCommand)
        #expect(command.hasSuffix("/data/daemon/0.1.2/bin/nest"))
    }

    @Test func uninstallStartsNestWithTheUsersChoice() throws {
        defer { try? FileManager.default.removeItem(at: root) }
        let install = ReleasedInstall(dataFolder: data, environment: [:])
        let spawner = FakeSpawner()
        #expect(!install.uninstall(deleteData: false, spawner: spawner))
        #expect(spawner.spawned.isEmpty)

        try write("#!/bin/sh\n", to: "data/daemon/0.1.2/bin/nest")
        try FileManager.default.createSymbolicLink(
            at: data.appending(path: "daemon/current"),
            withDestinationURL: data.appending(path: "daemon/0.1.2"))
        #expect(install.uninstall(deleteData: false, spawner: spawner))
        #expect(install.uninstall(deleteData: true, spawner: spawner))
        #expect(
            spawner.spawned.map { Array($0.dropFirst()) } == [
                ["uninstall"], ["uninstall", "--delete-data"],
            ])
    }

    /// Regression (B130): Open folder did nothing on a new Mac, whose skills folder is not
    /// there yet.
    @Test func aMissingFolderInTheHomeFolderIsMade() throws {
        defer { try? FileManager.default.removeItem(at: root) }
        let home = root.appending(path: "home", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
        let skills = home.appending(path: ".claude/skills").path
        try HomeFolder.make(skills, home: home)
        var isFolder: ObjCBool = false
        #expect(FileManager.default.fileExists(atPath: skills, isDirectory: &isFolder))
        #expect(isFolder.boolValue)
        try HomeFolder.make(skills, home: home)
    }

    @Test func nothingIsMadeOutsideTheHomeFolder() throws {
        defer { try? FileManager.default.removeItem(at: root) }
        let home = root.appending(path: "home", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
        let outside = root.appending(path: "outside/skills").path
        #expect(throws: HomeFolder.Refused.self) { try HomeFolder.make(outside, home: home) }
        #expect(throws: HomeFolder.Refused.self) {
            try HomeFolder.make(home.path + "/../outside/skills", home: home)
        }
        #expect(throws: HomeFolder.Refused.self) { try HomeFolder.make("relative", home: home) }
        #expect(!FileManager.default.fileExists(atPath: root.appending(path: "outside").path))
    }
}
