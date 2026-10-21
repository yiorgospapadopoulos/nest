import Foundation
import Testing

@testable import NestKit

/// A pull request as the daemon stores it, with the checks state and items given.
private func pr(
    state: String = "open", checks: String = "failure",
    items: String = """
    [{"name": "lint", "state": "success", "url": null},
     {"name": "test", "state": "failure", "url": "https://github.com/me/r/actions/1"},
     {"name": "build", "state": "failure", "url": null},
     {"name": "docs", "state": "skipped", "url": null}]
    """
) -> PullRequest {
    Fixture.decode(PullRequest.self, json: prJSON(state: state, checks: checks, items: items))
}

private func prJSON(state: String = "open", checks: String = "failure", items: String = "[]")
    -> String
{
    """
    {"number": 12, "url": "https://github.com/me/r/pull/12", "title": "Add RSS",
     "state": "\(state)",
     "checks": {"state": "\(checks)", "passed": 2, "failed": 2, "pending": 0, "items": \(items)},
     "mergeable": null, "merge_state": "blocked", "review_decision": null,
     "head_sha": "abc123", "created_at": "2026-10-06T08:00:00Z",
     "changed_at": "2026-10-06T09:00:00Z", "updated_at": "2026-10-06T09:05:00Z"}
    """
}

@Suite struct PullRequestModelTests {
    @Test func decodesTheStoredStatus() {
        let status = pr()
        #expect(status.number == 12)
        #expect(status.state == .open)
        #expect(status.checks.state == .failure)
        #expect(status.checks.items.count == 4)
        #expect(status.mergeable == nil)
        #expect(status.mergeState == "blocked")
        #expect(status.headSHA == "abc123")
        #expect(status.failingChecks == ["test", "build"])
        #expect(pr(checks: "none").checks.state == .noChecks)
        #expect(pr(state: "draft", checks: "weird").state == .unknown)
        #expect(pr(checks: "weird").checks.state == .unknown)
    }

    @Test func sessionsCarryTheirPullRequest() {
        var json = Fixture.text("session_detail")
        json.removeLast(2)
        json += #", "pr": \#(prJSON())}"#
        let session = Fixture.decode(Session.self, json: json)
        #expect(session.pr?.number == 12)
        #expect(Fixture.sessionDetail.pr == nil)
    }

    @Test func theDotFollowsTheChecks() {
        #expect(PRBadge.dot(of: pr(checks: "pending")) == (.waiting, false))
        #expect(PRBadge.dot(of: pr(checks: "success")) == (.review, false))
        #expect(PRBadge.dot(of: pr(checks: "failure")) == (.failed, false))
        #expect(PRBadge.dot(of: pr(checks: "none")) == (.done, true))
        #expect(PRBadge.dot(of: pr(checks: "weird")) == (.done, true))
        #expect(PRBadge.dot(of: pr(state: "merged", checks: "success")) == (.done, false))
        #expect(PRBadge.dot(of: pr(state: "closed")) == (.done, false))
    }

    @Test func summariesAndLabels() {
        let all = Fixture.decode(
            PRChecks.self, json: #"{"state": "failure", "passed": 3, "failed": 1, "pending": 2}"#)
        #expect(all.items.isEmpty)
        #expect(PRBadge.checksSummary(all) == "1 failed, 2 running, 3 passed")
        let none = Fixture.decode(
            PRChecks.self, json: #"{"state": "none", "passed": 0, "failed": 0, "pending": 0}"#)
        #expect(PRBadge.checksSummary(none) == "No checks")
        #expect(
            [PRState.open, .merged, .closed, .unknown].map(PRBadge.stateLabel) == [
                "Open", "Merged", "Closed", "Unknown",
            ])
        #expect(
            MergeMethod.allCases.map(\.label) == [
                "Squash and merge", "Merge commit", "Rebase and merge",
            ])
    }

    @Test func mergeApprovalsCarryTheProposal() {
        var approval = Fixture.approval("ap-perm")
        #expect(approval.merge == nil)
        approval.kind = .merge
        approval.payload = Fixture.decode(
            JSONValue.self,
            json: """
                {"number": 12, "title": "Add RSS", "url": "https://github.com/me/r/pull/12",
                 "head_sha": "abc123",
                 "checks": {"state": "success", "passed": 3, "failed": 0, "pending": 0}}
                """)
        #expect(approval.merge?.number == 12)
        #expect(approval.merge?.headSHA == "abc123")
        #expect(approval.merge?.checks.state == .success)
        #expect(approval.permission == nil)
        #expect(Fixture.decode(Approval.self, json: Fixture.json(approval)).kind == .merge)
    }

    @Test func mergeRequestsDefaultToSquashAndKeepTheBranch() {
        #expect(
            Fixture.json(MergeRequest()) == #"{"delete_branch":false,"method":"squash"}"#)
        #expect(
            Fixture.json(MergeRequest(method: .rebase, deleteBranch: true))
                == #"{"delete_branch":true,"method":"rebase"}"#)
    }
}

@MainActor
@Suite struct PullRequestStoreTests {
    let api = FakeAPI()
    let approvals: ApprovalsStore
    let sessions: SessionsStore

    init() {
        approvals = ApprovalsStore(api: api)
        sessions = SessionsStore(api: api, approvals: approvals)
    }

    func session(
        _ id: String, state: SessionState = .idle, pr status: PullRequest? = pr(),
        archived: Bool = false
    ) -> Session {
        var session = Fixture.session(id, state: state, archived: archived)
        session.pr = status
        return session
    }

    @Test func statusEventsUpdateTheSession() async throws {
        api.set { $0.sessions = [session("s1", pr: nil)] }
        try await sessions.load()
        sessions.apply(Fixture.event("session.pr", #"{"pr": \#(prJSON(checks: "pending"))}"#))
        #expect(sessions.session("s1")?.pr?.checks.state == .pending)
        sessions.apply(
            Fixture.event("session.pr", #"{"pr": \#(prJSON())}"#, session: nil))
        sessions.apply(
            Fixture.event("session.pr", #"{"pr": \#(prJSON())}"#, session: "gone"))
        #expect(sessions.session("s1")?.pr?.checks.state == .pending)
        #expect(sessions.session("gone") == nil)
        #expect(Fixture.event("session.pr", #"{"pr": null}"#).body == .other)
    }

    @Test func failedChecksWaitForTheUserOnlyWhenTheyCanAct() async throws {
        var review = Fixture.approval("ap-review")
        review.sessionID = "review"
        api.set {
            $0.sessions = [
                session("failed"),
                session("running", state: .running),
                session("waiting", state: .waiting),
                session("closed", state: .closed),
                session("archived", archived: true),
                session("review"),
                session("green", pr: pr(checks: "success")),
                session("merged", pr: pr(state: "merged")),
                session("none", pr: nil),
                session("interrupted", state: .interrupted),
            ]
            $0.approvals = [review]
        }
        try await sessions.load()
        try await approvals.load()
        #expect(Set(sessions.checksFailed(in: "cv-page").map(\.id)) == ["failed", "interrupted"])
        #expect(sessions.checksFailed(in: "llm-hunter").isEmpty)
    }

    @Test func attentionCountsApprovalsFailedChecksAndStuckChats() async throws {
        var other = Fixture.approval("ap-perm")
        other.id = "ap-other"
        other.repo = "llm-hunter"
        api.set {
            $0.sessions = [
                session("failed"), StuckFixture.session("stuck"),
                session("green", pr: pr(checks: "success")),
            ]
            $0.approvals = Array(Fixture.approvals.prefix(2)) + [other]
        }
        try await sessions.load()
        try await approvals.load()

        #expect(sessions.attention(of: "cv-page") == 3)
        #expect(sessions.attention(of: "llm-hunter") == 1)
        #expect(sessions.attention(of: "novel-engine") == 1)
        #expect(sessions.attention(of: "none") == 0)
        // The Dock badge counts every project.
        #expect(sessions.attention() == 5)
    }

    /// The daemon reads the failing checks' logs with its own login and sends them (IMP-08).
    @Test func sendToAgentAsksTheDaemonForTheFailingChecks() async throws {
        api.set {
            $0.sessions = [
                session("s1"), session("none", pr: nil), session("green", pr: pr(items: "[]")),
            ]
        }
        try await sessions.load()
        #expect(try await sessions.sendChecksFailure("s1"))
        #expect(api.calls.last == "ciFeedback s1")
        #expect(try await sessions.sendChecksFailure("none") == false)
        #expect(try await sessions.sendChecksFailure("green") == false)
        #expect(api.calls.count { $0.hasPrefix("ciFeedback") } == 1)
        #expect(!api.calls.contains { $0.hasPrefix("sendMessage") })

        api.fail("ciFeedback", with: APIError.badGateway("gh failed"))
        await #expect(throws: APIError.badGateway("gh failed")) {
            try await sessions.sendChecksFailure("s1")
        }
    }

    @Test func refreshReadsThePullRequestAgain() async throws {
        api.set {
            $0.sessions = [session("s1", pr: pr(checks: "pending"))]
            $0.githubPRs["s1"] = pr(checks: "success")
        }
        try await sessions.load()
        try await sessions.refreshPR("s1")
        #expect(sessions.session("s1")?.pr?.checks.state == .success)
        #expect(sessions.refreshingPR.isEmpty)

        api.fail("refreshPR")
        await #expect(throws: APIError.self) { try await sessions.refreshPR("s1") }
        #expect(sessions.refreshingPR.isEmpty)
        #expect(sessions.session("s1")?.pr?.checks.state == .success)
    }

    @Test func mergingClosesTheChatAndClearsTheApproval() async throws {
        var merge = Fixture.approval("ap-perm")
        merge.id = "ap-merge"
        merge.sessionID = "s1"
        merge.kind = .merge
        api.set {
            $0.sessions = [session("s1", pr: pr(checks: "success"))]
            $0.approvals = [merge]
        }
        try await approvals.load()

        api.fail("merge", with: APIError.gitFailed("merge failed", step: "merge", stderr: "no"))
        await #expect(throws: APIError.self) { try await approvals.merge(merge, method: .rebase) }
        #expect(approvals.pending.map(\.id) == ["ap-merge"])
        #expect(approvals.busy.isEmpty)

        api.set { $0.failures = [:] }
        let closed = try await approvals.merge(merge)
        #expect(closed.state == .closed)
        #expect(closed.pr?.state == .merged)
        #expect(approvals.pending.isEmpty)
        #expect(
            api.calls.filter { $0.hasPrefix("merge") } == ["merge s1 rebase", "merge s1 squash"])
    }

    @Test func theBranchIsDeletedOnlyWhenAskedAtTheMerge() async throws {
        var merge = Fixture.approval("ap-perm")
        merge.id = "ap-merge"
        merge.sessionID = "s1"
        merge.kind = .merge
        api.set {
            $0.sessions = [session("s1", pr: pr(checks: "success"))]
            $0.approvals = [merge]
        }
        try await approvals.load()

        try await approvals.merge(merge, method: .rebase, deleteBranch: true)

        #expect(api.calls.filter { $0.hasPrefix("merge") } == ["merge s1 rebase delete-branch"])
    }
}
