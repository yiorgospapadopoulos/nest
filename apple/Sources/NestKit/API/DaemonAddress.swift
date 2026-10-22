import Foundation

/// Why a typed daemon address was not taken.
public enum DaemonAddressError: LocalizedError, Sendable, Equatable {
    case empty
    case invalid
    case scheme
    /// Plain http to another machine.
    case insecure
    case credentials
    /// A path, query or fragment.
    case extra

    public var message: String {
        switch self {
        case .empty: "Enter the daemon's address"
        case .invalid: "This is not an address, such as mac-mini.tail1a2b.ts.net"
        case .scheme: "The address must start with https://"
        case .insecure: "Use https: plain http is only for a daemon on this Mac"
        case .credentials: "The address cannot hold a user name or password"
        case .extra: "Give only the machine's address, without a path, query or fragment"
        }
    }

    public var errorDescription: String? { message }
}

/// The address of a daemon on another machine, as the user types it: a bare name such as
/// "mac-mini.tail1a2b.ts.net" means https. Plain http is only for a loopback host (a test
/// daemon on this Mac). The result is the base URL without a trailing slash.
public enum DaemonAddress {
    public static func parse(_ text: String) throws(DaemonAddressError) -> URL {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw .empty }
        // A closure, as in `SocketTokenStore`: a `CharacterSet.contains` method reference
        // went wrong in the release build.
        guard
            !trimmed.unicodeScalars.contains(where: {
                CharacterSet.whitespacesAndNewlines.contains($0)
            })
        else { throw .invalid }
        let full = trimmed.contains("://") ? trimmed : "https://" + trimmed
        guard var parts = URLComponents(string: full), let host = parts.percentEncodedHost,
            !host.isEmpty, !host.contains("%")
        else { throw .invalid }
        guard let scheme = parts.scheme?.lowercased(), ["http", "https"].contains(scheme) else {
            throw .scheme
        }
        guard parts.user == nil, parts.password == nil else { throw .credentials }
        guard parts.query == nil, parts.fragment == nil, ["", "/"].contains(parts.path) else {
            throw .extra
        }
        let lowered = host.lowercased()
        guard scheme == "https" || DaemonLocation.loopbackHosts.contains(lowered) else {
            throw .insecure
        }
        parts.scheme = scheme
        parts.percentEncodedHost = lowered
        parts.path = ""
        guard let url = parts.url else { throw .invalid }
        return url
    }

    /// The address without its scheme, such as "mac-mini.ts.net" or "127.0.0.1:8765".
    public static func display(_ url: URL) -> String {
        let text = url.absoluteString
        guard let range = text.range(of: "://") else { return text }
        return String(text[range.upperBound...])
    }
}
