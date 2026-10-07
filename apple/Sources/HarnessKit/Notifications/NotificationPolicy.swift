import Foundation

/// The Notifications settings.
public struct NotificationPreferences: Sendable, Hashable {
    /// Permission prompts and questions.
    public var approvals = true
    public var reviews = true
    public var errors = true
    public var finished = true
    /// Chats that look stuck (D036).
    public var stuck = true
    public var sound = false

    public init() {}

    /// Stored names of the toggles.
    static var fields: [(String, WritableKeyPath<NotificationPreferences, Bool>)] {
        [
            ("approvals", \.approvals), ("reviews", \.reviews), ("errors", \.errors),
            ("finished", \.finished), ("stuck", \.stuck), ("sound", \.sound),
        ]
    }

    /// Whether this kind of notice is switched on.
    public func wants(_ kind: NoticeKind) -> Bool {
        switch kind {
        case .needsApproval, .question: approvals
        case .reviewReady: reviews
        case .failed: errors
        case .finished: finished
        case .stuck: stuck
        case .unknown: false
        }
    }
}

/// A macOS notification for a notice.
public struct NotificationContent: Sendable, Hashable {
    public let title: String
    public let body: String
    public let sessionID: String
    public let project: String
    public let playsSound: Bool
}

/// Decides which notices become macOS notifications, and what they say.
public enum NotificationPolicy {
    /// Switched-on notices, unless the user is looking at that chat right now.
    public static func content(
        for notice: Notice, preferences: NotificationPreferences, visibleChats: Set<String>
    ) -> NotificationContent? {
        guard preferences.wants(notice.kind), !visibleChats.contains(notice.sessionID) else {
            return nil
        }
        return NotificationContent(
            title: "\(notice.repo) · \(notice.title)", body: notice.text,
            sessionID: notice.sessionID, project: notice.repo, playsSound: preferences.sound)
    }

    /// The chats on screen: the current project's open panes while its workspace shows in
    /// the focused window.
    @MainActor
    public static func visibleChats(app: AppStore, windowFocused: Bool) -> Set<String> {
        guard windowFocused, let project = app.currentProject else { return [] }
        let state = app.state(of: project)
        guard state.view == .workspace else { return [] }
        if let maximized = state.layout.maximized {
            return [maximized]
        }
        return Set(state.layout.leaves)
    }

    /// The Dock badge: every pending approval, or none.
    public static func badge(pending: Int) -> String? {
        pending > 0 ? "\(pending)" : nil
    }
}
