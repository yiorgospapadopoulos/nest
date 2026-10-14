import Foundation

/// Reads and writes whole preference domains; `UserDefaults` in the app, a fake in tests.
public protocol PreferenceDomains: AnyObject {
    func persistentDomain(forName domainName: String) -> [String: Any]?
    func setPersistentDomain(_ domain: [String: Any], forName domainName: String)
}

extension UserDefaults: PreferenceDomains {}

/// The settings and backgrounds of the Mac app from before the rename to Nest (B43), copied
/// on Nest's first launch. Settings are copied once (a marker records it), without replacing
/// any Nest already has, with background paths pointing into Nest's own folder. The
/// backgrounds folder is copied when Nest has none yet. The old app's data is never changed.
public struct LegacyAppData {
    public static let bundleID = "local.nest.app"
    public static let legacyBundleID = "local.harness.app"
    static let marker = "nest.migratedFromHarness"

    let defaults: any PreferenceDomains
    let home: URL
    let oldDomain: String
    let newDomain: String

    public init(
        defaults: any PreferenceDomains = UserDefaults.standard,
        home: URL = FileManager.default.homeDirectoryForCurrentUser,
        oldDomain: String = Self.legacyBundleID, newDomain: String = Self.bundleID
    ) {
        self.defaults = defaults
        self.home = home
        self.oldDomain = oldDomain
        self.newDomain = newDomain
    }

    public func run() {
        migrateDefaults()
        migrateSupportFolder()
    }

    /// Whether any setting was copied.
    @discardableResult func migrateDefaults() -> Bool {
        var current = defaults.persistentDomain(forName: newDomain) ?? [:]
        guard current[Self.marker] == nil else { return false }
        let old = defaults.persistentDomain(forName: oldDomain) ?? [:]
        for (key, value) in old where current[key] == nil {
            current[key] = followingSupportFolder(value)
        }
        current[Self.marker] = true
        defaults.setPersistentDomain(current, forName: newDomain)
        return !old.isEmpty
    }

    /// Whether the folder was copied. The copy is made under a temporary name first, so a
    /// launch that stops part way never leaves half a folder under Nest's name.
    @discardableResult func migrateSupportFolder() -> Bool {
        let files = FileManager.default
        let support = home.appending(path: "Library/Application Support")
        let old = support.appending(path: oldDomain)
        let new = support.appending(path: newDomain)
        guard files.fileExists(atPath: old.path), !files.fileExists(atPath: new.path) else {
            return false
        }
        let staging = support.appending(path: newDomain + ".moving")
        do {
            try files.copyItem(at: old, to: staging)
            try files.moveItem(at: staging, to: new)
        } catch {
            return false
        }
        return true
    }

    /// A saved path into the old app's folder points into Nest's instead.
    private func followingSupportFolder(_ value: Any) -> Any {
        switch value {
        case let text as String:
            text.replacingOccurrences(
                of: "/Application Support/\(oldDomain)/", with: "/Application Support/\(newDomain)/"
            )
        case let items as [String: Any]:
            items.mapValues(followingSupportFolder)
        case let items as [Any]:
            items.map(followingSupportFolder)
        default:
            value
        }
    }
}
