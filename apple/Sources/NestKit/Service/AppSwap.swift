import Foundation

/// What kind of build this is, read at run time. `bundle-app.sh` writes a developer build's
/// checkout into its Info.plist and a release build leaves it out, so a release carries no
/// path of the machine that built it.
public enum AppBuild {
    public static let checkoutKey = "NestCheckout"

    /// A developer build's checkout, for the service's install command; nil for a release, or
    /// once the checkout has moved.
    public static func checkout(
        info: [String: Any], fileExists: (String) -> Bool
    ) -> String? {
        guard let path = info[checkoutKey] as? String,
            fileExists(path + "/daemon/pyproject.toml")
        else { return nil }
        return path
    }

    public static var checkout: String? {
        checkout(info: Bundle.main.infoDictionary ?? [:]) {
            FileManager.default.fileExists(atPath: $0)
        }
    }
}

/// The app follows the daemon (B130): after an update or its undo the running daemon names
/// the app that belongs to it, and an app of another version swaps to that file, once a
/// launch. A version whose swap did not stick is not tried again, or a Mac where it cannot
/// work would quit and reopen forever.
@MainActor
public final class AppSwapper {
    public enum Outcome: Sendable, Equatable {
        case none
        /// The helper waits for this process: quit now.
        case swapping
        /// The last launch's swap to this version did not stick.
        case failed(String)
    }

    /// The version the last swap went to, until this app is that version.
    static let triedKey = "update.swapTried"

    private let spawner: any ProcessSpawner
    private let appPath: String
    private let ownVersion: String?
    private let dataFolder: URL
    private let pid: Int32
    private let environment: [String: String]
    private let preferences: any KeyValueStore
    private let developerBuild: Bool
    private let fileExists: @Sendable (String) -> Bool
    private var asked = false

    public init(
        spawner: any ProcessSpawner, appPath: String, ownVersion: String?, dataFolder: URL,
        pid: Int32, environment: [String: String], preferences: any KeyValueStore,
        developerBuild: Bool, fileExists: @escaping @Sendable (String) -> Bool
    ) {
        self.spawner = spawner
        self.appPath = appPath
        self.ownVersion = ownVersion
        self.dataFolder = dataFolder
        self.pid = pid
        self.environment = environment
        self.preferences = preferences
        self.developerBuild = developerBuild
        self.fileExists = fileExists
    }

    /// For this running app and This Mac's daemon.
    public static func local(dataFolder: URL) -> AppSwapper {
        let bundle = Bundle.main
        return AppSwapper(
            spawner: DetachedSpawner(), appPath: bundle.bundleURL.path,
            ownVersion: bundle.infoDictionary?["CFBundleShortVersionString"] as? String,
            dataFolder: dataFolder, pid: getpid(),
            environment: ProcessInfo.processInfo.environment,
            preferences: UserDefaultsStore(), developerBuild: AppBuild.checkout != nil,
            fileExists: { FileManager.default.fileExists(atPath: $0) })
    }

    public func follow(_ file: AppFile) -> Outcome {
        guard let ownVersion, !developerBuild, appPath.hasSuffix(".app") else { return .none }
        guard ownVersion != file.version else {
            preferences.set(nil, forKey: Self.triedKey)
            return .none
        }
        // Only here: the daemon can move to another version while this app stays open.
        guard !asked else { return .none }
        asked = true
        guard isOurs(file.path) else { return .none }
        guard preferences.string(forKey: Self.triedKey) != file.version else {
            return .failed(file.version)
        }
        preferences.set(file.version, forKey: Self.triedKey)
        let arguments = AppRelaunch.swapping(
            appPath: appPath, zipPath: file.path, pid: pid, environment: environment)
        guard (try? spawner.spawn(AppRelaunch.shell, arguments)) != nil else {
            return .failed(file.version)
        }
        return .swapping
    }

    /// Relaunch to update with a new app (B130): starts the helper that waits for the daemon
    /// to come back and opens the new app once, so the old one does not load again only to
    /// quit for the swap. True when it started and the app should quit; false leaves the
    /// plain reopen, as for a developer build.
    public func afterUpdate(to version: String, daemon: URL) -> Bool {
        guard let ownVersion, !developerBuild, appPath.hasSuffix(".app"), ownVersion != version,
            Self.isPlain(version)
        else { return false }
        let daemons = dataFolder.appending(path: "daemon", directoryHint: .isDirectory)
        let zip = daemons.appending(path: "\(version)/app-file").path
        guard isOurs(zip) else { return false }
        // A swap that does not stick opens this app again, whose connect tries once more as
        // after any update, then says so.
        let arguments = AppRelaunch.afterUpdate(
            appPath: appPath, zipPath: zip, version: version, pid: pid, daemon: daemon,
            updateFile: daemons.appending(path: "update.json").path, environment: environment)
        return (try? spawner.spawn(AppRelaunch.shell, arguments)) != nil
    }

    /// A version is a folder's name: no separators and no `..`.
    private static func isPlain(_ version: String) -> Bool {
        !version.isEmpty && !version.contains("..")
            && version.allSatisfy {
                $0.isASCII && ($0.isLetter || $0.isNumber || ".+-_".contains($0))
            }
    }

    /// `<data>/daemon/<version>/app-file`: the path comes from the daemon and what it names
    /// gets run, so nothing else is accepted.
    private func isOurs(_ path: String) -> Bool {
        let file = URL(filePath: path)
        let daemons = file.deletingLastPathComponent().deletingLastPathComponent()
        let expected = dataFolder.appending(path: "daemon", directoryHint: .isDirectory)
        return file.lastPathComponent == "app-file" && fileExists(path)
            && daemons.resolvingSymlinksInPath().standardizedFileURL.path
                == expected.resolvingSymlinksInPath().standardizedFileURL.path
    }
}
