import AppKit
import HarnessKit

/// Watches whether harness is on screen and hands each change to the reporter, which tells
/// the daemon and keeps the heartbeat going (D031).
@MainActor
final class VisibilityMonitor {
    private let reporter: VisibilityReporter
    private var observers: [(NotificationCenter, any NSObjectProtocol)] = []
    private var heartbeat: Task<Void, Never>?
    private var screenAsleep = false
    private var sessionInactive = false

    init(reporter: VisibilityReporter) {
        self.reporter = reporter
    }

    func start() {
        guard observers.isEmpty else { return }
        let app = NotificationCenter.default
        for name in [
            NSApplication.didBecomeActiveNotification, NSApplication.didResignActiveNotification,
            NSApplication.didHideNotification, NSApplication.didUnhideNotification,
            NSApplication.didChangeOcclusionStateNotification,
            NSWindow.didChangeOcclusionStateNotification, NSWindow.didMiniaturizeNotification,
            NSWindow.didDeminiaturizeNotification, NSWindow.willCloseNotification,
        ] {
            observe(app, name) { _ in }
        }
        let workspace = NSWorkspace.shared.notificationCenter
        observe(workspace, NSWorkspace.screensDidSleepNotification) { $0.screenAsleep = true }
        observe(workspace, NSWorkspace.screensDidWakeNotification) { $0.screenAsleep = false }
        observe(workspace, NSWorkspace.sessionDidResignActiveNotification) {
            $0.sessionInactive = true
        }
        observe(workspace, NSWorkspace.sessionDidBecomeActiveNotification) {
            $0.sessionInactive = false
        }
        evaluate()
        heartbeat = Task { [reporter] in await reporter.run() }
    }

    private func observe(
        _ center: NotificationCenter, _ name: Notification.Name,
        change: @escaping @MainActor (VisibilityMonitor) -> Void
    ) {
        let token = center.addObserver(forName: name, object: nil, queue: .main) {
            [weak self] _ in
            MainActor.assumeIsolated {
                guard let self else { return }
                change(self)
                // A window that is closing still counts as shown until it is gone.
                Task { self.evaluate() }
            }
        }
        observers.append((center, token))
    }

    private func evaluate() {
        let windows = NSApp.windows.filter(\.canBecomeMain).map { window in
            WindowPresence(
                isShown: window.isVisible, isOnScreen: window.occlusionState.contains(.visible),
                isMiniaturized: window.isMiniaturized)
        }
        reporter.update(
            visible: WindowPresence.isVisible(
                appHidden: NSApp.isHidden, screenAway: screenAsleep || sessionInactive,
                windows: windows))
    }
}
