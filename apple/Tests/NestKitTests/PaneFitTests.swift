import Foundation
import Testing

@testable import NestKit

@Suite struct PaneFitTests {
    @Test func aWidePaneShowsEverything() {
        let fit = PaneFit(width: 828)
        #expect(fit.showsDetailsLabel)
        #expect(fit.showsHeaderDetails)
        #expect(fit.showsPlaceName)
        #expect(fit.showsStatusLabel)
        #expect(fit.showsPullRequest)
        #expect(fit.context == .full)
        #expect(!fit.compact)
    }

    /// The chat's name keeps its room: the header drops the pull request chip, then
    /// shortens who started the chat and a pixie's @slug (B60).
    @Test func theHeaderGivesWayInOrder() {
        #expect(PaneFit(width: 420).showsPullRequest)
        #expect(!PaneFit(width: 419).showsPullRequest)
        #expect(PaneFit(width: 419).showsHeaderDetails)
        #expect(PaneFit(width: 360).showsHeaderDetails)
        #expect(!PaneFit(width: 359).showsHeaderDetails)
        let narrow = PaneFit(width: 280)
        #expect(!narrow.showsPullRequest && !narrow.showsHeaderDetails)
    }

    /// A pixie's Details button keeps its word while it fits, then shows its icon only.
    @Test func thePixieDetailsButtonShortensToItsIcon() {
        #expect(PaneFit(width: 480).showsDetailsLabel)
        #expect(!PaneFit(width: 479).showsDetailsLabel)
    }

    /// The branch beside the mic names itself only where the model, thinking,
    /// permission and the full context still fit beside it (B71); below that its icon.
    @Test func theComposersPlaceNamesItselfInWidePanes() {
        #expect(PaneFit(width: 560).showsPlaceName)
        #expect(!PaneFit(width: 559).showsPlaceName)
        #expect(!PaneFit(width: 460).showsPlaceName)
    }

    /// A pixie's header still shows its status word while it fits.
    @Test func theStatusWordFitsWidePixieHeaders() {
        #expect(PaneFit(width: 380).showsStatusLabel)
        #expect(!PaneFit(width: 379).showsStatusLabel)
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
