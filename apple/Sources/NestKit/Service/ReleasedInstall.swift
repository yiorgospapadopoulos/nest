import Foundation

/// A relaunch under way, as `<data>/daemon/update.json` holds it (daemon/src/nestd/updates/
/// app.py): the watcher clears it once the new version answers or the update went back.
public struct UpdateUnderWay: Codable, Sendable, Equatable {
    public var fromVersion: String
    public var toVersion: String
    public var startedAt: String

    public init(fromVersion: String, toVersion: String, startedAt: String) {
        self.fromVersion = fromVersion
        self.toVersion = toVersion
        self.startedAt = startedAt
    }

    private enum CodingKeys: String, CodingKey {
        case fromVersion = "from_version"
        case toVersion = "to_version"
        case startedAt = "started_at"
    }

    /// A note older than this is left over, not an update under way.
    static let fresh: TimeInterval = 5 * 60
    /// After this an update says it is taking longer than usual; most take a few seconds.
    static let slow: TimeInterval = 15

    /// When it started. The daemon writes microseconds, which the parser does not take, and
    /// none at all on a whole second.
    var started: Date? {
        let millis = startedAt.replacing(/(\.\d{3})\d+/) { String($0.output.1) }
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = parser.date(from: millis) {
            return date
        }
        parser.formatOptions = [.withInternetDateTime]
        return parser.date(from: millis)
    }

    /// Whether it is under way at `now`, not left over.
    public func isUnderWay(at now: Date) -> Bool {
        guard let started else { return false }
        return now.timeIntervalSince(started) < Self.fresh
    }

    /// Whether to say it is taking longer than usual.
    public func isSlow(at now: Date) -> Bool {
        guard let started else { return false }
        return now.timeIntervalSince(started) >= Self.slow
    }
}

/// A released install, read from Nest's data folder by the app itself, since the daemon may
/// be down (B130): an update under way, the address the install came from, and the `nest`
/// command that removes it. As the Linux app's install.rs.
public struct ReleasedInstall: Sendable {
    public static let defaultReleaseURL =
        "https://github.com/yiorgospapadopoulos/nest/releases/latest/download"

    public let dataFolder: URL
    let environment: [String: String]

    public init(dataFolder: URL, environment: [String: String]) {
        self.dataFolder = dataFolder
        self.environment = environment
    }

    var daemons: URL { dataFolder.appending(path: "daemon", directoryHint: .isDirectory) }
    var updateFile: URL { daemons.appending(path: "update.json") }

    /// The update under way, if the daemon's file says so and it is not left over.
    public func updating(at now: Date = Date()) -> UpdateUnderWay? {
        struct File: Decodable { var updating: UpdateUnderWay? }
        guard let data = try? Data(contentsOf: updateFile),
            let update = (try? JSONDecoder().decode(File.self, from: data))?.updating,
            update.isUnderWay(at: now)
        else { return nil }
        return update
    }

    /// As the daemon's release_url: the variable, else the file release/install.sh wrote,
    /// else GitHub.
    public var releaseURL: String {
        let file = try? String(
            contentsOf: dataFolder.appending(path: "release-url"), encoding: .utf8)
        let chosen = [environment["NEST_RELEASE_URL"], file]
            .compactMap { $0?.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first { !$0.isEmpty }
        return Self.trimmed(chosen ?? Self.defaultReleaseURL)
    }

    /// What repairs an install and keeps the data (release/install.sh), from the address the
    /// install came from, as the daemon's install_line: a piped script cannot tell it otherwise.
    public static func installLine(releaseURL: String) -> String {
        let url = trimmed(releaseURL)
        return url == defaultReleaseURL
            ? "curl -fsSL \(url)/install.sh | sh"
            : "curl -fsSL \(url)/install.sh | NEST_RELEASE_URL=\(url) sh"
    }

    private static func trimmed(_ url: String) -> String {
        var url = url
        while url.hasSuffix("/") {
            url.removeLast()
        }
        return url
    }

    /// `<data>/daemon/current/bin/nest`, with its links resolved, only while it stays inside
    /// the data folder's `daemon`: a checkout has none.
    public var nestCommand: String? {
        let command = daemons.appending(path: "current/bin/nest").resolvingSymlinksInPath()
        let inside = daemons.resolvingSymlinksInPath().standardizedFileURL.path + "/"
        var isFolder: ObjCBool = false
        guard command.standardizedFileURL.path.hasPrefix(inside),
            FileManager.default.fileExists(atPath: command.path, isDirectory: &isFolder),
            !isFolder.boolValue
        else { return nil }
        return command.path
    }

    /// `nest uninstall`, with `--delete-data` when chosen, in a session of its own so it
    /// outlives the app and the service it removes; the caller quits next. False when this is
    /// no released install, or it could not start.
    public func uninstall(deleteData: Bool, spawner: any ProcessSpawner) -> Bool {
        guard let nestCommand else { return false }
        let arguments = ["uninstall"] + (deleteData ? ["--delete-data"] : [])
        return (try? spawner.spawn(nestCommand, arguments)) != nil
    }
}
