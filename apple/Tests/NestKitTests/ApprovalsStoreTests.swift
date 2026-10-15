import Foundation
import Testing

@testable import NestKit

@MainActor
@Suite struct ApprovalsStoreTests {
    let api = FakeAPI()
    let store: ApprovalsStore

    init() {
        store = ApprovalsStore(api: api)
        var resolved = Fixture.approval("ap-perm")
        resolved.id = "ap-old"
        resolved.status = .resolved
        let approvals = Fixture.approvals + [resolved]
        let sessions = approvals.map { Fixture.session($0.sessionID, repo: $0.repo) }
        api.set {
            $0.approvals = approvals
            $0.sessions = sessions
        }
    }

    var permission: Approval { Fixture.approval("ap-perm") }
    var question: Approval { Fixture.approval("ap-question") }
    var review: Approval { Fixture.approval("ap-review") }

    /// The pending items, with the review's diff loaded as its sheets load it.
    func loadReview() async throws {
        try await store.load()
        try await store.loadDiff(for: review)
    }

    @Test func loadsPendingItemsByRepoAndSession() async throws {
        try await store.load()

        #expect(store.pending.map(\.id) == ["ap-perm", "ap-question", "ap-review"])
        #expect(store.pending(repo: "todo-ui").map(\.id) == ["ap-perm", "ap-review"])
        #expect(store.pending(session: question.sessionID).map(\.id) == ["ap-question"])
        #expect(store.hasPendingReview(session: review.sessionID))
        #expect(!store.hasPendingReview(session: permission.sessionID))
    }

    @Test func resolvesPermissions() async throws {
        try await store.load()

        try await store.allow(permission, always: true)
        #expect(store.pending(repo: "todo-ui").map(\.id) == ["ap-review"])
        try await store.deny(question, message: "Not now")

        #expect(
            api.calls.suffix(2) == [
                #"resolveApproval ap-perm {"always":true,"behavior":"allow","dismiss":false}"#,
                #"resolveApproval ap-question {"always":false,"behavior":"deny","dismiss":false,"message":"Not now"}"#,
            ])
    }

    @Test func questionsStartWithTheRecommendedOptions() throws {
        let questions = try #require(question.question).questions

        #expect(store.selection(for: question, question: questions[0]) == ["DAG"])
        #expect(store.selection(for: question, question: questions[1]) == ["JSON", "Ink"])
        var none = questions[0]
        none.options = none.options.map { option in
            var option = option
            option.recommended = false
            return option
        }
        #expect(store.selection(for: question, question: none).isEmpty)
    }

    @Test func pickingOptionsReplacesOrToggles() throws {
        let questions = try #require(question.question).questions

        store.select("Tree", for: question, question: questions[0])
        #expect(store.selection(for: question, question: questions[0]) == ["Tree"])
        store.select("Ink", for: question, question: questions[1])
        store.select("Twine", for: question, question: questions[1])
        #expect(store.selection(for: question, question: questions[1]) == ["JSON", "Twine"])
        #expect(store.answer(for: question, question: questions[0]) == ["Tree"])
        #expect(!store.isOtherChosen(for: question, question: questions[0]))
    }

    /// Other is the last option (B60): with one answer allowed it replaces the options,
    /// and its text, trimmed, is the answer.
    @Test func otherIsExclusiveWhenOneAnswerIsAllowed() throws {
        let single = try #require(question.question).questions[0]

        store.chooseOther(for: question, question: single)
        #expect(store.isOtherChosen(for: question, question: single))
        #expect(store.selection(for: question, question: single).isEmpty)
        #expect(store.answer(for: question, question: single).isEmpty)
        store.answerOther("  A graph of scenes ", for: question, question: single)
        #expect(store.otherAnswer(for: question, question: single) == "  A graph of scenes ")
        #expect(store.answer(for: question, question: single) == ["A graph of scenes"])
        // Choosing it again keeps it chosen.
        store.chooseOther(for: question, question: single)
        #expect(store.isOtherChosen(for: question, question: single))

        store.select("Tree", for: question, question: single)
        #expect(!store.isOtherChosen(for: question, question: single))
        #expect(store.answer(for: question, question: single) == ["Tree"])
        // The typed text waits for Other to be chosen again.
        store.chooseOther(for: question, question: single)
        #expect(store.answer(for: question, question: single) == ["A graph of scenes"])
    }

    /// With several answers allowed, Other toggles like an option and its text joins the
    /// picked labels.
    @Test func otherJoinsThePickedOptionsWhenSeveralAreAllowed() throws {
        let multiple = try #require(question.question).questions[1]

        store.chooseOther(for: question, question: multiple)
        #expect(store.isOtherChosen(for: question, question: multiple))
        #expect(store.answer(for: question, question: multiple) == ["JSON", "Ink"])
        store.answerOther(" YAML ", for: question, question: multiple)
        #expect(store.answer(for: question, question: multiple) == ["JSON", "Ink", "YAML"])
        store.select("Twine", for: question, question: multiple)
        #expect(store.isOtherChosen(for: question, question: multiple))
        #expect(
            store.answer(for: question, question: multiple) == ["JSON", "Ink", "Twine", "YAML"])

        store.chooseOther(for: question, question: multiple)
        #expect(!store.isOtherChosen(for: question, question: multiple))
        #expect(store.answer(for: question, question: multiple) == ["JSON", "Ink", "Twine"])
    }

    /// Text typed without Other chosen is not sent.
    @Test func otherTextCountsOnlyWhileOtherIsChosen() throws {
        let questions = try #require(question.question).questions
        store.answerOther("Neither", for: question, question: questions[0])
        #expect(store.answer(for: question, question: questions[0]) == ["DAG"])
        store.chooseOther(for: question, question: questions[0])
        #expect(store.answer(for: question, question: questions[0]) == ["Neither"])
    }

    @Test func answersNeedSomethingForEveryQuestion() throws {
        let questions = try #require(question.question).questions
        #expect(store.canSubmitAnswers(question))
        store.select("JSON", for: question, question: questions[1])
        store.select("Ink", for: question, question: questions[1])
        #expect(!store.canSubmitAnswers(question))
        store.chooseOther(for: question, question: questions[1])
        #expect(!store.canSubmitAnswers(question))
        store.answerOther("YAML", for: question, question: questions[1])
        #expect(store.canSubmitAnswers(question))
        #expect(!store.canSubmitAnswers(permission))
    }

    /// Other chosen with blank text holds Send back, even beside picked options.
    @Test func aBlankOtherCannotBeSent() throws {
        let questions = try #require(question.question).questions
        store.chooseOther(for: question, question: questions[1])
        #expect(!store.canSubmitAnswers(question))
        store.answerOther("   ", for: question, question: questions[1])
        #expect(!store.canSubmitAnswers(question))
        store.chooseOther(for: question, question: questions[1])
        #expect(store.canSubmitAnswers(question))
    }

    @Test func submitsEveryQuestionsAnswer() async throws {
        try await store.load()
        let questions = try #require(question.question).questions
        store.select("Twine", for: question, question: questions[1])

        try await store.submitAnswers(question)

        #expect(
            api.calls.last
                == #"resolveApproval ap-question {"always":false,"answers":{"Store branches as a DAG or a tree?":["DAG"],"Which formats should export support?":["JSON","Ink","Twine"]},"dismiss":false}"#
        )
        #expect(store.pending(session: question.sessionID).isEmpty)
        // A later item with the same id starts from the recommendation again.
        #expect(store.selection(for: question, question: questions[1]) == ["JSON", "Ink"])
    }

    @Test func submitsOtherAnswersInTheSameShape() async throws {
        try await store.load()
        let questions = try #require(question.question).questions
        store.chooseOther(for: question, question: questions[0])
        store.answerOther("Neither", for: question, question: questions[0])
        store.chooseOther(for: question, question: questions[1])
        store.answerOther("YAML", for: question, question: questions[1])

        try await store.submitAnswers(question)

        #expect(
            api.calls.last
                == #"resolveApproval ap-question {"always":false,"answers":{"Store branches as a DAG or a tree?":["Neither"],"Which formats should export support?":["JSON","Ink","YAML"]},"dismiss":false}"#
        )
        // A later item with the same id starts without Other.
        #expect(!store.isOtherChosen(for: question, question: questions[0]))
        #expect(store.otherAnswer(for: question, question: questions[1]).isEmpty)
    }

    @Test func onlyQuestionsTakeAnswers() async throws {
        try await store.load()
        try await store.submitAnswers(permission)
        #expect(api.calls == ["approvals"])
        #expect(store.pending.count == 3)
    }

    @Test func dismissesQuestions() async throws {
        try await store.load()
        try await store.dismiss(question, message: "Skip")
        #expect(
            api.calls.last
                == #"resolveApproval ap-question {"always":false,"dismiss":true,"message":"Skip"}"#)
    }

    @Test func aFailedResolveKeepsTheItem() async throws {
        try await store.load()
        api.fail("resolveApproval", with: APIError.conflict("already resolved"))
        await #expect(throws: APIError.self) { try await store.allow(permission) }
        #expect(store.pending.count == 3)
    }

    @Test func publishesAWorktreeReviewWithThePullRequest() async throws {
        try await loadReview()
        let form = store.publishForm(for: review, session: nil)
        #expect(form.commitMessage == "Dark mode contrast")
        #expect(store.progress(session: review.sessionID) == nil)

        let session = try await store.publish(review, form)

        #expect(session.prURL == "https://example.com/pr/1")
        #expect(
            api.calls.last
                == "approve \(review.sessionID) Dark mode contrast open_pr=true \(Self.loadedHead)")
        #expect(!store.hasPendingReview(session: review.sessionID))
        let progress = try #require(store.progress(session: review.sessionID))
        #expect(progress.steps.map(\.state) == [.done, .done, .done])
        #expect(progress.result == session)
        #expect(!progress.isRunning)
        #expect(store.busy.isEmpty)
    }

    @Test func publishesAnInPlaceReviewWithItsFilesAndNoPullRequest() async throws {
        try await loadReview()
        var session = Fixture.session(review.sessionID)
        session.mode = .inPlace
        var form = store.publishForm(for: review, session: session)
        form.commitMessage = "Raise contrast"
        try await store.publish(review, form)
        #expect(
            api.calls.last
                == #"approve \#(review.sessionID) Raise contrast open_pr=false files=["app/globals.css", "app/layout.tsx", "components/ThemeToggle.tsx"] \#(Self.loadedHead)"#
        )
    }

    @Test func aFailedGitStepKeepsTheReviewForARetry() async throws {
        try await loadReview()
        api.fail(
            "approve", with: APIError.gitFailed("git push failed", step: "push", stderr: "denied"))
        await #expect(throws: APIError.self) {
            try await store.publish(review, store.publishForm(for: review, session: nil))
        }
        #expect(store.hasPendingReview(session: review.sessionID))
        let progress = try #require(store.progress(session: review.sessionID))
        #expect(progress.steps.map(\.state) == [.done, .failed("denied"), .pending])
        #expect(progress.failure == .gitFailed("git push failed", step: "push", stderr: "denied"))
    }

    /// The daemon refuses to publish when HEAD or the changes are no longer the ones the
    /// review showed (audit SEC-02, SEC-06, BUG-83).
    @Test func approveSendsTheHeadAndFingerprintOfTheLoadedReview() async throws {
        try await loadReview()
        try await store.publish(review, store.publishForm(for: review, session: nil))
        #expect(
            api.calls.last
                == "approve \(review.sessionID) Dark mode contrast open_pr=true \(Self.loadedHead)")
    }

    static let loadedHead = "head=2222222222222222222222222222222222222222 fingerprint=fp-1"

    /// Approve goes out only for a review whose diff was read for it (audit M-5, SEC-16).
    @Test func approvingWaitsForTheReviewToLoad() async throws {
        try await store.load()
        #expect(!store.isReviewLoaded(review))
        await #expect(throws: APIError.self) {
            try await store.publish(review, store.publishForm(for: review, session: nil))
        }
        #expect(!api.calls.contains { $0.hasPrefix("approve") })
        #expect(store.progress(session: review.sessionID) == nil)

        try await store.loadDiff(for: review)
        #expect(store.isReviewLoaded(review))
        // A diff read for another review of the chat does not count for this one.
        var later = review
        later.id = "ap-review-2"
        #expect(!store.isReviewLoaded(later))
    }

    /// Every opening reads the diff again: a cached one would show old changes and send an
    /// old HEAD (audit BUG-83). The previous diff stays on screen while it reloads, and
    /// Approve waits for the new one.
    @Test func openingTheReviewAgainReadsAFreshDiff() async throws {
        try await loadReview()
        var changed = Fixture.diff
        changed.head = ReviewHead(commit: "3333", branch: "agent/dark-mode-1a2b3c")
        changed.fingerprint = "fp-2"
        let gate = AsyncStream<Void>.makeStream()
        api.set {
            $0.diff = changed
            $0.gates["diff"] = gate.stream
        }
        let reloading = Task { try await store.loadDiff(for: review) }
        try await waitFor { store.loadingDiffs.contains(review.sessionID) }
        #expect(store.diffs[review.sessionID] == Fixture.diff)
        #expect(!store.isReviewLoaded(review))

        gate.continuation.finish()
        #expect(try await reloading.value == changed)
        #expect(store.loadingDiffs.isEmpty)
        #expect(store.diffs[review.sessionID] == changed)
        try await store.publish(review, store.publishForm(for: review, session: nil))
        #expect(api.calls.last?.hasSuffix("head=3333 fingerprint=fp-2") == true)
    }

    /// A failed reload keeps the diff on screen, but Approve waits for one that loads.
    @Test func aFailedReloadKeepsTheDiffButNotApprove() async throws {
        try await loadReview()
        api.fail("diff")
        await #expect(throws: APIError.self) { try await store.loadDiff(for: review) }
        #expect(store.diffs[review.sessionID] == Fixture.diff)
        #expect(store.loadingDiffs.isEmpty)
        #expect(!store.isReviewLoaded(review))
    }

    /// A new or resolved review and a publish each make the loaded
    /// diff stale, so it is dropped.
    @Test func theDiffIsDroppedWhenTheReviewChanges() async throws {
        let id = review.sessionID
        try await loadReview()
        // The same review again (a replay) keeps it.
        store.apply(.approvalCreated(review))
        #expect(store.isReviewLoaded(review))
        var newer = review
        newer.id = "ap-review-2"
        store.apply(.approvalCreated(newer))
        #expect(store.diffs[id] == nil)
        #expect(!store.isReviewLoaded(newer))

        try await store.loadDiff(for: newer)
        store.apply(.approvalCreated(permission))
        #expect(store.isReviewLoaded(newer))
        store.apply(.approvalResolved(newer))
        #expect(store.diffs[id] == nil)

        store.apply(.approvalCreated(review))
        try await store.loadDiff(for: review)
        // Feedback leaves the review and its diff: a turn that changes the work replaces
        // the review, which drops the diff then (B56).
        try await store.feedback(review, text: "More tests")
        #expect(store.isReviewLoaded(review))
        store.apply(.approvalResolved(review))
        #expect(store.diffs[id] == nil)

        store.apply(.approvalCreated(review))
        try await store.loadDiff(for: review)
        try await store.publish(review, store.publishForm(for: review, session: nil))
        #expect(store.diffs[id] == nil)
        #expect(!store.isReviewLoaded(review))
    }

    /// A load that the review outlived does not bring the old diff back.
    @Test func aLoadForAReviewThatWentAwayIsDropped() async throws {
        try await store.load()
        let gate = AsyncStream<Void>.makeStream()
        api.set { $0.gates["diff"] = gate.stream }
        let loading = Task { try await store.loadDiff(for: review) }
        try await waitFor { store.loadingDiffs.contains(review.sessionID) }

        store.apply(.approvalResolved(review))
        #expect(store.loadingDiffs.isEmpty)
        gate.continuation.finish()
        _ = try await loading.value

        #expect(store.diffs[review.sessionID] == nil)
        #expect(!store.isReviewLoaded(review))
    }

    @Test func aRefusedApproveRunsNoStepAndKeepsTheReason() async throws {
        try await loadReview()
        let refusal = APIError.approveRefused("Work still runs.", reason: .backgroundRunning)
        api.fail("approve", with: refusal)
        await #expect(throws: refusal) {
            try await store.publish(review, store.publishForm(for: review, session: nil))
        }
        let progress = try #require(store.progress(session: review.sessionID))
        #expect(progress.steps.map(\.state) == [.pending, .pending, .pending])
        #expect(progress.failedStep == nil)
        #expect(progress.failure == refusal)
        #expect(!progress.isRunning)
        #expect(store.hasPendingReview(session: review.sessionID))
    }

    @Test func otherPublishErrorsMarkTheRunningStep() async throws {
        try await loadReview()
        api.fail("approve", with: CancellationError())
        await #expect(throws: CancellationError.self) {
            try await store.publish(review, store.publishForm(for: review, session: nil))
        }
        let progress = try #require(store.progress(session: review.sessionID))
        #expect(progress.failedStep?.kind == .commit)
        #expect(progress.failure == .transport(CancellationError().localizedDescription))
    }

    @Test func gitEventsMoveTheProgress() async throws {
        try await loadReview()
        let gate = AsyncStream<Void>.makeStream()
        api.set { $0.gates["approve"] = gate.stream }
        let task = Task {
            try await store.publish(review, store.publishForm(for: review, session: nil))
        }
        try await waitFor { store.progress(session: review.sessionID) != nil }
        let progress = try #require(store.progress(session: review.sessionID))
        #expect(progress.isRunning)
        #expect(store.busy == [review.id])
        #expect(progress.steps.map(\.state) == [.running, .pending, .pending])

        let id = review.sessionID
        store.apply(Fixture.event(EventType.gitCommitted, #"{"sha": "abc"}"#, session: id))
        #expect(progress.steps.map(\.state) == [.done, .running, .pending])
        store.apply(Fixture.event(EventType.prOpened, #"{"url": "u"}"#, session: id))
        #expect(progress.steps.map(\.state) == [.done, .done, .done])
        store.apply(
            Fixture.event(EventType.gitFailed, #"{"step": "push", "stderr": "x"}"#, session: id))
        #expect(progress.steps.map(\.state) == [.done, .failed("x"), .pending])
        store.apply(
            Fixture.event(EventType.gitPushed, #"{"remote": "origin", "branch": "b"}"#, session: id)
        )
        #expect(progress.steps.map(\.state) == [.done, .done, .running])
        store.apply(
            Fixture.event(EventType.sessionState, #"{"state": "idle", "error": null}"#, session: id)
        )
        store.apply(Fixture.event(EventType.gitPushed, #"{"branch": "b"}"#, session: "other"))
        store.apply(Fixture.event(EventType.gitPushed, #"{"branch": "b"}"#, session: nil))
        #expect(progress.steps.map(\.state) == [.done, .done, .running])

        gate.continuation.finish()
        _ = try await task.value
        #expect(progress.steps.map(\.state) == [.done, .done, .done])

        store.apply(.sessionDeleted(sessionID: id))
        #expect(store.progress(session: id) == nil)
    }

    @Test func sendsFeedback() async throws {
        try await store.load()
        let running = try await store.feedback(review, text: "Keep the old focus ring")
        #expect(running.state == .running)
        #expect(api.calls.last == "feedback \(review.sessionID) Keep the old focus ring")
        // The review stays pending: a turn that changes the work replaces it (B56).
        #expect(store.pending(repo: "todo-ui").map(\.id) == ["ap-perm", "ap-review"])
    }

    @Test func loadsDiffs() async throws {
        let diff = try await store.loadDiff(for: review)
        #expect(diff == Fixture.diff)
        #expect(store.diffs[review.sessionID] == Fixture.diff)
    }

    @Test func followsLiveEvents() async throws {
        store.apply(.approvalCreated(permission))
        store.apply(.approvalCreated(permission))
        #expect(store.pending.map(\.id) == ["ap-perm"])

        var expired = question
        expired.status = .expired
        store.apply(.approvalCreated(expired))
        #expect(store.pending.count == 1)

        store.apply(.approvalCreated(review))
        _ = try await store.loadDiff(for: review)
        store.apply(.approvalResolved(permission))
        #expect(store.pending.map(\.id) == ["ap-review"])

        store.apply(.sessionDeleted(sessionID: review.sessionID))
        #expect(store.pending.isEmpty)
        #expect(store.diffs.isEmpty)

        store.apply(.delta("ignored"))
        #expect(store.pending.isEmpty)
    }
}
