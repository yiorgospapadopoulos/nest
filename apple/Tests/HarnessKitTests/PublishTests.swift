import Foundation
import Testing

@testable import HarnessKit

@MainActor
@Suite struct RejectConsequenceTests {
    @Test func rejectingSaysWhatHappensToTheChatsChanges() {
        // Nothing removes an in-place chat's edits from the folder.
        #expect(
            RejectConsequence.of(.inPlace) == "The chat closes. Its changes stay in your folder.")
        #expect(
            RejectConsequence.of(.worktree)
                == "The chat closes and its worktree and branch are removed. Nothing is merged.")
        #expect(RejectConsequence.of(nil) == RejectConsequence.of(.worktree))
    }
}

@Suite struct PublishFormTests {
    var review: Approval { Fixture.approval("ap-review") }

    func session(mode: SessionMode = .worktree, violation: Bool = false) -> Session {
        var session = Fixture.session(review.sessionID)
        session.mode = mode
        session.gitViolation = violation
        return session
    }

    @Test func startsWithTheTitlePushAndAPullRequest() {
        let form = PublishForm(approval: review, session: session())
        #expect(form.commitMessage == "Dark mode contrast")
        #expect(form.push && form.openPR && form.canOpenPR)
        #expect(form.steps == [.commit, .push, .pr])
        #expect(form.canSubmit)
        #expect(
            form.request
                == ApproveRequest(commitMessage: "Dark mode contrast", push: true, openPR: true))
    }

    @Test func optionalPullRequestFieldsAreTrimmedOrLeftOut() {
        var form = PublishForm(approval: review, session: nil)
        form.commitMessage = "  Raise contrast \n"
        form.prTitle = " Better dark mode "
        form.prBody = "   "
        #expect(
            form.request
                == ApproveRequest(
                    commitMessage: "Raise contrast", push: true, openPR: true,
                    prTitle: "Better dark mode"))
        form.commitMessage = "  "
        #expect(!form.canSubmit)
    }

    @Test func withoutPushOnlyTheCommitRuns() {
        var form = PublishForm(approval: review, session: session())
        form.push = false
        form.prTitle = "Ignored"
        #expect(form.steps == [.commit])
        #expect(!form.canOpenPR)
        #expect(
            form.request
                == ApproveRequest(commitMessage: "Dark mode contrast", push: false, openPR: false))
        form.push = true
        form.openPR = false
        #expect(form.steps == [.commit, .push])
        #expect(!form.request.openPR)
        #expect(form.request.prTitle == nil)
    }

    @Test func inPlaceSessionsCommitTheirFilesWithoutAPullRequest() {
        let form = PublishForm(approval: review, session: session(mode: .inPlace))
        #expect(!form.canOpenPR)
        #expect(form.steps == [.commit, .push])
        #expect(form.request.files == review.review?.paths)
        #expect(!form.request.openPR)
    }

    @Test func aGitViolationNeedsTheAcknowledgement() {
        var form = PublishForm(approval: review, session: session(violation: true))
        #expect(form.hasViolation)
        #expect(!form.canSubmit)
        form.acknowledgeViolation = true
        #expect(form.canSubmit)
        #expect(form.request.acknowledgeViolation)
        var clean = PublishForm(approval: review, session: session())
        clean.acknowledgeViolation = true
        #expect(!clean.request.acknowledgeViolation)
    }

    @Test func otherKindsHaveNoFiles() {
        #expect(PublishForm(approval: Fixture.approval("ap-perm"), session: nil).files.isEmpty)
    }

    @Test func stepsHaveTitles() {
        #expect(PublishStepKind.allCases.map(\.title) == ["Commit", "Push", "Open pull request"])
    }
}

@MainActor
@Suite struct PublishProgressTests {
    @Test func stepsRunInOrder() {
        let progress = PublishProgress(steps: [.commit, .push, .pr])
        #expect(progress.steps.map(\.state) == [.pending, .pending, .pending])
        #expect(progress.steps.map(\.id) == [.commit, .push, .pr])
        progress.start()
        #expect(progress.isRunning)
        progress.complete(.push)
        #expect(progress.steps.map(\.state) == [.done, .done, .running])
        progress.complete(.pr)
        #expect(progress.steps.map(\.state) == [.done, .done, .done])
        progress.complete(.commit)
        #expect(progress.failedStep == nil)
    }

    @Test func stepsMissingFromThePlanAreIgnored() {
        let progress = PublishProgress(steps: [.commit])
        progress.start()
        progress.complete(.pr)
        #expect(progress.steps.map(\.state) == [.running])
        progress.fail(step: .push, message: "x")
        #expect(progress.steps.map(\.state) == [.failed("x")])
    }

    @Test func aFailureWithoutAStepMarksTheRunningOne() {
        let progress = PublishProgress(steps: [.commit, .push])
        progress.start()
        progress.complete(.commit)
        progress.finish(APIError.transport("offline"))
        #expect(progress.steps.map(\.state) == [.done, .failed("offline")])
        #expect(progress.failure == .transport("offline"))
        #expect(!progress.isRunning)
    }

    @Test func anAlreadyFailedStepKeepsItsOutput() {
        let progress = PublishProgress(steps: [.commit, .push])
        progress.start()
        progress.fail(step: .commit, message: "nothing to commit")
        progress.finish(APIError.badGateway("bad"))
        #expect(progress.steps.map(\.state) == [.failed("nothing to commit"), .pending])
    }

    @Test func aGitFailureWithoutOutputShowsItsMessage() {
        let progress = PublishProgress(steps: [.commit, .push])
        progress.start()
        progress.finish(APIError.gitFailed("git push failed", step: "push", stderr: " \n"))
        #expect(progress.steps.map(\.state) == [.done, .failed("git push failed")])
    }

    @Test func aRetryStartsOver() {
        let progress = PublishProgress(steps: [.commit, .push])
        progress.start()
        progress.finish(APIError.transport("offline"))
        progress.start()
        #expect(progress.failure == nil)
        #expect(progress.steps.map(\.state) == [.running, .pending])
    }

    @Test func noStepsAtAllStillFinish() {
        let progress = PublishProgress(steps: [])
        progress.start()
        progress.finish(APIError.transport("offline"))
        #expect(progress.steps.isEmpty)
    }
}
