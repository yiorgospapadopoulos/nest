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
}

/// Whether the transcript follows new content. Only the user's own scrolling starts or
/// stops following: content that grows or a resized window never does, so a reader who
/// scrolled up is never moved, and one at the bottom stays there while text streams in.
public struct ScrollFollow: Sendable, Equatable {
    public private(set) var following = true
    private var unseen = false
    /// Scrolling to the latest after Jump to latest, until the bottom is reached.
    private var jumping = false
    private var last: ScrollMetrics?

    public init() {}

    /// Jump to latest is offered when new content arrived out of view.
    public var showsJump: Bool { !following && unseen }

    /// Reads a geometry change; returns true when the view should scroll to the bottom.
    public mutating func update(_ metrics: ScrollMetrics) -> Bool {
        defer { last = metrics }
        if metrics.isAtBottom {
            jumping = false
        }
        let scrolled =
            last.map {
                $0.content == metrics.content && $0.viewport == metrics.viewport
                    && $0.offset != metrics.offset
            } ?? false
        if scrolled && !jumping {
            following = metrics.isAtBottom
            if following {
                unseen = false
            }
            return false
        }
        return following && !metrics.isAtBottom
    }

    /// A message, tool call or streamed text arrived; returns true when the view should
    /// scroll to the bottom.
    public mutating func contentArrived() -> Bool {
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
        jumping = true
    }
}
