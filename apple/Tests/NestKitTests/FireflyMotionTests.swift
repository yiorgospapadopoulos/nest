import Foundation
import Testing

@testable import NestKit

private func near(_ a: Double, _ b: Double, _ tolerance: Double = 1e-6) -> Bool {
    abs(a - b) <= tolerance
}

private func near(_ pose: FireflyPose, _ x: Double, _ y: Double, _ scale: Double, _ opacity: Double)
    -> Bool
{
    near(pose.x, x) && near(pose.y, y) && near(pose.scale, scale) && near(pose.opacity, opacity)
}

@Suite struct FireflyMotionTests {
    @Test func easesInAndOutAsCSSDoes() {
        #expect(near(Motion.easeInOut(0), 0))
        #expect(near(Motion.easeInOut(1), 1))
        #expect(near(Motion.easeInOut(0.5), 0.5))
        // cubic-bezier(0.42, 0, 0.58, 1): slow at both ends, symmetric around the middle.
        #expect(near(Motion.easeInOut(0.25), 0.129162, 1e-5))
        #expect(near(Motion.easeInOut(0.1), 0.019722, 1e-5))
        #expect(near(Motion.easeInOut(0.75), 1 - Motion.easeInOut(0.25)))
    }

    @Test func loopsWrapAndTimesBeforeTheEpochCountForward() {
        #expect(near(Motion.fraction(0, of: 2), 0))
        #expect(near(Motion.fraction(0.5, of: 2), 0.25))
        #expect(near(Motion.fraction(5, of: 2), 0.5))
        #expect(near(Motion.fraction(-0.5, of: 2), 0.75))
        #expect(near(Motion.fraction(-4, of: 2), 0))
    }

    @Test func dotsStartAtTheirFirstKeyframes() {
        let start = FireflyMotion.poses(at: 0)
        #expect(start.count == 3)
        // Centres: each dot's top-left plus half its 3 point diameter.
        #expect(near(start[0], 2.5, 6.5, 1, 1))
        #expect(near(start[1], 8.5, 2.5, 0.8, 0.6))
        #expect(near(start[2], 13.5, 9.5, 1.1, 1))
        #expect(FireflyMotion.still == start)
    }

    @Test func dotsReachEachKeyframeOnTime() {
        #expect(near(FireflyMotion.poses(at: 0.3 * 2.4)[0], 6.5, 2.5, 0.75, 0.55))
        #expect(near(FireflyMotion.poses(at: 0.6 * 2.4)[0], 8.5, 7.5, 1.15, 1))
        #expect(near(FireflyMotion.poses(at: 0.4 * 2.9)[1], 4.5, 7.5, 1.15, 1))
        #expect(near(FireflyMotion.poses(at: 0.7 * 2.9)[1], 11.5, 8.5, 0.9, 0.7))
        #expect(near(FireflyMotion.poses(at: 0.5 * 2.1)[2], 7.5, 4.5, 0.8, 0.55))
    }

    @Test func betweenKeyframesTheyEase() {
        // Halfway through dot 3's first segment: halfway there, the curve's middle.
        #expect(near(FireflyMotion.poses(at: 0.25 * 2.1)[2], 10.5, 7, 0.95, 0.775))
        // A quarter through it, eased: well short of a quarter of the way.
        let quarter = FireflyMotion.poses(at: 0.125 * 2.1)[2]
        #expect(near(quarter.x, 13.5 - 6 * 0.129162, 1e-4))
        // Into the last segment, heading home.
        let late = FireflyMotion.poses(at: 0.85 * 2.4)[0]
        #expect(late.x > 2.5 && late.x < 8.5)
        #expect(late.scale > 1 && late.scale < 1.15)
    }

    @Test func eachDotLoopsOnItsOwnPeriod() {
        for time in [0.3, 1.1, 1.7] {
            let now = FireflyMotion.poses(at: time)
            #expect(near(FireflyMotion.poses(at: time + 2.4)[0].x, now[0].x))
            #expect(near(FireflyMotion.poses(at: time + 2.9)[1].y, now[1].y))
            #expect(near(FireflyMotion.poses(at: time + 2.1)[2].opacity, now[2].opacity))
        }
        // Different periods: they do not move in lockstep.
        #expect(!near(FireflyMotion.poses(at: 2.4)[1].x, FireflyMotion.poses(at: 0)[1].x))
        #expect(near(FireflyMotion.poses(at: -2.1)[2].x, 13.5))
    }

    @Test func dotsStayInsideTheBox() {
        for step in 0..<600 {
            for pose in FireflyMotion.poses(at: Double(step) / 100) {
                let radius = FireflyMotion.diameter / 2 * pose.scale
                #expect(pose.x - radius >= 0 && pose.x + radius <= FireflyMotion.width)
                #expect(pose.y - radius >= 0 && pose.y + radius <= FireflyMotion.height)
                #expect(pose.opacity >= 0.55 - 1e-9 && pose.opacity <= 1 + 1e-9)
            }
        }
    }

    @Test func theRowGlowSweepsFromOffTheLeftToOffTheRight() {
        // Half the row wide: its centre a quarter row off either edge.
        #expect(near(RowGlow.center(at: 0), -0.25))
        #expect(near(RowGlow.center(at: 0.9), 0.5))
        #expect(near(RowGlow.center(at: 1.8 - 1e-9), 1.25, 1e-6))
        #expect(near(RowGlow.center(at: 1.8), -0.25))
        // Ease-in-out: a quarter of the time covers far less than a quarter of the way.
        #expect(near(RowGlow.center(at: 0.45), -0.25 + 1.5 * 0.129162, 1e-5))
        #expect(RowGlow.bandWidth == 0.5)
        #expect(RowGlow.peakOpacity == 0.24)
    }

    @Test func theFirefliesKeepTheirFourByThreeBoxAtAnyHeight() {
        #expect(near(FireflyMotion.width(forHeight: 12), 16))
        #expect(near(FireflyMotion.width(forHeight: 9), 12))
        #expect(near(FireflyMotion.width(forHeight: 14), 14 * 4 / 3))
    }

    @Test func aStatusMarkAnimatesOnlyWhileRunningInASlotAsWideAsItsFireflies() {
        for tone in StatusTone.allCases {
            #expect(StatusMarkMetrics.animates(tone) == (tone == .running))
        }
        // A plain 6 point dot sits centred in the 12 by 9 slot of the row's fireflies.
        #expect(StatusMarkMetrics.dotSize == 6)
        #expect(StatusMarkMetrics.fireflyHeight == 9)
        #expect(near(StatusMarkMetrics.slotWidth, 12))
    }
}
