import CoreGraphics
import Foundation

/// `row` places its two children side by side, `column` stacks them.
public enum SplitDirection: String, Sendable, Hashable {
    case row
    case column
}

/// Where a chat dropped on a pane goes.
public enum DropSide: Sendable, Hashable {
    case left, right, top, bottom
}

/// The workspace's split tree: leaves are chat ids, splits divide their space by `ratio`
/// (the first child's share).
public indirect enum LayoutNode: Sendable, Hashable {
    case leaf(String)
    case split(
        id: Int, direction: SplitDirection, ratio: Double, first: LayoutNode, second: LayoutNode)

    /// Chat ids in reading order.
    public var leaves: [String] {
        switch self {
        case .leaf(let id): [id]
        case .split(_, _, _, let first, let second): first.leaves + second.leaves
        }
    }

    func removing(_ chat: String) -> LayoutNode? {
        switch self {
        case .leaf(let id):
            return id == chat ? nil : self
        case .split(let id, let direction, let ratio, let first, let second):
            guard let newFirst = first.removing(chat) else { return second.removing(chat) }
            guard let newSecond = second.removing(chat) else { return newFirst }
            return .split(
                id: id, direction: direction, ratio: ratio, first: newFirst, second: newSecond)
        }
    }

    /// Replaces every leaf through `transform`.
    func mapLeaves(_ transform: (String) -> String) -> LayoutNode {
        switch self {
        case .leaf(let id):
            return .leaf(transform(id))
        case .split(let id, let direction, let ratio, let first, let second):
            return .split(
                id: id, direction: direction, ratio: ratio, first: first.mapLeaves(transform),
                second: second.mapLeaves(transform))
        }
    }

    /// Replaces the leaf `target` with `node`.
    func replacingLeaf(_ target: String, with node: LayoutNode) -> LayoutNode {
        switch self {
        case .leaf(let id):
            return id == target ? node : self
        case .split(let id, let direction, let ratio, let first, let second):
            return .split(
                id: id, direction: direction, ratio: ratio,
                first: first.replacingLeaf(target, with: node),
                second: second.replacingLeaf(target, with: node))
        }
    }

    func settingRatio(_ newRatio: Double, of split: Int) -> LayoutNode {
        switch self {
        case .leaf:
            return self
        case .split(let id, let direction, let ratio, let first, let second):
            return .split(
                id: id, direction: direction, ratio: id == split ? newRatio : ratio,
                first: first.settingRatio(newRatio, of: split),
                second: second.settingRatio(newRatio, of: split))
        }
    }

    /// The smallest extent this node can take along the width or the height.
    func minimumExtent(horizontal: Bool) -> Double {
        switch self {
        case .leaf:
            return horizontal ? WorkspaceLayout.minimumPaneWidth : WorkspaceLayout.minimumPaneHeight
        case .split(_, let direction, _, let first, let second):
            let a = first.minimumExtent(horizontal: horizontal)
            let b = second.minimumExtent(horizontal: horizontal)
            return (direction == .row) == horizontal ? a + b + WorkspaceLayout.gutter : max(a, b)
        }
    }

    /// Leaf frames and split frames within `rect`.
    func frames(in rect: CGRect, leaves: inout [(String, CGRect)], splits: inout [Int: CGRect]) {
        switch self {
        case .leaf(let id):
            leaves.append((id, rect))
        case .split(let id, let direction, let ratio, let first, let second):
            splits[id] = rect
            let parts = Self.divide(rect, direction, ratio)
            first.frames(in: parts.first, leaves: &leaves, splits: &splits)
            second.frames(in: parts.second, leaves: &leaves, splits: &splits)
        }
    }

    /// The gutters of this node's splits within `rect`, outer splits first.
    func gutters(in rect: CGRect) -> [GutterFrame] {
        guard case .split(let id, let direction, let ratio, let first, let second) = self else {
            return []
        }
        let parts = Self.divide(rect, direction, ratio)
        let gutter = parts.gutter
        let span = direction == .row ? rect.width - gutter.width : rect.height - gutter.height
        return [
            GutterFrame(split: id, direction: direction, ratio: ratio, frame: gutter, span: span)
        ] + first.gutters(in: parts.first) + second.gutters(in: parts.second)
    }

    /// A split's two child rects and the gutter between them.
    static func divide(_ rect: CGRect, _ direction: SplitDirection, _ ratio: Double) -> (
        first: CGRect, gutter: CGRect, second: CGRect
    ) {
        let size = WorkspaceLayout.gutter
        if direction == .row {
            let width = (rect.width - size) * ratio
            return (
                CGRect(x: rect.minX, y: rect.minY, width: width, height: rect.height),
                CGRect(x: rect.minX + width, y: rect.minY, width: size, height: rect.height),
                CGRect(
                    x: rect.minX + width + size, y: rect.minY, width: rect.width - width - size,
                    height: rect.height)
            )
        }
        let height = (rect.height - size) * ratio
        return (
            CGRect(x: rect.minX, y: rect.minY, width: rect.width, height: height),
            CGRect(x: rect.minX, y: rect.minY + height, width: rect.width, height: size),
            CGRect(
                x: rect.minX, y: rect.minY + height + size, width: rect.width,
                height: rect.height - height - size)
        )
    }

    func split(_ id: Int) -> (direction: SplitDirection, first: LayoutNode, second: LayoutNode)? {
        guard case .split(let splitID, let direction, _, let first, let second) = self else {
            return nil
        }
        if splitID == id {
            return (direction, first, second)
        }
        return first.split(id) ?? second.split(id)
    }
}

/// The space between a split's two children, where dragging resizes them.
public struct GutterFrame: Sendable, Hashable {
    public let split: Int
    public let direction: SplitDirection
    public let ratio: Double
    public let frame: CGRect
    /// The split's length along its direction without the gutter; a drag of this many
    /// points moves the ratio by 1.
    public let span: Double
}

/// Where a chat's pane sits in the workspace.
public struct PanePlacement: Sendable, Hashable {
    public let chat: String
    public let frame: CGRect
}

/// What opening a chat did.
public enum OpenOutcome: Sendable, Equatable {
    /// It was open already and is now focused.
    case focused
    case added
    /// The workspace was full; the named chat's pane now shows it.
    case replaced(String)
}

/// One project's split workspace of up to four chats.
public struct WorkspaceLayout: Sendable, Hashable {
    public static let maximumPanes = 4
    public static let minimumPaneWidth = 280.0
    public static let minimumPaneHeight = 180.0
    public static let gutter = 10.0
    /// A new chat goes beside a pane when both halves keep at least this width.
    public static let minimumSideBySideWidth = 360.0

    public private(set) var root: LayoutNode?
    /// The chat shown alone, if any.
    public private(set) var maximized: String?
    public private(set) var focused: String?
    private var nextSplitID = 1

    public init() {}

    public var leaves: [String] { root?.leaves ?? [] }

    public func contains(_ chat: String) -> Bool {
        leaves.contains(chat)
    }

    /// Pane placements in reading order, keyed by chat so views keep their identity.
    public func placements(in size: CGSize) -> [PanePlacement] {
        paneFrames(in: size).map { PanePlacement(chat: $0.chat, frame: $0.frame) }
    }

    /// The gutters of every split for a workspace of `size`, outer splits first.
    public func gutterFrames(in size: CGSize) -> [GutterFrame] {
        root?.gutters(in: CGRect(origin: .zero, size: size)) ?? []
    }

    /// Pane frames in reading order for a workspace of `size`.
    public func paneFrames(in size: CGSize) -> [(chat: String, frame: CGRect)] {
        var leaves: [(String, CGRect)] = []
        var splits: [Int: CGRect] = [:]
        root?.frames(in: CGRect(origin: .zero, size: size), leaves: &leaves, splits: &splits)
        return leaves.map { (chat: $0.0, frame: $0.1) }
    }

    /// The pane under a point of a workspace of `size`: the maximized one anywhere in it,
    /// else the pane whose frame holds the point; none in a gutter or outside.
    public func pane(at point: CGPoint, in size: CGSize) -> String? {
        guard CGRect(origin: .zero, size: size).contains(point) else { return nil }
        if let maximized {
            return maximized
        }
        return paneFrames(in: size).first { $0.frame.contains(point) }?.chat
    }

    /// Opens a chat by click: focus it if open; otherwise add it next to the largest pane
    /// (to its right when both halves stay wide enough to read, else below it); when four are open,
    /// the last pane in reading order shows it instead.
    @discardableResult
    public mutating func open(_ chat: String, in size: CGSize) -> OpenOutcome {
        if contains(chat) {
            focused = chat
            if maximized != nil {
                maximized = chat
            }
            return .focused
        }
        defer {
            maximized = nil
            focused = chat
        }
        let open = leaves
        if open.count >= Self.maximumPanes {
            let last = open[open.count - 1]
            root = root?.replacingLeaf(last, with: .leaf(chat))
            return .replaced(last)
        }
        guard root != nil else {
            root = .leaf(chat)
            return .added
        }
        let frames = paneFrames(in: size)
        let target =
            maximized.flatMap { id in frames.first { $0.chat == id } }
            ?? frames.max { $0.frame.width * $0.frame.height < $1.frame.width * $1.frame.height }!
        let halfWidth = (target.frame.width - Self.gutter) / 2
        let wide = maximized != nil || halfWidth >= Self.minimumSideBySideWidth
        insert(chat, at: target.chat, side: wide ? .right : .bottom)
        return .added
    }

    /// Drops a chat onto a pane: splits the target on `side`. A chat that is not open yet
    /// replaces the target when four are open. Dropping into an empty workspace opens it.
    @discardableResult
    public mutating func drop(_ chat: String, onto target: String?, side: DropSide) -> OpenOutcome?
    {
        guard root != nil else {
            root = .leaf(chat)
            focused = chat
            return .added
        }
        guard let target, chat != target, contains(target) else { return nil }
        defer { focus(chat) }
        if !contains(chat) && leaves.count >= Self.maximumPanes {
            replace(target, with: chat)
            return .replaced(target)
        }
        root = root?.removing(chat)
        insert(chat, at: target, side: side)
        return .added
    }

    /// Swaps two open chats' panes.
    public mutating func swap(_ a: String, _ b: String) {
        guard contains(a), contains(b) else { return }
        root = root?.mapLeaves { $0 == a ? b : $0 == b ? a : $0 }
    }

    /// Shows `chat` in `target`'s pane; an open chat swaps places instead.
    public mutating func replace(_ target: String, with chat: String) {
        guard contains(target) else { return }
        if contains(chat) {
            swap(target, chat)
            return
        }
        root = root?.replacingLeaf(target, with: .leaf(chat))
        if focused == target {
            focused = chat
        }
        if maximized == target {
            maximized = nil
        }
    }

    /// Closes a pane; its sibling takes the space.
    public mutating func remove(_ chat: String) {
        guard contains(chat) else { return }
        root = root?.removing(chat)
        if maximized == chat {
            maximized = nil
        }
        if focused == chat {
            focused = leaves.first
        }
    }

    public mutating func focus(_ chat: String) {
        if contains(chat) {
            focused = chat
        }
    }

    /// Maximizes the chat, or restores the split view when it is the maximized one.
    public mutating func toggleMaximize(_ chat: String) {
        guard contains(chat) else { return }
        maximized = maximized == chat ? nil : chat
        focused = chat
    }

    public mutating func restore() {
        maximized = nil
    }

    /// Sets a split's ratio, kept within what its panes' minimum sizes allow in `size`.
    public mutating func resize(split id: Int, ratio: Double, in size: CGSize) {
        var leaves: [(String, CGRect)] = []
        var splits: [Int: CGRect] = [:]
        root?.frames(in: CGRect(origin: .zero, size: size), leaves: &leaves, splits: &splits)
        guard let rect = splits[id], let split = root?.split(id) else { return }
        let horizontal = split.direction == .row
        let total = (horizontal ? rect.width : rect.height) - Self.gutter
        let lower = split.first.minimumExtent(horizontal: horizontal) / total
        let upper = 1 - split.second.minimumExtent(horizontal: horizontal) / total
        // Too small for both minimums: share the space in proportion to them.
        let clamped = lower > upper ? lower / (lower + 1 - upper) : min(max(ratio, lower), upper)
        root = root?.settingRatio(clamped, of: id)
    }

    private mutating func insert(_ chat: String, at target: String, side: DropSide) {
        let id = nextSplitID
        nextSplitID += 1
        let direction: SplitDirection = side == .left || side == .right ? .row : .column
        let first = side == .left || side == .top
        root = root?.replacingLeaf(
            target,
            with: .split(
                id: id, direction: direction, ratio: 0.5,
                first: first ? .leaf(chat) : .leaf(target),
                second: first ? .leaf(target) : .leaf(chat)))
    }
}
