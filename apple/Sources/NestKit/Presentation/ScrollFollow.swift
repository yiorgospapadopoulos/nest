import Foundation

/// Where a vertical scroll view is: its offset, the visible height and the content height.
public struct ScrollMetrics: Sendable, Equatable {
    /// How close to the end still counts as the bottom.
    public static let threshold = 40.0

    public var offset: Double
    public var viewport: Double
    public var content: Double

    public init(offset: Double, viewport: Double, content: Double) {
        self.offset = offset
        self.viewport = viewport
        self.content = content
    }

    public var isAtBottom: Bool { offset + viewport >= content - Self.threshold }

    /// Exactly at the end, where shrinking content or a taller window pins the offset.
    var isAtEnd: Bool { offset + viewport >= content - 1 }
}

/// Whether the transcript follows new content. Only the user's own scrolling starts or
/// stops following: any move up stops it and only a return to the bottom resumes it.
/// Content that grows or a resized window never does, so a reader who scrolled up is
/// never moved, and one at the bottom stays there while text streams in. The one
/// exception is a pane losing the focus to another pane (B93): it jumps to the latest.
public struct ScrollFollow: Sendable, Equatable {
    public private(set) var following = true
    private var unseen = false
    /// Scrolling to the latest after Jump to latest, until the bottom is reached.
    private var jumping = false
    private var last: ScrollMetrics?
    /// Whether the pane has the focus, as last told by `focusChanged`.
    private var focused = true

    public init() {}

    /// Jump to latest is offered when new content arrived out of view.
    /// Never in a pane without the focus, which goes back to the latest by itself.
    public var showsJump: Bool { !following && unseen && focused }

    /// Reads a geometry change; returns true when the view should scroll to the bottom.
    public mutating func update(_ metrics: ScrollMetrics) -> Bool {
        defer { last = metrics }
        if metrics.isAtBottom {
            jumping = false
        }
        guard let last, last.viewport == metrics.viewport, !jumping else {
            return following && !metrics.isAtBottom
        }
        // Any move up the user makes stops following, however small, even while text
        // streams in; only a move pinned to the end is not theirs.
        if metrics.offset < last.offset && !metrics.isAtEnd {
            following = false
            return false
        }
        if metrics.offset > last.offset && metrics.isAtBottom {
            following = true
            unseen = false
            return false
        }
        return following && !metrics.isAtBottom
    }

    /// A message, tool call or streamed text arrived; returns true when the view should
    /// scroll to the bottom.
    public mutating func contentArrived() -> Bool {
        // A pane without the focus, even one scrolled up by hand, goes back to the latest.
        if !focused && !following {
            jumpToLatest()
        }
        if !following {
            unseen = true
        }
        return following
    }

    /// The view scrolled to an earlier item on purpose, such as a search hit: stays there
    /// until the user scrolls back to the bottom.
    public mutating func hold() {
        following = false
        unseen = false
        jumping = false
    }

    public mutating func jumpToLatest() {
        following = true
        unseen = false
        // Already at the bottom, no scroll follows to end the jump, and a stuck jump would
        // pull every later scroll up back down.
        jumping = last?.isAtBottom != true
    }

    /// The pane's focus, read whenever it changes. Losing the focus to another pane jumps
    /// to the latest and follows again; returns true when the view should scroll to the
    /// bottom. Gaining or keeping the focus moves nothing.
    public mutating func focusChanged(focused: Bool) -> Bool {
        defer { self.focused = focused }
        guard self.focused && !focused else { return false }
        jumpToLatest()
        return true
    }
}
