import Foundation

/// What the connection banner offers.
public enum BannerAction: Sendable, Hashable {
    case retry
    /// Start Nest service, for This Mac's daemon only.
    case startService
    /// A remote refused this Mac's token: pair with it again.
    case pairAgain
    case useThisMac
}

extension ConnectionState {
    /// The daemon cannot be reached right now.
    public var isUnreachable: Bool {
        switch self {
        case .disconnected, .reconnecting: true
        default: false
        }
    }
}

/// The words of the remote daemon feature (B105): the banner, the Devices rows and why
/// the features that open things on this Mac are off while connected to a remote.
public enum DaemonText {
    public static let thisMac = "This Mac"

    /// Under the Daemons heading in Settings > Devices.
    public static let daemonsNote =
        "Where Nest runs. This Mac talks to one at a time; kept on this Mac only."

    /// The banner's line; `machine` is the remote's name, nil for This Mac, whose words
    /// stay as they were. Nil while connected or connecting.
    public static func banner(_ connection: ConnectionState, machine: String?) -> String? {
        switch connection {
        case .connected, .connecting:
            return nil
        case .disconnected:
            return "Not connected to \(machine ?? "the Nest daemon")"
        case .reconnecting(let attempt, let delay):
            let seconds = Int(delay.rounded(.up))
            let name = machine ?? "the Nest daemon"
            return attempt > 1
                ? "Can't reach \(name). Trying again in \(seconds)s" : "Reconnecting to \(name)"
        case .unauthorized:
            return "\(machine ?? "The daemon") did not accept this Mac's device token"
        case .forbiddenOrigin:
            return "\(machine ?? "The daemon") refused this connection"
        }
    }

    /// The banner's buttons. This Mac: Retry (not while its service starts) and Start
    /// Nest service when offered; a remote: Retry, or Pair again once it refused the
    /// token, and Use This Mac.
    public static func actions(
        _ connection: ConnectionState, remote: Bool, starting: Bool, offersStart: Bool
    ) -> [BannerAction] {
        guard remote else {
            return (starting ? [] : [.retry]) + (offersStart ? [.startService] : [])
        }
        return [connection == .unauthorized ? .pairAgain : .retry, .useThisMac]
    }

    /// Under the banner while a remote cannot be reached.
    public static func unreachableNote(_ machine: String) -> String {
        "Check that \(machine) is awake, the Nest service is running there and"
            + " `tailscale serve` is on."
    }

    /// "https://mac-mini.ts.net · last connected 18:42".
    public static func addressLine(_ url: URL, lastConnected: Date?, calendar: Calendar)
        -> String
    {
        guard let date = lastConnected else { return url.absoluteString }
        let parts = calendar.dateComponents([.hour, .minute], from: date)
        return url.absoluteString + " · last connected "
            + String(format: "%02d:%02d", parts.hour!, parts.minute!)
    }

    /// This Mac's row: "127.0.0.1:8765 · the default", or the override's URL.
    public static func localDetail(_ location: DaemonLocation) -> String {
        location.baseURL == APIClient.defaultBaseURL
            ? DaemonAddress.display(location.baseURL) + " · the default"
            : location.baseURL.absoluteString
    }

    /// A remote's row: `https://mac-mini.ts.net · paired 21 Oct as "MacBook Air"`.
    public static func remoteDetail(_ daemon: RemoteDaemon, calendar: Calendar) -> String {
        let parts = calendar.dateComponents([.day, .month], from: daemon.pairedAt)
        let date = "\(parts.day!) \(UsageText.shortMonths[parts.month! - 1])"
        return "\(daemon.baseURL.absoluteString) · paired \(date) as \"\(daemon.deviceName)\""
    }

    /// Remove's confirmation.
    public static func removeMessage(_ machine: String) -> String {
        "This Mac forgets the daemon and its token. To stop the token working there too,"
            + " revoke this Mac in Settings > Devices on \(machine)."
    }

    public static func appsOff(_ machine: String) -> String {
        "These open apps on the daemon's machine, so they are off while connected to"
            + " \(machine)."
    }

    public static func terminalOff(_ machine: String) -> String {
        "Terminal and the browser pane's local servers run on this Mac, not on \(machine)."
    }

    public static func copyPath(_ machine: String) -> String {
        "Copy folder path on \(machine)"
    }

    /// Add project's field label while on a remote, whose folders the picker cannot browse.
    public static func folder(_ machine: String) -> String {
        "Folder on \(machine)"
    }

    /// In place of an engine's Sign in: its sign-in page would open on the remote.
    public static func signInNote(_ machine: String) -> String {
        "Sign in on \(machine) itself; the sign-in page opens there. In Terminal on"
            + " \(machine) run:"
    }

    public static func signInCommand(_ provider: String) -> String {
        provider == ProviderInfo.claude ? "claude auth login" : "codex login"
    }
}
