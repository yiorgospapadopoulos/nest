import CoreGraphics

/// The geometry of dragging a project tab along the tab strip, where every project tab
/// takes the same `step` (its width plus the spacing).
public enum TabReorder {
    /// The position the tab dragged from `start` lands at, by the nearest whole step.
    public static func target(from start: Int, translation: CGFloat, step: CGFloat, count: Int)
        -> Int
    {
        guard step > 0, count > 0 else { return start }
        let moved = Int((translation / step).rounded())
        return min(max(start + moved, 0), count - 1)
    }

    /// How far the tab at `index` slides aside while the tab from `start` is over `target`:
    /// the tabs in between move one step toward `start`. The dragged tab itself follows the
    /// pointer instead, so it is 0 here.
    public static func offset(of index: Int, from start: Int, to target: Int, step: CGFloat)
        -> CGFloat
    {
        if target > start, index > start, index <= target { return -step }
        if target < start, index >= target, index < start { return step }
        return 0
    }
}
