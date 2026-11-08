import AppKit

/// Says text through VoiceOver, for changes the user would otherwise only see.
enum VoiceOver {
    /// AppKit's announcement on the app, which VoiceOver speaks whatever has its cursor.
    static func announce(_ text: String, urgent: Bool = false) {
        let priority: NSAccessibilityPriorityLevel = urgent ? .high : .medium
        NSAccessibility.post(
            element: NSApp as Any,
            notification: .announcementRequested,
            userInfo: [.announcement: text, .priority: priority.rawValue])
    }
}
