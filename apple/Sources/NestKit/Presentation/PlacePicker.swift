import Foundation

/// One row of the "Work on" picker (P1, B131): a branch in its lane, what choosing it sets
/// and, on hover, the new worktree from it.
public struct PlacePickerRow: Sendable, Hashable, Identifiable {
    public static let height = 30.0

    public let lane: BranchLaneRow

    public var id: String { lane.id }

    public var branch: BranchMap.Branch { lane.branch }

    /// Where a click on the row works, for that one chat.
    public var choice: NewChatChoice { branch.newChatChoice }

    /// "New worktree from" it; a remote-only row has none.
    public var newWorktree: NewChatChoice? {
        branch.remote == nil ? .newWorktree(from: branch.name) : nil
    }

    public var accessibilityLabel: String {
        if branch.here {
            "Work on \(branch.name) in the project folder"
        } else if branch.worktree != nil {
            "Work in worktree \(branch.name)"
        } else {
            "Work on \(branch.name), branch"
        }
    }
}

/// Where a new chat can work, from the project's branch map (B96, P1, B131): the top row
/// pinned, every other branch under it in its lane.
public struct PlacePicker: Sendable, Hashable {
    /// Under the pinned top row; the rest scroll.
    public static let visibleRows = 8

    public let lanes: BranchLanes
    public let top: PlacePickerRow?
    public let rows: [PlacePickerRow]

    public init(map: BranchMap) {
        self.init(lanes: BranchLanes(map: map, maxDepth: BranchLanes.indentCap))
    }

    public init(lanes: BranchLanes) {
        self.lanes = lanes
        top = lanes.top.map(PlacePickerRow.init(lane:))
        rows = lanes.rest.map(PlacePickerRow.init(lane:))
    }
}

extension BranchMap.Branch {
    /// Where a click on its picker row works: the folder's branch in place, a worktree in
    /// its folder, any other branch on that branch itself.
    public var newChatChoice: NewChatChoice {
        if here {
            return .inPlace
        }
        if let worktree {
            return .worktree(path: worktree.path, branch: name)
        }
        return .onBranch(name)
    }
}

/// Where a list of fixed-height rows must scroll to bring one into view.
public enum RowReveal {
    /// The room left past a name brought in sideways.
    public static let sideRoom = 44.0

    /// The offset that centres `row`; nil when it is in view already, which moves nothing.
    public static func offset(
        row: Int, height: Double, current: Double, viewport: Double, content: Double
    ) -> Double? {
        let top = Double(row) * height
        guard top < current || top + height > current + viewport else { return nil }
        return clamped(top - (viewport - height) / 2, viewport: viewport, content: content)
    }

    /// The sideways offset that shows a name from `start` to `end`: its ending, with some
    /// room, but never so far that its start leaves the view, so a name wider than the view
    /// shows its start. Nil when it is in view already.
    public static func sideways(
        start: Double, end: Double, current: Double, viewport: Double, content: Double
    ) -> Double? {
        let right = current + viewport
        if end > right {
            let target = current + min(end - right + sideRoom, start - current - sideRoom)
            return clamped(target, viewport: viewport, content: content)
        }
        guard start < current else { return nil }
        return clamped(start - sideRoom, viewport: viewport, content: content)
    }

    private static func clamped(_ offset: Double, viewport: Double, content: Double) -> Double {
        min(max(offset, 0), max(content - viewport, 0))
    }
}
