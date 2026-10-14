import Foundation
import Testing

@testable import NestKit

/// A REST answer reflects the daemon before the live events that arrive while it is on
/// its way; those events apply again on top of it (PL-06).
@MainActor
@Suite struct SnapshotOrderTests {
    let api = FakeAPI()
    let approvals: ApprovalsStore
    let sessions: SessionsStore
    let activity: ActivityStore

    init() {
        approvals = ApprovalsStore(api: api)
        sessions = SessionsStore(api: api, approvals: approvals)
        activity = ActivityStore(api: api)
    }

    /// Holds the named call at its gate until the returned closure runs.
    func hold(_ gate: String) -> () -> Void {
        let (stream, open) = AsyncStream<Void>.makeStream()
        api.set { $0.gates[gate] = stream }
        return { open.finish() }
    }

    static func state(_ state: String, session: String = "s1", id: Int = 9) -> Event {
        Fixture.event(
            EventType.sessionState, #"{"state": "\#(state)", "error": null}"#, id: id,
            session: session, ts: "2026-10-06T10:00:00Z")
    }

    @Test func aSessionsReloadKeepsWhatHappenedMeanwhile() async throws {
        api.set {
            $0.sessions = [
                Fixture.session("s1", state: .running), Fixture.session("gone"),
            ]
        }
        let release = hold("sessions")
        let loading = Task { try await sessions.load() }
        try await waitFor { api.calls.count == 1 }

        sessions.apply(Self.state("idle"))
        sessions.apply(Fixture.event(EventType.sessionDeleted, #"{"session_id": "gone"}"#))
        let born = Fixture.session("born", state: .starting)
        sessions.apply(
            Fixture.event(
                EventType.sessionCreated, #"{"session": \#(Fixture.json(born))}"#,
                session: "born"))
        release()
        try await loading.value

        #expect(sessions.session("s1")?.state == .idle)
        #expect(sessions.session("gone") == nil)
        #expect(sessions.session("born")?.state == .starting)

        // Events after the load are not applied again by the next one.
        api.set { $0.gates = [:] }
        try await sessions.load()
        #expect(sessions.session("s1")?.state == .running)
    }

    @Test func aFailedReloadStopsRecording() async throws {
        api.fail("sessions")
        await #expect(throws: APIError.self) { try await sessions.load() }
        api.set {
            $0.failures = [:]
            $0.sessions = [Fixture.session("s1", state: .running)]
        }
        sessions.apply(Self.state("idle"))
        try await sessions.load()
        #expect(sessions.session("s1")?.state == .running)
    }

    @Test func anActionsAnswerDoesNotUndoNewerEvents() async throws {
        let review = Fixture.approval("ap-review")
        let id = review.sessionID
        api.set { $0.sessions = [Fixture.session(id)] }
        try await sessions.load()
        approvals.apply(.approvalCreated(review))
        try await approvals.loadDiff(for: review)
        let release = hold("approve")
        let publishing = Task {
            try await sessions.publish(
                review, approvals.publishForm(for: review, session: sessions.session(id)))
        }
        try await waitFor { approvals.busy.contains(review.id) }

        sessions.apply(Self.state("closed", session: id))
        release()
        let answered = try await publishing.value

        #expect(answered.state == .closed)
        #expect(answered.prURL == "https://example.com/pr/1")
        #expect(sessions.session(id)?.state == .closed)
    }

    @Test func aChatDeletedWhileAnActionRunsStaysDeleted() async throws {
        let review = Fixture.approval("ap-review")
        let id = review.sessionID
        api.set { $0.sessions = [Fixture.session(id)] }
        try await sessions.load()
        approvals.apply(.approvalCreated(review))
        try await approvals.loadDiff(for: review)
        let release = hold("approve")
        let publishing = Task {
            try await sessions.publish(
                review, approvals.publishForm(for: review, session: sessions.session(id)))
        }
        try await waitFor { approvals.busy.contains(review.id) }

        sessions.apply(Fixture.event(EventType.sessionDeleted, #"{"session_id": "\#(id)"}"#))
        release()

        #expect(try await publishing.value.prURL == "https://example.com/pr/1")
        #expect(sessions.session(id) == nil)
    }

    @Test func anActivityReloadKeepsWhatHappenedMeanwhile() async throws {
        let detail = Fixture.sessionDetail
        api.set { $0.details[detail.id] = detail }
        let release = hold("session")
        let loading = Task { try await activity.load(session: detail.id) }
        try await waitFor { api.calls.count == 1 }

        let queued = QueuedMessage(
            id: "q1", text: "next", createdAt: Date(timeIntervalSince1970: 0))
        activity.apply(
            Fixture.event(
                EventType.sessionQueued, #"{"queued": [\#(Fixture.json(queued))]}"#, id: nil,
                session: detail.id))
        activity.apply(
            Fixture.event(EventType.sessionTasks, #"{"tasks": []}"#, session: detail.id))
        release()
        try await loading.value

        #expect(activity.queued(session: detail.id).map(\.id) == ["q1"])
        #expect(activity.goals(session: detail.id).tasks.isEmpty)
        #expect(!activity.agents(session: detail.id).isEmpty)
    }

    @Test func anApprovalCreatedDuringAReloadStays() async throws {
        let permission = Fixture.approval("ap-perm")
        let review = Fixture.approval("ap-review")
        api.set { $0.approvals = [permission] }
        let release = hold("approvals")
        let loading = Task { try await approvals.load() }
        try await waitFor { api.calls.count == 1 }

        approvals.apply(
            Fixture.event(
                EventType.approvalCreated, #"{"approval": \#(Fixture.json(review))}"#,
                session: review.sessionID))
        release()
        try await loading.value

        #expect(approvals.pending.map(\.id) == ["ap-perm", "ap-review"])
    }
}
