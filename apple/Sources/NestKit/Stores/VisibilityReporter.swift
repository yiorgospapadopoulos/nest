import Foundation
import Observation

/// What the app knows about one of its windows.
public struct WindowPresence: Sendable, Hashable {
    /// Ordered in, not closed.
    public var isShown: Bool
    /// Some part of it is on screen (not fully covered, minimized or on another Space).
    public var isOnScreen: Bool
    public var isMiniaturized: Bool

    public init(isShown: Bool, isOnScreen: Bool, isMiniaturized: Bool) {
        self.isShown = isShown
        self.isOnScreen = isOnScreen
        self.isMiniaturized = isMiniaturized
    }

    /// Someone can see Nest: the app is not hidden, the screen is awake and unlocked,
    /// and a window is on screen. Being in the background with a visible window counts.
    public static func isVisible(appHidden: Bool, screenAway: Bool, windows: [WindowPresence])
        -> Bool
    {
        !appHidden && !screenAway
            && windows.contains { $0.isShown && $0.isOnScreen && !$0.isMiniaturized }
    }
}

/// Tells the daemon whether the app is on screen, so it refreshes the usage limits only
/// while someone can see them (D031): on each change, and every minute while visible,
/// since a report lapses on the daemon after 150 s. Reports go out in order. Views read
/// `isVisible` too, to pause their animations while nobody sees them (IMP-11).
@MainActor @Observable
public final class VisibilityReporter {
    /// The client name that tells the Mac app apart from a browser on the same device.
    public static let client = "mac"
    /// Seconds between reports while visible.
    public static let heartbeat: TimeInterval = 60
    /// How often `run` checks whether a heartbeat is due.
    public static let tickInterval: Duration = .seconds(10)

    public private(set) var isVisible = false
    /// When the last report went out; nil before the first.
    @ObservationIgnored public private(set) var lastReport: Date?

    let send: @Sendable (Bool) async throws -> Void
    let now: @Sendable () -> Date
    @ObservationIgnored private var sending: Task<Void, Never>?

    public init(
        send: @escaping @Sendable (Bool) async throws -> Void,
        now: @escaping @Sendable () -> Date = { Date() }
    ) {
        self.send = send
        self.now = now
    }

    public convenience init(api: any NestAPI, now: @escaping @Sendable () -> Date) {
        self.init(send: { try await api.reportVisibility($0, client: Self.client) }, now: now)
    }

    /// Reports a change, and the first state whatever it is.
    public func update(visible: Bool) {
        guard visible != isVisible || lastReport == nil else { return }
        isVisible = visible
        report()
    }

    /// Sends the heartbeat when a minute has passed since the last report while visible.
    public func tick() {
        guard isVisible, let lastReport, now().timeIntervalSince(lastReport) >= Self.heartbeat
        else { return }
        report()
    }

    /// Reports again at once while visible, as after a reconnect: the daemon keeps reports
    /// only in memory.
    public func resend() {
        guard isVisible else { return }
        report()
    }

    /// Checks for a due heartbeat after each sleep, until the sleep throws (cancellation).
    public func run(
        sleep: @Sendable (Duration) async throws -> Void = { try await Task.sleep(for: $0) }
    ) async {
        while (try? await sleep(Self.tickInterval)) != nil {
            tick()
        }
    }

    /// Waits until every report so far has been sent or has failed.
    public func flush() async {
        await sending?.value
    }

    private func report() {
        lastReport = now()
        let visible = isVisible
        let previous = sending
        let send = self.send
        sending = Task {
            await previous?.value
            // A lost report only delays a refresh; the next heartbeat sends it again.
            try? await send(visible)
        }
    }
}
