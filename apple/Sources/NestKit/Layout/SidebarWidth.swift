import Foundation

/// The left sidebar's width, which the user drags (B45): one width for the chats sidebar
/// and the Pixies list, in every project, kept on this Mac.
public enum SidebarWidth {
    public static let standard = 236.0
    /// Chat titles stay readable.
    public static let minimum = 200.0
    public static let maximum = 420.0
    /// The workspace keeps room for one pane at its narrowest.
    public static let minimumWorkspace = WorkspaceLayout.minimumPaneWidth
    /// One accessibility increment or decrement.
    public static let step = 10.0

    /// `proposed` within the bounds, leaving the workspace its minimum of `available`,
    /// the width the sidebar and the workspace share. Before the window is measured
    /// (`available` zero) only the fixed bounds apply. The minimum wins in a window too
    /// narrow for both.
    public static func clamp(_ proposed: Double, available: Double) -> Double {
        let upper = available > 0 ? min(maximum, available - minimumWorkspace) : maximum
        return max(minimum, min(proposed, upper))
    }

    /// A saved width, within the fixed bounds; the standard one when missing or unreadable.
    public static func stored(_ text: String?) -> Double {
        guard let width = text.flatMap(Double.init), width.isFinite else { return standard }
        return clamp(width, available: 0)
    }

    /// `width` one step wider (`by` 1) or narrower (-1).
    public static func stepped(_ width: Double, by direction: Int) -> Double {
        clamp(width + step * Double(direction), available: 0)
    }
}
