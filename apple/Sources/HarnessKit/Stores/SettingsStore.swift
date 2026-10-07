import Foundation
import Observation

public enum ThemeMode: String, Sendable, CaseIterable {
    case auto, light, dark
}

public enum AccentName: String, Sendable, CaseIterable {
    case graphite, ocean, teal, moss, clay, rose
}

/// Whether the user's chat bubbles use the accent or a neutral glass.
public enum BubbleStyle: String, Sendable, CaseIterable {
    case accent, neutral
}

/// What shows behind the window's glass: the desktop itself, or a painted wallpaper.
public enum WallpaperName: String, Sendable, CaseIterable {
    /// See-through: the desktop and windows behind, blurred by the system.
    case desktop
    case stone, sage, sky, slate

    /// The Settings label.
    public var label: String {
        self == .desktop ? "Desktop" : rawValue.capitalized
    }
}

/// How the window's background is drawn.
public enum WindowBackdrop: Sendable, Hashable {
    /// Non-opaque, with the system's behind-window blur.
    case desktop
    /// A wallpaper painted behind the glass.
    case painted(WallpaperName)
    /// Reduce Transparency with the see-through choice: an opaque page color.
    case opaque

    /// Reduce Transparency turns the see-through window opaque; painted wallpapers are
    /// opaque already.
    public static func of(_ wallpaper: WallpaperName, reduceTransparency: Bool) -> Self {
        guard wallpaper == .desktop else { return .painted(wallpaper) }
        return reduceTransparency ? .opaque : .desktop
    }

    /// Reading surfaces (the transcript and composer) take a denser tint over the desktop.
    public var isSeeThrough: Bool { self == .desktop }
}

/// The app's appearance, Claude Code chat listing and notifications, kept between
/// launches. The defaults for new chats live on the daemon (`AgentsStore`).
@MainActor @Observable
public final class SettingsStore {
    enum Key {
        static let theme = "appearance.theme"
        static let accent = "appearance.accent"
        static let bubble = "appearance.bubble"
        static let wallpaper = "appearance.wallpaper"
        static let notifications = "notifications."
        static let automatedChats = "claudeChats.showAutomated"
    }

    public var theme: ThemeMode {
        didSet { save(theme.rawValue, Key.theme) }
    }
    public var accent: AccentName {
        didSet { save(accent.rawValue, Key.accent) }
    }
    public var bubble: BubbleStyle {
        didSet { save(bubble.rawValue, Key.bubble) }
    }
    public var wallpaper: WallpaperName {
        didSet { save(wallpaper.rawValue, Key.wallpaper) }
    }
    /// List Claude Code chats that scripts and tools started, not only the user's own.
    public var showAutomatedChats: Bool {
        didSet { save(showAutomatedChats ? "on" : "off", Key.automatedChats) }
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

    /// Values that are missing or no longer valid fall back to the defaults.
    public init(store: any KeyValueStore = UserDefaultsStore()) {
        self.store = store
        theme = store.string(forKey: Key.theme).flatMap(ThemeMode.init) ?? .auto
        accent = store.string(forKey: Key.accent).flatMap(AccentName.init) ?? .graphite
        bubble = store.string(forKey: Key.bubble).flatMap(BubbleStyle.init) ?? .accent
        wallpaper = store.string(forKey: Key.wallpaper).flatMap(WallpaperName.init) ?? .desktop
        showAutomatedChats = store.string(forKey: Key.automatedChats) == "on"
        var notifications = NotificationPreferences()
        for (name, path) in NotificationPreferences.fields {
            if let stored = store.string(forKey: Key.notifications + name) {
                notifications[keyPath: path] = stored == "on"
            }
        }
        self.notifications = notifications
    }

    private func save(_ value: String?, _ key: String) {
        store.set(value, forKey: key)
    }
}
