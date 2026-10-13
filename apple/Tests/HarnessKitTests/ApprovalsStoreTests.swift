import Foundation
import Testing

@testable import HarnessKit

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
        store.answerFreely("  A graph of scenes ", for: question, question: questions[0])
        #expect(store.freeAnswer(for: question, question: questions[0]) == "  A graph of scenes ")
        #expect(store.answer(for: question, question: questions[0]) == ["A graph of scenes"])
        #expect(store.selection(for: question, question: questions[0]) == ["Tree"])
        store.answerFreely("   ", for: question, question: questions[0])
        #expect(store.answer(for: question, question: questions[0]) == ["Tree"])
    }

    @Test func answersNeedSomethingForEveryQuestion() throws {
        let questions = try #require(question.question).questions
        #expect(store.canSubmitAnswers(question))
        store.select("JSON", for: question, question: questions[1])
        store.select("Ink", for: question, question: questions[1])
        #expect(!store.canSubmitAnswers(question))
        store.answerFreely("YAML", for: question, question: questions[1])
        #expect(store.canSubmitAnswers(question))
        #expect(!store.canSubmitAnswers(permission))
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

    @Test func aFreeAnswerCanComeFirst() throws {
        let questions = try #require(question.question).questions
        store.answerFreely("Neither", for: question, question: questions[0])
        #expect(store.answer(for: question, question: questions[0]) == ["Neither"])
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
        api.fail("resolveApproval", with: APIError.conflict("already resolved", files: []))
        await #expect(throws: APIError.self) { try await store.allow(permission) }
        #expect(store.pending.count == 3)
    }

    @Test func publishesAWorktreeReviewWithThePullRequest() async throws {
        try await store.load()
        let form = store.publishForm(for: review, session: nil)
        #expect(form.commitMessage == "Dark mode contrast")
        #expect(store.progress(session: review.sessionID) == nil)

        let session = try await store.publish(review, form)

        #expect(session.prURL == "https://example.com/pr/1")
        #expect(api.calls.last == "approve \(review.sessionID) Dark mode contrast open_pr=true")
        #expect(!store.hasPendingReview(session: review.sessionID))
        let progress = try #require(store.progress(session: review.sessionID))
        #expect(progress.steps.map(\.state) == [.done, .done, .done])
        #expect(progress.result == session)
        #expect(!progress.isRunning)
        #expect(store.busy.isEmpty)
    }

    @Test func publishesAnInPlaceReviewWithItsFilesAndNoPullRequest() async throws {
        try await store.load()
        var session = Fixture.session(review.sessionID)
        session.mode = .inPlace
        var form = store.publishForm(for: review, session: session)
        form.commitMessage = "Raise contrast"
        try await store.publish(review, form)
        #expect(
            api.calls.last
                == #"approve \#(review.sessionID) Raise contrast open_pr=false files=["app/globals.css", "app/layout.tsx", "components/ThemeToggle.tsx"]"#
        )
    }

    @Test func aFailedGitStepKeepsTheReviewForARetry() async throws {
        try await store.load()
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

    /// The daemon refuses to publish when HEAD is no longer the one the review showed
    /// (audit SEC-02, SEC-06).
    @Test func approveSendsTheHeadTheReviewShowed() async throws {
        try await store.load()
        try await store.loadDiff(session: review.sessionID)
        try await store.publish(review, store.publishForm(for: review, session: nil))
        #expect(
            api.calls.last
                == "approve \(review.sessionID) Dark mode contrast open_pr=true head=2222222222222222222222222222222222222222"
        )
    }

    @Test func aRefusedApproveRunsNoStepAndKeepsTheReason() async throws {
        try await store.load()
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
        try await store.load()
        api.fail("approve", with: CancellationError())
        await #expect(throws: CancellationError.self) {
            try await store.publish(review, store.publishForm(for: review, session: nil))
        }
        let progress = try #require(store.progress(session: review.sessionID))
        #expect(progress.failedStep?.kind == .commit)
        #expect(progress.failure == .transport(CancellationError().localizedDescription))
    }

    @Test func gitEventsMoveTheProgress() async throws {
        try await store.load()
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

    @Test func acknowledgedViolationsCarryIntoTheFormUntilResolved() async throws {
        try await store.load()
        var session = Fixture.session(review.sessionID)
        session.gitViolation = true
        #expect(!store.publishForm(for: review, session: session).canSubmit)
        store.acknowledgedViolations.insert(review.id)
        let form = store.publishForm(for: review, session: session)
        #expect(form.canSubmit)
        #expect(form.request.acknowledgeViolation)
        try await store.reject(review)
        #expect(store.acknowledgedViolations.isEmpty)
    }

    @Test func rejectsAndSendsFeedback() async throws {
        try await store.load()
        let closed = try await store.reject(review)
        #expect(closed.state == .closed)
        store.apply(.approvalCreated(review))
        let running = try await store.feedback(review, text: "Keep the old focus ring")
        #expect(running.state == .running)
        #expect(
            api.calls.suffix(2) == [
                "reject \(review.sessionID)",
                "feedback \(review.sessionID) Keep the old focus ring",
            ])
        #expect(store.pending(repo: "todo-ui").map(\.id) == ["ap-perm"])
    }

    @Test func loadsDiffs() async throws {
        let diff = try await store.loadDiff(session: review.sessionID)
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
        _ = try await store.loadDiff(session: review.sessionID)
        store.apply(.approvalResolved(permission))
        #expect(store.pending.map(\.id) == ["ap-review"])

        store.apply(.sessionDeleted(sessionID: review.sessionID))
        #expect(store.pending.isEmpty)
        #expect(store.diffs.isEmpty)

        store.apply(.delta("ignored"))
        #expect(store.pending.isEmpty)
    }
}
