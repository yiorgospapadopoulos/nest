import Foundation

/// Which daemon the app talks to: the default one on this Mac, or a test daemon named by
/// `NEST_DAEMON_URL` (its base URL) and `NEST_DATA_DIR` (its data folder, holding
/// `token.sock`, the same variable the daemon reads). Unset or empty variables keep the
/// defaults. Only a plain http or https loopback URL is used, so the app never talks to
/// anything but this Mac.
public struct DaemonLocation: Sendable, Equatable {
    public let baseURL: URL
    public let dataFolder: URL

    public init(
        environment: [String: String],
        home: URL = FileManager.default.homeDirectoryForCurrentUser
    ) {
        baseURL = environment["NEST_DAEMON_URL"].flatMap(Self.loopback) ?? APIClient.defaultBaseURL
        if let folder = environment["NEST_DATA_DIR"], !folder.isEmpty {
            dataFolder = URL(filePath: folder, directoryHint: .isDirectory)
        } else {
            dataFolder = Self.defaultDataFolder(home: home)
        }
    }

    /// The daemon's own default data folder.
    public static func defaultDataFolder(
        home: URL = FileManager.default.homeDirectoryForCurrentUser
    ) -> URL {
        home.appending(path: "Library/Application Support/nest", directoryHint: .isDirectory)
    }

    static let loopbackHosts: Set<String> = ["127.0.0.1", "::1", "[::1]", "localhost"]

    /// The URL when it is a scheme, a loopback host and an optional port, nothing more.
    static func loopback(_ text: String) -> URL? {
        guard let parts = URLComponents(string: text), let url = parts.url,
            let scheme = parts.scheme?.lowercased(), ["http", "https"].contains(scheme),
            let host = parts.host?.lowercased(), loopbackHosts.contains(host),
            parts.user == nil, parts.password == nil, parts.query == nil,
            parts.fragment == nil, ["", "/"].contains(parts.path)
        else { return nil }
        return url
    }
}
