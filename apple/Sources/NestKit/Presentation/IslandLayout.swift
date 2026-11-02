import Foundation

// How many pixies fit on each side of the notch and how wide the wings grow (B114), in
// points, with the mockup's numbers; and what a click on the island does.

/// One side of the island as it fits.
public struct IslandSideFit: Sendable, Hashable {
    /// How many pixies show, the first ones of the side in order.
    public var shown: Int
    /// The rest, in the +N.
    public var more: Int
    /// The +N sits beside the pixies; else on top of the first one.
    public var countInline: Bool
    /// The +N is orange: a hidden entry needs the user, failed or was interrupted.
    public var moreIsAlert: Bool
    /// The wing's width from the notch's edge (or the pill's centre gap).
    public var width: Double
}

/// Both sides as they fit.
public struct IslandFit: Sendable, Hashable {
    public var left: IslandSideFit
    public var right: IslandSideFit
}

public enum IslandLayout {
    /// A sprite's size.
    public static let sprite = 28.0
    /// A pixie's slot: the sprite and a small gap.
    public static let slot = 30.0
    /// The wing's inner padding before the first pixie.
    public static let pad = 8.0
    /// The inline +N's width.
    public static let plus = 24.0
    /// The pill's gap from its centre to each side.
    public static let pillGap = 12.0
    /// The smallest form's free width: one pixie right against the notch.
    public static let smallest = sprite + 12
    /// At most this many pixies on a side.
    public static let most = 3

    /// The free menu bar beside the notch: left from the rightmost app menu to the notch,
    /// right from the notch to the leftmost status item, each less a 10 point margin. A side
    /// whose edge is unknown (no Accessibility access) gets the smallest form.
    public static func freeWidth(
        notchMinX: Double, notchMaxX: Double, appMenuMaxX: Double?, statusItemMinX: Double?
    ) -> (left: Double, right: Double) {
        (
            appMenuMaxX.map { max(smallest, notchMinX - ($0 + 10)) } ?? smallest,
            statusItemMinX.map { max(smallest, ($0 - 10) - notchMaxX) } ?? smallest
        )
    }

    /// How many of `count` entries show in `space`, and whether the +N fits beside them.
    /// A side with anything shows at least one.
    public static func count(space: Double, entries count: Int) -> (shown: Int, inline: Bool) {
        guard count > 0 else { return (0, false) }
        var shown = min(most, count)
        while shown > 1,
            pad + Double(shown) * slot + (count > shown ? plus : 0) + 4 > space
        {
            shown -= 1
        }
        let inline = count > shown && pad + Double(shown) * slot + plus + 4 <= space
        return (shown, inline)
    }

    /// Both sides of `state`. The pill never covers the menu bar, so three always fit and
    /// both sides are as wide as the wider one.
    public static func fit(_ state: IslandState, left: Double, right: Double, pill: Bool)
        -> IslandFit
    {
        let leftStatuses =
            state.nightshade != nil ? [IslandStatus.working] : state.left.map(\.status)
        let rightStatuses = state.restingBluebell ? [IslandStatus.done] : state.right.map(\.status)
        var leftFit = side(leftStatuses, space: pill ? .infinity : left, extra: 2)
        var rightFit = side(rightStatuses, space: pill ? .infinity : right, extra: 6)
        if pill {
            let width = max(leftFit.width, rightFit.width, sprite * 2 + 20)
            leftFit.width = width
            rightFit.width = width
        }
        return IslandFit(left: leftFit, right: rightFit)
    }

    private static func side(_ statuses: [IslandStatus], space: Double, extra: Double)
        -> IslandSideFit
    {
        let (shown, inline) = count(space: space, entries: statuses.count)
        let more = statuses.count - shown
        let width = max(
            smallest, pad + Double(shown) * slot + (more > 0 && inline ? plus : 0) + extra)
        return IslandSideFit(
            shown: shown, more: more, countInline: inline,
            moreIsAlert: statuses.dropFirst(shown).contains(where: \.isAlert), width: width)
    }
}

/// What was clicked on the island or in its list.
public enum IslandTarget: Sendable, Hashable {
    /// Nightshade, the resting Bluebell or the empty strip.
    case strip
    /// A pixie on the island, or its row in the list.
    case entry(IslandEntry)
    /// A side's +N.
    case more
}

/// What a click does.
public enum IslandAction: Sendable, Hashable {
    case openNest
    /// Opens the chat the work happens in.
    case open(IslandPlace)
    /// Opens the chat with the approval in view: the right panel open, its row unfolded.
    case openApproval(IslandPlace, approvalID: String)
    /// Opens the hover list, pinned until the mouse leaves.
    case showList
}

extension IslandAction {
    /// A click on a pixie opens its chat, so the chat counts as seen: a done, failed or
    /// interrupted pixie leaves and one that needs the user turns calm.
    public static func of(_ target: IslandTarget) -> IslandAction {
        switch target {
        case .strip: .openNest
        case .more: .showList
        case .entry(let entry):
            if let approval = entry.approvalID, entry.status == .needsYou || entry.status == .seen {
                .openApproval(entry.place, approvalID: approval)
            } else {
                .open(entry.place)
            }
        }
    }

    /// The chat it opens, which the click marks seen.
    public var seenChat: String? {
        switch self {
        case .open(let place), .openApproval(let place, _): place.sessionID
        case .openNest, .showList: nil
        }
    }
}
