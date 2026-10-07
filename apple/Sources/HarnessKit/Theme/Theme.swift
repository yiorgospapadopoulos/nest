import Foundation

public enum Appearance: Sendable, Hashable {
    case light, dark
}

extension ThemedColor {
    public func resolved(_ appearance: Appearance) -> RGBA {
        appearance == .light ? light : dark
    }
}

/// The colors the settings pick, for one appearance.
public struct ResolvedTheme: Sendable, Equatable {
    public let appearance: Appearance
    public let accent: RGBA
    /// Text and icons on the accent.
    public let onAccent: RGBA
    public let bubble: RGBA
    public let bubbleText: RGBA
    public let glass: GlassStyle
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

    public static func resolve(
        accent name: AccentName, bubble: BubbleStyle, glass: GlassStyle, appearance: Appearance
    ) -> ResolvedTheme {
        let accent = accent(name)
        let neutral = bubble == .neutral
        return ResolvedTheme(
            appearance: appearance,
            accent: accent.fill.resolved(appearance),
            onAccent: accent.on.resolved(appearance),
            bubble: (neutral ? DesignTokens.Colors.Surface.neutralBubble : accent.fill)
                .resolved(appearance),
            bubbleText: (neutral ? DesignTokens.Colors.Text.primary : accent.on).resolved(
                appearance),
            glass: glass)
    }

    /// The theme for the current settings and system appearance.
    @MainActor
    public static func resolve(_ settings: SettingsStore, system: Appearance) -> ResolvedTheme {
        resolve(
            accent: settings.accent, bubble: settings.bubble, glass: settings.glass,
            appearance: appearance(for: settings.theme, system: system))
    }
}
