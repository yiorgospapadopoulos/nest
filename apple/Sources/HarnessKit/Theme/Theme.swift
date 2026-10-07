import Foundation

public enum Appearance: Sendable, Hashable {
    case light, dark
}

extension ThemedColor {
    public func resolved(_ appearance: Appearance) -> RGBA {
        appearance == .light ? light : dark
    }
}

/// A wallpaper glow with its color resolved.
public struct ResolvedWallpaperStop: Sendable, Equatable {
    public let color: RGBA
    public let centerX: Double
    public let centerY: Double
    public let radiusX: Double
    public let radiusY: Double
    public let fade: Double
}

/// The colors the settings pick, for one appearance.
public struct ResolvedTheme: Sendable, Equatable {
    public let appearance: Appearance
    public let accent: RGBA
    /// Text and icons on the accent.
    public let onAccent: RGBA
    public let bubble: RGBA
    public let bubbleText: RGBA
    /// Nil for the see-through desktop.
    public let wallpaperBase: RGBA?
    public let wallpaperStops: [ResolvedWallpaperStop]
}

/// The fixed status colors: running blue, needs you amber, review green, failed red,
/// interrupted grey-brown, done grey.
public enum StatusTone: Sendable, Hashable, CaseIterable {
    case running, waiting, review, failed, interrupted, done

    public var fill: ThemedColor {
        switch self {
        case .running: DesignTokens.Status.Running.fill
        case .waiting: DesignTokens.Status.Waiting.fill
        case .review: DesignTokens.Status.Review.fill
        case .failed: DesignTokens.Status.Failed.fill
        case .interrupted: DesignTokens.Status.Interrupted.fill
        case .done: DesignTokens.Status.Done.fill
        }
    }

    public var text: ThemedColor {
        switch self {
        case .running: DesignTokens.Status.Running.text
        case .waiting: DesignTokens.Status.Waiting.text
        case .review: DesignTokens.Status.Review.text
        case .failed: DesignTokens.Status.Failed.text
        case .interrupted: DesignTokens.Status.Interrupted.text
        case .done: DesignTokens.Status.Done.text
        }
    }

    /// The tone of a session's dot; `hasReview` is true while work waits for review.
    public static func of(_ state: SessionState, hasReview: Bool) -> StatusTone {
        switch state {
        case .starting, .running: .running
        case .waiting: .waiting
        case .failed: .failed
        case .interrupted: .interrupted
        default: hasReview ? .review : .done
        }
    }
}

public enum Theme {
    public static func appearance(for mode: ThemeMode, system: Appearance) -> Appearance {
        switch mode {
        case .auto: system
        case .light: .light
        case .dark: .dark
        }
    }

    public static func accent(_ name: AccentName) -> AccentColor {
        switch name {
        case .graphite: DesignTokens.Accent.graphite
        case .ocean: DesignTokens.Accent.ocean
        case .teal: DesignTokens.Accent.teal
        case .moss: DesignTokens.Accent.moss
        case .clay: DesignTokens.Accent.clay
        case .rose: DesignTokens.Accent.rose
        }
    }

    /// The painted wallpaper's style; nil for the see-through desktop.
    public static func wallpaper(_ name: WallpaperName) -> WallpaperStyle? {
        switch name {
        case .desktop: nil
        case .stone: DesignTokens.Wallpaper.stone
        case .sage: DesignTokens.Wallpaper.sage
        case .sky: DesignTokens.Wallpaper.sky
        case .slate: DesignTokens.Wallpaper.slate
        }
    }

    public static func resolve(
        accent name: AccentName, bubble: BubbleStyle, wallpaper wallpaperName: WallpaperName,
        appearance: Appearance
    ) -> ResolvedTheme {
        let accent = accent(name)
        let wallpaper = wallpaper(wallpaperName)
        let neutral = bubble == .neutral
        return ResolvedTheme(
            appearance: appearance,
            accent: accent.fill.resolved(appearance),
            onAccent: accent.on.resolved(appearance),
            bubble: (neutral ? DesignTokens.Colors.Surface.neutralBubble : accent.fill)
                .resolved(appearance),
            bubbleText: (neutral ? DesignTokens.Colors.Text.primary : accent.on).resolved(
                appearance),
            wallpaperBase: wallpaper?.base.resolved(appearance),
            wallpaperStops: (wallpaper?.stops ?? []).map { stop in
                ResolvedWallpaperStop(
                    color: stop.color.resolved(appearance), centerX: stop.centerX,
                    centerY: stop.centerY, radiusX: stop.radiusX, radiusY: stop.radiusY,
                    fade: stop.fade)
            })
    }

    /// The theme for the current settings and system appearance.
    @MainActor
    public static func resolve(_ settings: SettingsStore, system: Appearance) -> ResolvedTheme {
        resolve(
            accent: settings.accent, bubble: settings.bubble, wallpaper: settings.wallpaper,
            appearance: appearance(for: settings.theme, system: system))
    }
}
