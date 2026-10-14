import Foundation

/// How the window's background is drawn.
public enum WindowBackdrop: Sendable, Hashable {
    /// Non-opaque, with the system's behind-window blur: the desktop shows through.
    case desktop
    /// The tint at full strength: Reduce Transparency, and fullscreen, where nothing is
    /// behind the window and macOS reports a placeholder for every desktop picture.
    case opaque

    public static func of(reduceTransparency: Bool, fullScreen: Bool = false) -> Self {
        reduceTransparency || fullScreen ? .opaque : .desktop
    }

    public var isSeeThrough: Bool { self != .opaque }
}
