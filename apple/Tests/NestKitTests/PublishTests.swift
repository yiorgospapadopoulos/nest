import Foundation
import Testing

@testable import NestKit

@MainActor
@Suite struct RejectConsequenceTests {
    @Test func rejectingSaysWhatHappensToTheChatsChanges() {
        // The daemon undoes an in-place chat's edits by Claude when it is rejected (B53).
        #expect(
            RejectConsequence.of(.inPlace)
                == "The chat closes and the files Claude edited go back to how they were before it. Changes made by commands it ran are not undone."
        )
        #expect(
            RejectConsequence.of(.worktree)
                == "The chat closes and its worktree and branch are removed. Nothing is merged.")
        #expect(RejectConsequence.of(nil) == RejectConsequence.of(.worktree))
    }

    @Test func theToastSaysWhatHappenedToTheEdits() {
        #expect(
            RejectConsequence.done("Fix", mode: .inPlace)
                == "Rejected Fix. Claude's edits were undone")
        #expect(
            RejectConsequence.done("Fix", mode: .worktree) == "Rejected Fix. Nothing was merged")
        #expect(RejectConsequence.done("Fix", mode: nil) == "Rejected Fix. Nothing was merged")
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

    /// A violation found while the sheet is open needs the acknowledgement too.
    @Test func followsAViolationFoundLater() {
        var form = PublishForm(approval: review, session: session())
        #expect(form.canSubmit)
        form.follow(session(violation: true))
        #expect(form.hasViolation)
        #expect(!form.canSubmit)
        form.acknowledgeViolation = true
        #expect(form.canSubmit && form.request.acknowledgeViolation)
        form.follow(nil)
        #expect(!form.hasViolation)
    }

    /// "Push there" approves again with the address origin pushes to now (I-008).
    @Test func aConfirmedPushAddressGoesWithAPush() {
        var form = PublishForm(approval: review, session: session())
        #expect(form.request.confirmRemoteURL == nil)
        form.confirmRemoteURL = "git@github.com:me/cv.git"
        #expect(form.request.confirmRemoteURL == "git@github.com:me/cv.git")
        form.push = false
        #expect(form.request.confirmRemoteURL == nil)
    }

    @Test func aRefusedPushSaysWhereOriginPushes() {
        let changed = PushRemote(urls: ["git@new:r.git"], confirmedURL: "git@old:r.git")
        #expect(changed.summary == "origin now pushes to")
        #expect(changed.target == "git@new:r.git")
        #expect(PushRemote(urls: ["a"]).summary == "origin pushes to")
        #expect(PushRemote(urls: []).summary == "origin has no push address")
        #expect(PushRemote(urls: []).target == nil)
        let several = PushRemote(urls: ["a", "b"])
        #expect(several.summary.hasPrefix("origin pushes to several addresses"))
        #expect(several.target == nil)
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
