import AppKit
import HarnessKit
import UserNotifications

/// Turns the daemon's notices into macOS notifications, and a click on one into the chat
/// it is about. Only the bundled app can use the notification center.
@MainActor
final class Notifier: NSObject, UNUserNotificationCenterDelegate {
    private let shell: Shell

    init(shell: Shell) {
        self.shell = shell
    }

    /// Asks for permission once and starts listening for notices.
    func start() {
        guard Bundle.main.bundleURL.pathExtension == "app" else { return }
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        // The async form: a completion closure written here would be main actor isolated
        // but called on a background queue, which traps.
        Task { _ = try? await center.requestAuthorization(options: [.alert, .sound, .badge]) }
        shell.model.live.onNotice = { [weak self] notice in self?.post(notice) }
    }

    /// The chats on screen; on the Pixies tab, those of the pixie panes on screen.
    private var visibleChats: Set<String> {
        let focused = NSApp.isActive && NSApp.keyWindow != nil
        return shell.pixiesOpen
            ? NotificationPolicy.visiblePixieChats(
                app: shell.app, pixies: shell.pixies.pixies, windowFocused: focused)
            : NotificationPolicy.visibleChats(app: shell.app, windowFocused: focused)
    }

    private func post(_ notice: Notice) {
        guard
            let content = NotificationPolicy.content(
                for: notice, preferences: shell.settings.notifications,
                visibleChats: visibleChats, pixies: shell.model.pixies.pixies)
        else { return }
        deliver(content)
    }

    private func deliver(_ content: NotificationContent) {
        let message = UNMutableNotificationContent()
        message.title = content.title
        message.body = content.body
        message.userInfo = ["session": content.sessionID, "project": content.project]
        message.threadIdentifier = content.sessionID
        if content.playsSound {
            message.sound = .default
        }
        let request = UNNotificationRequest(
            identifier: UUID().uuidString, content: message, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter, willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        [.banner, .list, .sound]
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse
    ) async {
        let info = response.notification.request.content.userInfo
        guard let session = info["session"] as? String, let project = info["project"] as? String
        else { return }
        await MainActor.run {
            NSApp.activate()
            NSApp.windows.first { $0.isVisible && $0.canBecomeMain }?.makeKeyAndOrderFront(nil)
            shell.reveal(chat: session, in: project)
        }
    }
}
