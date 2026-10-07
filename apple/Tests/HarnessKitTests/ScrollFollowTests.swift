import Testing

@testable import HarnessKit

@Suite struct ScrollFollowTests {
    /// A viewport of 500 over `content`, scrolled to `offset`.
    private func metrics(_ offset: Double, content: Double, viewport: Double = 500)
        -> ScrollMetrics
    {
        ScrollMetrics(offset: offset, viewport: viewport, content: content)
    }

    private func scroll(_ follow: inout ScrollFollow, _ metrics: ScrollMetrics) -> Bool {
        follow.update(metrics)
    }

    private func arrive(_ follow: inout ScrollFollow) -> Bool {
        follow.contentArrived()
    }

    @Test func atBottomAllowsASmallThreshold() {
        #expect(metrics(500, content: 1000).isAtBottom)
        #expect(metrics(461, content: 1000).isAtBottom)
        #expect(!metrics(459, content: 1000).isAtBottom)
        #expect(metrics(0, content: 300).isAtBottom)
    }

    @Test func followsFromTheStartAndKeepsFollowingAsContentGrows() {
        var follow = ScrollFollow()
        #expect(follow.following)
        #expect(!scroll(&follow, metrics(500, content: 1000)))
        // Growth moves the bottom away; the view must scroll down, not stop following.
        #expect(scroll(&follow, metrics(500, content: 1300)))
        #expect(follow.following)
        #expect(arrive(&follow))
        #expect(!follow.showsJump)
    }

    @Test func scrollingUpStopsFollowingAndNothingMovesTheView() {
        var follow = ScrollFollow()
        _ = follow.update(metrics(500, content: 1000))
        #expect(!scroll(&follow, metrics(200, content: 1000)))
        #expect(!follow.following)
        // Streaming text, a sent message and a viewport resize all leave the position alone.
        #expect(!scroll(&follow, metrics(200, content: 1400)))
        #expect(!arrive(&follow))
        #expect(!scroll(&follow, metrics(200, content: 1400, viewport: 600)))
        #expect(!follow.following)
        #expect(follow.showsJump)
    }

    @Test func noJumpButtonUntilNewContentArrives() {
        var follow = ScrollFollow()
        _ = follow.update(metrics(500, content: 1000))
        _ = follow.update(metrics(100, content: 1000))
        #expect(!follow.showsJump)
        // Opening a tool row grows the content but is not new content.
        _ = follow.update(metrics(100, content: 1200))
        #expect(!follow.showsJump)
    }

    @Test func scrollingBackToTheBottomResumesFollowing() {
        var follow = ScrollFollow()
        _ = follow.update(metrics(500, content: 1000))
        _ = follow.update(metrics(100, content: 1000))
        _ = follow.contentArrived()
        #expect(!scroll(&follow, metrics(480, content: 1000)))
        #expect(follow.following)
        #expect(!follow.showsJump)
        #expect(scroll(&follow, metrics(480, content: 1100)))
    }

    @Test func jumpingToLatestResumesFollowing() {
        var follow = ScrollFollow()
        _ = follow.update(metrics(500, content: 1000))
        _ = follow.update(metrics(100, content: 1000))
        _ = follow.contentArrived()
        follow.jumpToLatest()
        #expect(follow.following)
        #expect(!follow.showsJump)
        // While the jump animates, content growth keeps the view heading for the bottom.
        #expect(scroll(&follow, metrics(300, content: 1200)))
        // The animated scroll's own steps do not count as the user scrolling up.
        _ = follow.update(metrics(500, content: 1200))
        #expect(follow.following)
        _ = follow.update(metrics(700, content: 1200))
        _ = follow.update(metrics(400, content: 1200))
        #expect(!follow.following)
    }

    @Test func holdingStaysOnAnEarlierItemUntilTheUserReturns() {
        var follow = ScrollFollow()
        follow.jumpToLatest()
        follow.hold()
        #expect(!follow.following)
        // A programmatic scroll to the hit, then growth: nothing pulls the view down.
        #expect(!scroll(&follow, metrics(200, content: 1000)))
        #expect(!scroll(&follow, metrics(200, content: 1400)))
        #expect(!arrive(&follow))
        #expect(follow.showsJump)
        #expect(!scroll(&follow, metrics(900, content: 1400)))
        #expect(follow.following)
    }
}
