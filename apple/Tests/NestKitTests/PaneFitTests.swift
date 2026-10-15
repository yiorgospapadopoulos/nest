import Foundation
import Testing

@testable import NestKit

@Suite struct PaneFitTests {
    @Test func aWidePaneShowsEverything() {
        let fit = PaneFit(width: 828)
        #expect(fit.showsElapsed)
        #expect(fit.showsPlaceName)
        #expect(fit.showsStatusLabel)
        #expect(fit.showsPullRequest)
        #expect(fit.context == .full)
        #expect(!fit.compact)
    }

    @Test func theHeaderDropsItsPartsInTheMockupsOrder() {
        #expect(PaneFit(width: 470).showsElapsed)
        #expect(!PaneFit(width: 469).showsElapsed)
        #expect(PaneFit(width: 469).showsPlaceName)
        #expect(PaneFit(width: 420).showsPlaceName)
        #expect(!PaneFit(width: 419).showsPlaceName)
        #expect(PaneFit(width: 419).showsStatusLabel)
        #expect(PaneFit(width: 380).showsStatusLabel)
        #expect(!PaneFit(width: 379).showsStatusLabel)
        #expect(PaneFit(width: 330).showsPullRequest)
        #expect(!PaneFit(width: 329).showsPullRequest)
    }

    @Test func theComposerShortensThenHidesTheContext() {
        #expect(PaneFit(width: 460).context == .full)
        #expect(PaneFit(width: 459).context == .percent)
        #expect(PaneFit(width: 360).context == .percent)
        #expect(PaneFit(width: 359).context == .hidden)
        #expect(PaneFit(width: 280).context == .hidden)
    }

    @Test func narrowPanesUseCompactControls() {
        #expect(!PaneFit(width: 380).compact)
        #expect(PaneFit(width: 379).compact)
        #expect(PaneFit.shortModel("Sonnet 5.5") == "Sonnet")
        #expect(PaneFit.shortModel("Opus") == "Opus")
        #expect(PaneFit.shortModel("") == "")
    }

    @Test func compactLabelsStayRecognizable() {
        let efforts: [Effort] = [.low, .medium, .high, .xhigh, .max, .unknown]
        #expect(efforts.map(\.shortLabel) == ["Low", "Med", "High", "X-high", "Max", "Unknown"])
        #expect(PermissionMode.acceptEdits.shortLabel == "Edits")
        for mode in [PermissionMode.default, .bypassPermissions, .plan, .unknown] {
            #expect(mode.shortLabel == mode.label)
        }
    }

    @Test func contextLabelsFollowTheFit() {
        let context = SessionContext(percent: 41.4, used: 82_800, limit: 200_000)
        #expect(PaneFit.ContextStyle.full.label(context) == "context 41%")
        #expect(PaneFit.ContextStyle.percent.label(context) == "41%")
        #expect(PaneFit.ContextStyle.hidden.label(context) == nil)
    }
}
