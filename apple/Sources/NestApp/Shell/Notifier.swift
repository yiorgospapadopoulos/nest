import AppKit
import NestKit
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
        guard Self.canNotify else { return }
        UNUserNotificationCenter.current().delegate = self
        Task { await Self.ask() }
        shell.model.live.onNotice = { [weak self] notice in self?.post(notice) }
        shell.model.live.onUsageWarning = { [weak self] warning in self?.post(warning) }
    }

    /// The notification center stops a process that is not a bundle.
    static var canNotify: Bool { Bundle.main.bundleURL.pathExtension == "app" }

    /// The async form: a completion closure written here would be main actor isolated but
    /// called on a background queue, which traps.
    static func ask() async {
        let center = UNUserNotificationCenter.current()
        _ = try? await center.requestAuthorization(options: [.alert, .sound, .badge])
    }

    /// The system's current answer, asking nothing.
    static func answer() async -> SystemPermission {
        guard canNotify else { return .notAsked }
        switch await UNUserNotificationCenter.current().notificationSettings().authorizationStatus {
        case .authorized, .provisional: return .allowed
        case .denied: return .refused
        default: return .notAsked
        }
    }

    /// A usage warning becomes a notification too when its setting is on (B81).
    private func post(_ warning: UsageWarning) {
        let usage = shell.model.usage
        let text = usage.warningText(warning)
        Task {
            let notify = await usage.warningNotifies()
            if let content = NotificationPolicy.content(
                forWarning: text, notify: notify, preferences: shell.settings.notifications)
            {
                deliver(content)
            }
        }
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
        let preferences = shell.settings.notifications
        let visible = visibleChats
        if let spoken = NotificationPolicy.announcement(
            for: notice, preferences: preferences, visibleChats: visible)
        {
            VoiceOver.announce(spoken, urgent: true)
        }
        guard
            let content = NotificationPolicy.content(
                for: notice, preferences: preferences, visibleChats: visible,
                pixies: shell.model.pixies.pixies)
        else { return }
        deliver(content)
    }

    private func deliver(_ content: NotificationContent) {
        let message = UNMutableNotificationContent()
        message.title = content.title
        message.body = content.body
        // A usage warning opens no chat.
        if !content.sessionID.isEmpty {
            message.userInfo = ["session": content.sessionID, "project": content.project]
            message.threadIdentifier = content.sessionID
        }
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
