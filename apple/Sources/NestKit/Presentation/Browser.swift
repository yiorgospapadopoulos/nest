import Foundation

/// What typing in a browser pane's address field opens.
public enum BrowserAddress {
    static let localHosts: Set<String> = ["localhost", "127.0.0.1", "0.0.0.0", "[::1]"]
    static let search = "https://duckduckgo.com/"

    /// A full URL as typed; a bare port (`3000` or `:3000`) on localhost; a local host, or
    /// any host with a port, over http; a host with a dot over https; anything else is a
    /// web search. Nil for blank input.
    public static func url(from input: String) -> URL? {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        let bare = text.hasPrefix(":") ? String(text.dropFirst()) : text
        if let port = Int(bare), (1...65_535).contains(port) {
            return URL(string: "http://localhost:\(port)")
        }
        if text.contains("://") || text.hasPrefix("about:") {
            return URL(string: text)
        }
        if !text.contains(where: \.isWhitespace) {
            let (host, hasPort) = host(of: text)
            if localHosts.contains(host.lowercased()) || hasPort {
                return URL(string: "http://\(text)")
            }
            if host.contains(".") {
                return URL(string: "https://\(text)")
            }
        }
        var components = URLComponents(string: search)!
        components.queryItems = [URLQueryItem(name: "q", value: text)]
        return components.url
    }

    /// The host part of an address typed without a scheme, and whether a port follows it.
    static func host(of text: String) -> (host: String, hasPort: Bool) {
        let authority = text.prefix { $0 != "/" && $0 != "?" && $0 != "#" }
        if authority.hasPrefix("["), let end = authority.firstIndex(of: "]") {
            let host = authority[...end]
            return (String(host), authority[authority.index(after: end)...].hasPrefix(":"))
        }
        let parts = authority.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false)
        let hasPort = parts.count == 2 && Int(parts[1]) != nil
        return (String(parts[0]), hasPort)
    }
}

/// A server listening on a local TCP port, for the browser's Local servers menu.
public struct LocalServer: Sendable, Hashable, Identifiable {
    public let port: Int
    /// The process name as lsof shows it (at most nine characters).
    public let process: String

    public init(port: Int, process: String) {
        self.port = port
        self.process = process
    }

    public var id: Int { port }
    public var url: URL { URL(string: "http://localhost:\(port)")! }
}

/// Listening localhost TCP ports, from `lsof -nP -iTCP -sTCP:LISTEN`.
public enum LocalServers {
    public static let lsof = "/usr/sbin/lsof"
    public static let arguments = ["-nP", "-iTCP", "-sTCP:LISTEN"]
    /// The Nest daemon's own port.
    static let daemonPort = 8765
    /// Addresses reachable as localhost: any address, or loopback.
    static let reachable: Set<String> = ["*", "127.0.0.1", "[::1]", "[::]", "0.0.0.0"]
    /// macOS's own listeners (AirPlay, Continuity and the like), not dev servers.
    static let system: Set<String> = [
        "ControlCe", "rapportd", "sharingd", "launchd", "remoted", "identitys", "AirPlayXP",
    ]

    /// Runs lsof away from the main actor; no servers when it cannot run.
    public static func scan(runner: any CommandRunner) async -> [LocalServer] {
        parse(await runner.run(lsof, arguments).output)
    }

    /// One server per port, by port; the daemon and macOS's own listeners are left out.
    public static func parse(_ output: String) -> [LocalServer] {
        var servers: [Int: LocalServer] = [:]
        for line in output.split(separator: "\n") {
            let fields = line.split(whereSeparator: \.isWhitespace)
            guard fields.count >= 3, fields[fields.count - 1] == "(LISTEN)" else { continue }
            let name = fields[fields.count - 2]
            guard let colon = name.lastIndex(of: ":"),
                let port = Int(name[name.index(after: colon)...]),
                reachable.contains(String(name[..<colon])), port != daemonPort
            else { continue }
            let process = fields[0].replacingOccurrences(of: "\\x20", with: " ")
            if servers[port] == nil && !system.contains(process) {
                servers[port] = LocalServer(port: port, process: process)
            }
        }
        return servers.values.sorted { $0.port < $1.port }
    }
}
