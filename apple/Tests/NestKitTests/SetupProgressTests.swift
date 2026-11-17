import Foundation
import Testing

@testable import NestKit

@Suite struct SetupProgressTests {
    static let start = Date(timeIntervalSince1970: 1_000)

    @Test func stepsTickOffInOrderAndDownloadsShowTheirRealPercent() {
        var progress = SetupProgress(startedAt: Self.start)
        let started = progress.read("@step download", at: Self.start)
        let measured = progress.read("@progress 40", at: Self.start)
        #expect(started && measured)

        #expect(progress.percent(of: .download, at: Self.start) == 40)
        #expect(progress.mark(of: .service) == .todo)

        let moved = progress.read("@step service", at: Self.start.addingTimeInterval(10))
        #expect(moved)
        #expect(progress.percent(of: .download, at: Self.start) == 100)
        #expect(progress.mark(of: .download) == .ok)
        #expect(progress.mark(of: .service) == .now)
    }

    @Test func anEstimateHoldsAt95UntilTheStepReallyEnds() {
        let progress = SetupProgress(current: .service, startedAt: Self.start)

        #expect(progress.percent(of: .service, at: Self.start) == 0)
        #expect(progress.percent(of: .service, at: Self.start.addingTimeInterval(1_000)) == 95)
    }

    @Test func skippedStepsCountAsDoneAndStepsNeverGoBack() {
        // A Mac with the newest engines already gets no engine steps: service, then start.
        var progress = SetupProgress(current: .service, startedAt: Self.start)
        _ = progress.read("@step start", at: Self.start)
        _ = progress.read("@step engines", at: Self.start)

        #expect(progress.current == .start)
        #expect(progress.percent(of: .engines, at: Self.start) == 100)
        #expect(progress.percent(of: .check, at: Self.start) == 100)
    }

    @Test func theInstallersWordsAreNotProgressLines() {
        var progress = SetupProgress(startedAt: Self.start)

        let read = progress.read("Installing Nest 0.1.1", at: Self.start)
        #expect(!read)
        #expect(progress == SetupProgress(startedAt: Self.start))
    }
}
