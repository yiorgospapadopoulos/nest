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

/// What the window shows while This Mac's daemon cannot be reached at launch (B130, screen
/// Z), from a second failed try on, so a daemon just starting shows no alarm, until it
/// connects. A daemon lost later has the banner instead. While an update has the daemon down,
/// its progress shows at once, never the repair line, and stays until the daemon answers.
/// Otherwise the app first starts the service once by itself, and only if the daemon is
/// still down after that shows the line.
public struct DaemonDownWatch: Sendable, Equatable {
    public enum Screen: Sendable, Equatable {
        case none
        case updating(UpdateUnderWay)
        case down
    }

    private enum Start: Sendable, Equatable {
        case notYet, running, done
    }

    /// How long the updating screen waits for the daemon once `update.json` no longer says
    /// so: going back, the watcher clears it and only then starts the old version.
    static let afterUpdate: TimeInterval = 30

    public private(set) var screen = Screen.none
    private var connected = false
    /// A second try failed since launch, or since the app's own start of the service.
    private var lost = false
    private var update: UpdateUnderWay?
    /// When `update.json` stopped saying so while the updating screen showed.
    private var updateEnded: Date?
    private var start = Start.notYet

    public init() {}

    public var isDown: Bool { screen != .none }

    /// True when the app should start the service now: once, and never during an update,
    /// whose watcher is at work. `startFinished()` follows it. `update` is This Mac's update
    /// under way, as `update.json` says now. A try only starting tells nothing and changes
    /// nothing: the updating screen starts one every second, and taking it for "no update"
    /// had that screen flicker out and back each time, starting the service mid-update.
    public mutating func note(
        _ connection: ConnectionState, remote: Bool, update: UpdateUnderWay?,
        at now: Date = Date()
    ) -> Bool {
        switch connection {
        case .connected:
            connected = true
            lost = false
            screen = .none
            return false
        case .connecting:
            return false
        case .reconnecting(let attempt, _) where !connected && !remote && attempt > 1:
            lost = true
        default:
            break
        }
        self.update = remote ? nil : update
        return settle(at: now)
    }

    /// The update under way as `update.json` says now: read at launch before the first try,
    /// so an update under way shows at once (B130, fix 30a), and again while the daemon is
    /// down.
    public mutating func note(update: UpdateUnderWay?, at now: Date = Date()) -> Bool {
        self.update = update
        return settle(at: now)
    }

    /// The app's own start of the service is over; a second failed try after it shows the
    /// line.
    public mutating func startFinished() {
        start = .done
        lost = false
    }

    private mutating func settle(at now: Date) -> Bool {
        guard !connected else { return false }
        if let update {
            updateEnded = nil
            screen = .updating(update)
            return false
        }
        // The same screen until the daemon answers, not the window and its banner for the
        // moment between the watcher's end and the daemon's start (B130, fix 30b).
        if case .updating = screen {
            let ended = updateEnded ?? now
            updateEnded = ended
            if now.timeIntervalSince(ended) < Self.afterUpdate {
                return false
            }
            updateEnded = nil
            screen = .none
        }
        if screen == .down {
            return false
        }
        guard lost else {
            screen = .none
            return false
        }
        switch start {
        case .notYet:
            start = .running
            screen = .none
            return true
        case .running:
            screen = .none
            return false
        case .done:
            screen = .down
            return false
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
