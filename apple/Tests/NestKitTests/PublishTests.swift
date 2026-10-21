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

    /// A worktree chat whose pull request #8 Nest last read in this state.
    func session(prState: PRState, number: Int = 8) -> Session {
        var session = session(pr: "https://github.com/me/cv/pull/\(number)")
        session.pr = Fixture.decode(
            PullRequest.self,
            json: """
                {"number": \(number), "url": "https://github.com/me/cv/pull/\(number)",
                 "title": "Dark mode", "state": "\(prState.rawValue)",
                 "checks": {"state": "success", "passed": 1, "failed": 0, "pending": 0},
                 "changed_at": "2026-10-21T09:00:00Z", "updated_at": "2026-10-21T09:00:00Z"}
                """)
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

    /// A worktree chat whose pull request is open commits and pushes to its branch, so
    /// work on review comments reaches the pull request (B101); the confirmed push address
    /// goes with it as with the first push.
    @Test func aChatWithAnOpenPullRequestPushesToIt() {
        var form = PublishForm(approval: review, session: session(prState: .open))
        form.prTitle = "Ignored"
        form.prBody = "Ignored"
        #expect(form.hasPullRequest && form.pullRequest == 8)
        #expect(!form.canOpenPR && form.pushes && form.pushesToPR)
        #expect(form.steps == [.commit, .push])
        #expect(form.title == "Approve and push to #8")
        #expect(
            form.request
                == ApproveRequest(commitMessage: "Dark mode contrast", push: true, openPR: false))
        form.confirmRemoteURL = "git@github.com:me/cv.git"
        #expect(form.request.confirmRemoteURL == "git@github.com:me/cv.git")
        #expect(form.done("Fix") == "Pushed Fix to #8")
        #expect(
            form.note
                == "Approve commits and pushes to the pull request's branch, updating #8.")
    }

    /// Before the push, the sheet says Nest also replies on the threads sent to the agent
    /// and not replied to yet, without resolving them.
    @Test func pushingSaysItRepliesOnSentThreads() {
        var chat = session(prState: .open)
        chat.review = Fixture.decode(
            PRReview.self,
            json: """
                {"items": [
                   {"id": "t1:c1", "kind": "thread", "path": "a.py", "line": 1, "outdated": false,
                    "author": "o", "body": "b", "url": "u", "created_at": "2026-10-21T09:00:00Z"},
                   {"id": "t2:c2", "kind": "thread", "path": "a.py", "line": 2, "outdated": false,
                    "author": "o", "body": "b", "url": "u", "created_at": "2026-10-21T09:00:00Z"},
                   {"id": "r3", "kind": "review", "path": null, "line": null, "outdated": false,
                    "author": "o", "body": "b", "url": "u", "created_at": "2026-10-21T09:00:00Z"}],
                 "sent": ["t1:c1", "t2:c2", "r3"], "changes_requested": false,
                 "auto_send": false}
                """)
        var form = PublishForm(approval: review, session: chat)
        #expect(
            form.replyNote
                == "Also replies on 2 review threads with the commit, without resolving them.")
        #expect(PublishForm.replyNote(for: chat) == form.replyNote)
        chat.review?.replied = ["t1:c1"]
        #expect(
            PublishForm(approval: review, session: chat).replyNote
                == "Also replies on 1 review thread with the commit, without resolving them.")
        // Approve and commit pushes nothing, so it replies on nothing.
        form.pushToPR = false
        #expect(form.replyNote == nil)
        chat.review?.replied = ["t1:c1", "t2:c2"]
        #expect(PublishForm(approval: review, session: chat).replyNote == nil)
        #expect(PublishForm.replyNote(for: chat) == nil)
        // No open pull request, or no review: nothing to reply on.
        #expect(PublishForm(approval: review, session: session(prState: .merged)).replyNote == nil)
        #expect(PublishForm.replyNote(for: session(prState: .open)) == nil)
        #expect(PublishForm.replyNote(for: session()) == nil)
    }

    /// Approve and commit stays beside it: a commit only, as before (B56).
    @Test func aChatWithAnOpenPullRequestCanStillOnlyCommit() {
        var form = PublishForm(approval: review, session: session(prState: .open))
        form.pushToPR = false
        form.confirmRemoteURL = "git@github.com:me/cv.git"
        #expect(!form.pushes && !form.pushesToPR)
        #expect(form.steps == [.commit])
        #expect(form.title == "Approve and commit")
        #expect(
            form.request
                == ApproveRequest(commitMessage: "Dark mode contrast", push: false, openPR: false))
        #expect(form.done("Fix") == "Committed Fix without pushing")
        #expect(
            form.note
                == "This chat's pull request is already open. Approve and commit commits to its branch without pushing; the pull request stays as it is."
        )
    }

    /// Before Nest read the pull request, its number comes from its address.
    @Test func anUnreadPullRequestIsTakenAsOpen() {
        let form = PublishForm(
            approval: review, session: session(pr: "https://github.com/me/cv/pull/3"))
        #expect(form.pullRequest == 3)
        #expect(form.title == "Approve and push to #3")
        let odd = PublishForm(approval: review, session: session(pr: "https://example.com/x"))
        #expect(odd.pullRequest == nil)
        #expect(odd.title == "Approve and commit")
    }

    /// A merged or closed pull request takes no push: Approve commits only.
    @Test func aMergedOrClosedPullRequestOnlyCommits() {
        for state in [PRState.merged, .closed] {
            let form = PublishForm(approval: review, session: session(prState: state))
            #expect(form.hasPullRequest && form.pullRequest == nil)
            #expect(!form.pushes)
            #expect(form.steps == [.commit])
            #expect(form.title == "Approve and commit")
            #expect(
                form.request
                    == ApproveRequest(
                        commitMessage: "Dark mode contrast", push: false, openPR: false))
            #expect(form.done("Fix") == "Committed Fix without pushing")
            #expect(
                form.note
                    == "This chat's pull request is no longer open. Approve commits to its branch without pushing."
            )
        }
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
        let open = session(prState: .open)
        let merged = session(prState: .merged)
        #expect(PublishForm.approveTitle(for: session()) == "Approve and open PR")
        #expect(PublishForm.approveTitle(for: nil) == "Approve and open PR")
        #expect(PublishForm.approveTitle(for: open) == "Approve and push to #8")
        #expect(PublishForm.approveTitle(for: merged) == "Approve and commit")
        #expect(PublishForm.approveTitle(for: session(mode: .inPlace)) == "Approve and commit")
        #expect(PublishForm.pushes(for: session()) && PublishForm.pushes(for: nil))
        #expect(PublishForm.pushes(for: open))
        #expect(!PublishForm.pushes(for: merged))
        #expect(!PublishForm.pushes(for: session(mode: .inPlace)))
        // Approve and commit shows beside it only for an open pull request.
        #expect(PublishForm.offersCommitOnly(for: open))
        #expect(!PublishForm.offersCommitOnly(for: merged))
        #expect(!PublishForm.offersCommitOnly(for: session()))
        #expect(!PublishForm.offersCommitOnly(for: nil))
        #expect(PublishForm.commitTitle == "Approve and commit")
        // An in-place chat's pull request is not its own branch's to push.
        var inPlace = open
        inPlace.mode = .inPlace
        #expect(PublishForm.approveTitle(for: inPlace) == "Approve and commit")
        #expect(!PublishForm.pushes(for: inPlace))
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
