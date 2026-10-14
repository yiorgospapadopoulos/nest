import Foundation

/// The Notifications settings, one toggle per kind of notice.
public struct NotificationPreferences: Sendable, Hashable {
    /// Permission prompts.
    public var approvals = true
    public var questions = true
    public var reviews = true
    public var errors = true
    public var finished = true
    /// Pull requests whose checks failed.
    public var ciFailed = true
    /// Pull requests that are green and mergeable.
    public var readyToMerge = true
    /// Chats that look stuck (D036).
    public var stuck = true
    public var sound = false

    public init() {}

    /// Stored names of the toggles.
    static var fields: [(String, WritableKeyPath<NotificationPreferences, Bool>)] {
        [
            ("approvals", \.approvals), ("questions", \.questions), ("reviews", \.reviews),
            ("errors", \.errors), ("finished", \.finished), ("ci_failed", \.ciFailed),
            ("ready_to_merge", \.readyToMerge), ("stuck", \.stuck), ("sound", \.sound),
        ]
    }

    /// The Settings toggles in order, named as on the iPhone.
    public static var toggles:
        [(title: String, path: WritableKeyPath<NotificationPreferences, Bool>)]
    {
        [
            ("Approvals", \.approvals), ("Questions", \.questions),
            ("Work ready for review", \.reviews), ("Agent errors", \.errors),
            ("Finished turns", \.finished), ("Pull request checks failed", \.ciFailed),
            ("Pull requests ready to merge", \.readyToMerge), ("Chats that look stuck", \.stuck),
            ("Sound", \.sound),
        ]
    }

    /// Whether this kind of notice is switched on.
    public func wants(_ kind: NoticeKind) -> Bool {
        switch kind {
        case .needsApproval: approvals
        case .question: questions
        case .reviewReady: reviews
        case .failed: errors
        case .finished: finished
        case .ciFailed: ciFailed
        case .readyToMerge: readyToMerge
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
        for notice: Notice, preferences: NotificationPreferences, visibleChats: Set<String>,
        pixies: [Pixie] = []
    ) -> NotificationContent? {
        guard preferences.wants(notice.kind), !visibleChats.contains(notice.sessionID) else {
            return nil
        }
        return NotificationContent(
            title: "\(source(of: notice, pixies: pixies)) · \(notice.title)", body: notice.text,
            sessionID: notice.sessionID, project: notice.repo, playsSound: preferences.sound)
    }

    /// The project a notice comes from, or the pixie's name for a pixie chat (D072).
    static func source(of notice: Notice, pixies: [Pixie]) -> String {
        guard notice.repo.hasPrefix("pixie:") else { return notice.repo }
        let id = String(notice.repo.dropFirst("pixie:".count))
        return pixies.first { $0.id == id }?.name ?? "Pixie"
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

    /// The Dock badge: everything that needs the user (`SessionsStore.attention()`), or
    /// none.
    public static func badge(pending: Int) -> String? {
        pending > 0 ? "\(pending)" : nil
    }
}
