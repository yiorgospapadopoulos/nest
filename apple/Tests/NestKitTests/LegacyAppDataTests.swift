import Foundation
import Testing

@testable import NestKit

/// B43: Nest's first launch copies the settings and backgrounds of the app from before the
/// rename (`local.harness.app`).
final class MemoryDomains: PreferenceDomains {
    var domains: [String: [String: Any]] = [:]

    func persistentDomain(forName domainName: String) -> [String: Any]? {
        domains[domainName]
    }

    func setPersistentDomain(_ domain: [String: Any], forName domainName: String) {
        domains[domainName] = domain
    }
}

@Suite struct LegacyAppDataTests {
    let defaults = MemoryDomains()
    let oldDomain = "nest-tests-old-\(UUID().uuidString)"
    let newDomain = "nest-tests-new-\(UUID().uuidString)"
    let home = FileManager.default.temporaryDirectory.appending(
        path: "nest-tests-\(UUID().uuidString)")

    var migration: LegacyAppData {
        LegacyAppData(defaults: defaults, home: home, oldDomain: oldDomain, newDomain: newDomain)
    }

    var support: URL { home.appending(path: "Library/Application Support") }

    func cleanUp() {
        try? FileManager.default.removeItem(at: home)
    }

    @Test func theNamesAreTheAppsBeforeAndAfterTheRename() {
        #expect(LegacyAppData.legacyBundleID == "local.harness.app")
        #expect(LegacyAppData.bundleID == "local.nest.app")
        let standard = LegacyAppData()
        #expect(standard.defaults as? UserDefaults === UserDefaults.standard)
        #expect(standard.oldDomain == "local.harness.app")
        #expect(standard.newDomain == "local.nest.app")
        #expect(standard.home == FileManager.default.homeDirectoryForCurrentUser)
    }

    @Test func everySettingIsCopiedOnceWithBackgroundPathsFollowing() {
        defer { cleanUp() }
        let oldImage = support.path + "/\(oldDomain)/Backgrounds/a.png"
        defaults.setPersistentDomain(
            [
                "appearance.theme": "dark",
                "appearance.background.image": oldImage,
                "appearance.background.projects": ["todo-ui": oldImage, "nest": "/elsewhere.png"],
                "recent": [oldImage, 3],
                "window.width": 1200,
            ], forName: oldDomain)
        defaults.setPersistentDomain(["NSWindow Frame main": "0 0 10 10"], forName: newDomain)

        #expect(migration.migrateDefaults())

        let copied = defaults.persistentDomain(forName: newDomain) ?? [:]
        let newImage = support.path + "/\(newDomain)/Backgrounds/a.png"
        #expect(copied["appearance.theme"] as? String == "dark")
        #expect(copied["appearance.background.image"] as? String == newImage)
        #expect(
            copied["appearance.background.projects"] as? [String: String] == [
                "todo-ui": newImage, "nest": "/elsewhere.png",
            ])
        let recent = copied["recent"] as? [Any]
        #expect(recent?.first as? String == newImage)
        #expect(recent?.last as? Int == 3)
        #expect(copied["window.width"] as? Int == 1200)
        #expect(copied["NSWindow Frame main"] as? String == "0 0 10 10")
        #expect(copied[LegacyAppData.marker] as? Bool == true)
        // The old app's settings stay.
        #expect(
            defaults.persistentDomain(forName: oldDomain)?["appearance.theme"] as? String == "dark")

        // Once only: a setting changed or removed since is not copied again.
        var changed = copied
        changed.removeValue(forKey: "appearance.theme")
        defaults.setPersistentDomain(changed, forName: newDomain)
        #expect(!migration.migrateDefaults())
        #expect(defaults.persistentDomain(forName: newDomain)?["appearance.theme"] == nil)
    }

    @Test func aSettingAlreadyThereIsKept() {
        defer { cleanUp() }
        defaults.setPersistentDomain(["appearance.theme": "dark"], forName: oldDomain)
        defaults.setPersistentDomain(["appearance.theme": "light"], forName: newDomain)

        #expect(migration.migrateDefaults())

        #expect(
            defaults.persistentDomain(forName: newDomain)?["appearance.theme"] as? String == "light"
        )
    }

    @Test func withoutTheOldAppNothingIsCopiedButItIsNotLookedForAgain() {
        defer { cleanUp() }

        #expect(!migration.migrateDefaults())

        #expect(
            defaults.persistentDomain(forName: newDomain)?[LegacyAppData.marker] as? Bool == true)
    }

    @Test func theBackgroundsFolderIsCopiedAndTheOldOneKept() throws {
        defer { cleanUp() }
        let files = FileManager.default
        let old = support.appending(path: oldDomain)
        try files.createDirectory(
            at: old.appending(path: "Backgrounds"), withIntermediateDirectories: true)
        try Data("png".utf8).write(to: old.appending(path: "Backgrounds/a.png"))

        #expect(migration.migrateSupportFolder())

        let new = support.appending(path: newDomain)
        #expect(try Data(contentsOf: new.appending(path: "Backgrounds/a.png")) == Data("png".utf8))
        #expect(files.fileExists(atPath: old.appending(path: "Backgrounds/a.png").path))
        #expect(!files.fileExists(atPath: support.appending(path: newDomain + ".moving").path))

        // A folder that is already there is left as it is.
        try Data("new".utf8).write(to: new.appending(path: "Backgrounds/a.png"))
        #expect(!migration.migrateSupportFolder())
        #expect(try Data(contentsOf: new.appending(path: "Backgrounds/a.png")) == Data("new".utf8))
    }

    @Test func noOldFolderOrAFailedCopyLeavesNothingHalfDone() throws {
        defer { cleanUp() }
        #expect(!migration.migrateSupportFolder())

        let files = FileManager.default
        try files.createDirectory(
            at: support.appending(path: oldDomain), withIntermediateDirectories: true)
        // A copy left from a launch that stopped part way blocks the copy; nothing is deleted.
        try files.createDirectory(
            at: support.appending(path: newDomain + ".moving"), withIntermediateDirectories: true)

        #expect(!migration.migrateSupportFolder())
        #expect(!files.fileExists(atPath: support.appending(path: newDomain).path))
        #expect(files.fileExists(atPath: support.appending(path: oldDomain).path))
    }

    @Test func runDoesBoth() throws {
        defer { cleanUp() }
        defaults.setPersistentDomain(["appearance.theme": "dark"], forName: oldDomain)
        try FileManager.default.createDirectory(
            at: support.appending(path: oldDomain), withIntermediateDirectories: true)

        migration.run()

        #expect(
            defaults.persistentDomain(forName: newDomain)?["appearance.theme"] as? String == "dark")
        #expect(FileManager.default.fileExists(atPath: support.appending(path: newDomain).path))
    }
}
