import Foundation
import Observation

public enum ThemeMode: String, Sendable, CaseIterable {
    case auto, light, dark
}

public enum AccentName: String, Sendable, CaseIterable {
    case graphite, ocean, teal, moss, clay, rose
}

/// The app's appearance, Claude Code chat listing and notifications, kept between
/// launches. The defaults for new chats live on the daemon (`AgentsStore`).
@MainActor @Observable
public final class SettingsStore {
    enum Key {
        static let theme = "appearance.theme"
        static let accent = "appearance.accent"
        static let notifications = "notifications."
        static let automatedChats = "claudeChats.showAutomated"
        static let backgroundImage = "appearance.background.image"
        static let backgroundEmpty = "appearance.background.empty"
        static let backgroundChats = "appearance.background.chats"
        static let backgroundGrain = "appearance.background.grain"
        static let backgroundProjects = "appearance.background.projects"
        static let sidebarWidth = "sidebar.width"
        static let usageMeterHidden = "usage.meter.hidden"
    }

    public var theme: ThemeMode {
        didSet { save(theme.rawValue, Key.theme) }
    }
    /// Colors primary buttons, selection and focus.
    public var accent: AccentName {
        didSet { save(accent.rawValue, Key.accent) }
    }
    /// List Claude Code chats that scripts and tools started, not only the user's own.
    public var showAutomatedChats: Bool {
        didSet { save(showAutomatedChats ? "on" : "off", Key.automatedChats) }
    }

    /// The image behind the workspace (B39), on this Mac only.
    public var chatBackground: ChatBackgroundSettings {
        didSet { saveChatBackground() }
    }

    /// The left sidebar's width, the same in every project (B45).
    public var sidebarWidth: Double {
        didSet { save(String(sidebarWidth), Key.sidebarWidth) }
    }

    /// The engines unchecked for the usage meter at the top right (B94), on this Mac only.
    /// Kept as the engines left out, so an engine added later starts shown.
    public private(set) var usageMeterHidden: Set<String> {
        didSet {
            save(
                usageMeterHidden.isEmpty ? nil : usageMeterHidden.sorted().joined(separator: ","),
                Key.usageMeterHidden)
        }
    }

    public func showsInUsageMeter(_ engine: String) -> Bool {
        !usageMeterHidden.contains(engine)
    }

    public func setUsageMeter(_ engine: String, shown: Bool) {
        if shown {
            usageMeterHidden.remove(engine)
        } else {
            usageMeterHidden.insert(engine)
        }
    }

    /// Which notices reach macOS notifications.
    public var notifications: NotificationPreferences {
        didSet {
            for (name, path) in NotificationPreferences.fields {
                save(notifications[keyPath: path] ? "on" : "off", Key.notifications + name)
            }
        }
    }

    @ObservationIgnored let store: any KeyValueStore

    /// Values that are missing or no longer valid fall back to the defaults. Choices of
    /// removed settings (the wallpaper, glass theme and bubble color) stay in the store,
    /// unread.
    public init(store: any KeyValueStore = UserDefaultsStore()) {
        self.store = store
        theme = store.string(forKey: Key.theme).flatMap(ThemeMode.init) ?? .auto
        accent = store.string(forKey: Key.accent).flatMap(AccentName.init) ?? .graphite
        showAutomatedChats = store.string(forKey: Key.automatedChats) == "on"
        chatBackground = Self.loadChatBackground(from: store)
        sidebarWidth = SidebarWidth.stored(store.string(forKey: Key.sidebarWidth))
        usageMeterHidden = Set(
            (store.string(forKey: Key.usageMeterHidden) ?? "")
                .split(separator: ",").map(String.init))
        var notifications = NotificationPreferences()
        for (name, path) in NotificationPreferences.fields {
            if let stored = store.string(forKey: Key.notifications + name) {
                notifications[keyPath: path] = stored == "on"
            }
        }
        // Questions shared the approvals toggle before they had their own.
        if store.string(forKey: Key.notifications + "questions") == nil {
            notifications.questions = notifications.approvals
        }
        self.notifications = notifications
    }

    private func save(_ value: String?, _ key: String) {
        store.set(value, forKey: key)
    }

    /// A project's own background as saved; a missing visibility is the global one.
    private struct StoredBackground: Codable {
        var image: String?
        var empty: Double?
        var chats: Double?
        var grain: Double?
    }

    private static func loadChatBackground(from store: any KeyValueStore)
        -> ChatBackgroundSettings
    {
        var settings = ChatBackgroundSettings()
        let image = store.string(forKey: Key.backgroundImage)?
            .trimmingCharacters(in: .whitespaces)
        settings.image = image?.isEmpty == false ? image : nil
        for (key, path) in [
            (Key.backgroundEmpty, \ChatBackgroundSettings.emptyVisibility),
            (Key.backgroundChats, \.chatsVisibility),
        ] {
            if let value = store.string(forKey: key).flatMap(Double.init) {
                settings[keyPath: path] = ChatBackground.clamp(value)
            }
        }
        if let grain = store.string(forKey: Key.backgroundGrain).flatMap(Double.init) {
            settings.grain = ChatBackground.clampGrain(grain)
        }
        let stored =
            store.string(forKey: Key.backgroundProjects).flatMap {
                try? JSONDecoder().decode([String: StoredBackground].self, from: Data($0.utf8))
            } ?? [:]
        for (project, background) in stored {
            guard let image = background.image, !image.isEmpty else { continue }
            settings.projects[project] = ChatBackground(
                image: image, emptyVisibility: background.empty ?? settings.emptyVisibility,
                chatsVisibility: background.chats ?? settings.chatsVisibility,
                grain: background.grain ?? settings.grain)
        }
        return settings
    }

    private func saveChatBackground() {
        let settings = chatBackground
        save(settings.image, Key.backgroundImage)
        save(String(settings.emptyVisibility), Key.backgroundEmpty)
        save(String(settings.chatsVisibility), Key.backgroundChats)
        save(String(settings.grain), Key.backgroundGrain)
        let projects = settings.projects.mapValues {
            StoredBackground(
                image: $0.image, empty: $0.emptyVisibility, chats: $0.chatsVisibility,
                grain: $0.grain)
        }
        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys
        // Encoding plain strings and numbers cannot fail.
        let json = try? encoder.encode(projects)
        save(json.map { String(decoding: $0, as: UTF8.self) }, Key.backgroundProjects)
    }
}
