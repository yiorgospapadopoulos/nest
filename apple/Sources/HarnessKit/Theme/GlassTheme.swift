import Foundation

extension Theme {
    /// The glass theme with this id; an unknown id (such as a removed theme) falls back to
    /// the default, Clear.
    public static func glass(named id: String) -> GlassStyle {
        DesignTokens.GlassTheme.all.first { $0.name == id } ?? DesignTokens.GlassTheme.default
    }
}

/// How the window's background is drawn.
public enum WindowBackdrop: Sendable, Hashable {
    /// Non-opaque, with the system's behind-window blur: the desktop shows through.
    case desktop
    /// Fullscreen, where nothing is behind the window: the desktop wallpaper is drawn in
    /// the window instead, so the glass still has something to show.
    case wallpaper
    /// Reduce Transparency: an opaque page color.
    case opaque

    public static func of(reduceTransparency: Bool, fullScreen: Bool = false) -> Self {
        reduceTransparency ? .opaque : fullScreen ? .wallpaper : .desktop
    }

    /// Reading surfaces (the transcript and composer) take a denser tint over the desktop.
    public var isSeeThrough: Bool { self != .opaque }
}

/// How a glass theme's backdrop blur reaches a Mac window. macOS does not let an app set
/// the behind-window blur radius. A light blur (Clear) gets no window-wide blur at all, so
/// the desktop shows crisply between panels as in the preview; the panels' own Liquid
/// Glass does the blurring. Heavier blurs pick one of the system materials
/// (denser with the blur), with a frost wash of the theme's surface color over it that
/// grows with the blur, the most for Frosted.
public struct WindowGlass: Sendable, Equatable {
    public enum Material: Sendable, Equatable {
        /// No window-wide blur: only the panels' own glass.
        case none
        case medium, heavy
    }

    public let material: Material
    let blur: Double
    /// Drawn over the system blur, under the window shell.
    public let frost: ThemedColor

    /// The themes' blur range: Clear's 10 points to Frosted's 48.
    static let blurRange = 10.0...48.0
    /// The frost wash's opacity at the top of the range.
    static let maxFrost = 0.4

    public static func of(_ style: GlassStyle) -> WindowGlass {
        let blur = style.backdrop.blur
        return WindowGlass(
            material: material(blur: blur), blur: blur,
            frost: style.colors.surface.withAlpha(frost(blur: blur)))
    }

    /// Under 20 points of blur, no window blur; from 40 the densest material.
    static func material(blur: Double) -> Material {
        blur < 20 ? .none : blur < 40 ? .medium : .heavy
    }

    /// The blur for the wallpaper drawn in a fullscreen window: the theme's own, or none
    /// when the theme has no window blur.
    public var wallpaperBlur: Double { material == .none ? 0 : blur }

    static func frost(blur: Double) -> Double {
        let range = blurRange
        let position = (blur - range.lowerBound) / (range.upperBound - range.lowerBound)
        return min(max(position, 0), 1) * maxFrost
    }
}

extension GlassStyle {
    /// Reading surfaces (transcript panes, the composer): a third of the way from the
    /// panel tint toward the strong surface, so text stays readable over a busy desktop.
    /// Clear keeps its plain tint, as in the preview.
    public var readingTint: ThemedColor {
        WindowGlass.of(self).material == .none
            ? colors.tint : colors.tint.mixed(toward: colors.surface, by: 1.0 / 3)
    }
}

extension ThemedColor {
    public func withAlpha(_ alpha: Double) -> ThemedColor {
        ThemedColor(light: light.withAlpha(alpha), dark: dark.withAlpha(alpha))
    }

    func mixed(toward other: ThemedColor, by amount: Double) -> ThemedColor {
        ThemedColor(
            light: light.mixed(toward: other.light, by: amount),
            dark: dark.mixed(toward: other.dark, by: amount))
    }
}

extension RGBA {
    public func withAlpha(_ alpha: Double) -> RGBA {
        RGBA(red: red, green: green, blue: blue, alpha: alpha)
    }

    func mixed(toward other: RGBA, by amount: Double) -> RGBA {
        func mix(_ from: Double, _ to: Double) -> Double { from + (to - from) * amount }
        return RGBA(
            red: mix(red, other.red), green: mix(green, other.green), blue: mix(blue, other.blue),
            alpha: mix(alpha, other.alpha))
    }
}
