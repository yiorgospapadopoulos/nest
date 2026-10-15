import Foundation
import Testing

@testable import NestKit

@Suite struct PublishFormTests {
    var review: Approval { Fixture.approval("ap-review") }

    func session(mode: SessionMode = .worktree, pr: String? = nil) -> Session {
        var session = Fixture.session(review.sessionID)
        session.mode = mode
        session.prURL = pr
        return session
    }

    @Test func startsWithTheTitlePushAndAPullRequest() {
        let form = PublishForm(approval: review, session: session())
        #expect(form.commitMessage == "Dark mode contrast")
        #expect(form.pushes && form.openPR && form.canOpenPR)
        #expect(form.steps == [.commit, .push, .pr])
        #expect(form.canSubmit)
        #expect(
            form.request
                == ApproveRequest(commitMessage: "Dark mode contrast", push: true, openPR: true))
    }

    /// "Push there" approves again with the address origin pushes to now (I-008).
    @Test func aConfirmedPushAddressGoesWithAPush() {
        var form = PublishForm(approval: review, session: session())
        #expect(form.request.confirmRemoteURL == nil)
        form.confirmRemoteURL = "git@github.com:me/cv.git"
        #expect(form.request.confirmRemoteURL == "git@github.com:me/cv.git")
        form.openPR = false
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

    /// Without a pull request to open, Approve only commits: it never pushes (B56).
    @Test func withoutAPullRequestOnlyTheCommitRuns() {
        var form = PublishForm(approval: review, session: session())
        form.openPR = false
        form.prTitle = "Ignored"
        form.confirmRemoteURL = "git@github.com:me/cv.git"
        #expect(form.canOpenPR && !form.pushes)
        #expect(form.steps == [.commit])
        #expect(
            form.request
                == ApproveRequest(commitMessage: "Dark mode contrast", push: false, openPR: false))
        #expect(form.title == "Approve and commit")
        #expect(form.done("Fix") == "Committed Fix without pushing")
    }

    /// An in-place chat commits its files on the current branch and never pushes (B56).
    @Test func inPlaceSessionsOnlyCommitTheirFiles() {
        let form = PublishForm(approval: review, session: session(mode: .inPlace))
        #expect(!form.canOpenPR && !form.pushes)
        #expect(form.steps == [.commit])
        #expect(form.title == "Approve and commit")
        #expect(
            form.request
                == ApproveRequest(
                    commitMessage: "Dark mode contrast", files: review.review?.paths,
                    push: false, openPR: false))
        #expect(form.done("Fix") == "Committed Fix without pushing")
        #expect(
            form.note
                == "This chat works in the project folder, so its files are committed on the current branch, without pushing or a pull request."
        )
    }

    /// A worktree chat whose pull request is open commits to its branch without pushing;
    /// the user pushes to update the pull request (B56).
    @Test func aChatWithAPullRequestOnlyCommits() {
        let form = PublishForm(
            approval: review, session: session(pr: "https://github.com/me/cv/pull/3"))
        #expect(form.hasPullRequest)
        #expect(!form.canOpenPR && !form.pushes)
        #expect(form.steps == [.commit])
        #expect(form.title == "Approve and commit")
        #expect(
            form.request
                == ApproveRequest(commitMessage: "Dark mode contrast", push: false, openPR: false))
        #expect(form.done("Fix") == "Committed Fix without pushing")
        #expect(
            form.note
                == "This chat's pull request is already open. Approve commits to its branch without pushing; push it yourself to update the pull request."
        )
    }

    @Test func openingAPullRequestSaysSo() {
        let form = PublishForm(approval: review, session: session())
        #expect(form.title == "Approve and open PR")
        #expect(form.done("Fix") == "Opened a pull request for Fix")
        #expect(form.note == nil)
    }

    /// The Approve button on the review card and the changes sheet (B56): only a worktree
    /// chat without a pull request pushes, to open one.
    @Test func theApproveButtonFollowsTheChat() {
        let pr = session(pr: "https://github.com/me/cv/pull/3")
        #expect(PublishForm.approveTitle(for: session()) == "Approve and open PR")
        #expect(PublishForm.approveTitle(for: nil) == "Approve and open PR")
        #expect(PublishForm.approveTitle(for: pr) == "Approve and commit")
        #expect(PublishForm.approveTitle(for: session(mode: .inPlace)) == "Approve and commit")
        #expect(PublishForm.pushes(for: session()) && PublishForm.pushes(for: nil))
        #expect(!PublishForm.pushes(for: pr))
        #expect(!PublishForm.pushes(for: session(mode: .inPlace)))
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
