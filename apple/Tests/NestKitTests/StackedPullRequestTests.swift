import Foundation
import Testing

@testable import NestKit

/// The detail fixture with these fields added.
private func session(_ fields: String) -> Session {
    var json = Fixture.text("session_detail")
    json.removeLast(2)
    return Fixture.decode(Session.self, json: json + ", " + fields + "}")
}

private let openPR = """
    "pr": {"number": 12, "url": "https://github.com/me/r/pull/12", "title": "Add RSS",
     "state": "open", "checks": {"state": "pending", "passed": 0, "failed": 0, "pending": 1},
     "head_sha": "new", "base_branch": "feature-a",
     "auto_merge": {"method": "squash", "enabled_at": "2026-11-08T09:00:00Z"},
     "changed_at": "2026-11-08T09:00:00Z", "updated_at": "2026-11-08T09:00:00Z"}
    """

@Suite struct StackedPullRequestModelTests {
    @Test func sessionsCarryMergeWhenReadyTheirStackAndTheirGuide() {
        let chat = session(
            openPR + """
                , "merge_when_ready": {"method": "squash", "delete_branch": false},
                "stack": {"parent": "s-under", "parent_branch": "feature-a",
                 "restack": {"upstream": "abc", "onto": "refs/remotes/origin/main",
                  "fetch": "main", "base": "main", "rebased": null,
                  "error": "Rebasing onto main stopped on conflicts."}},
                "pr_guide": {"state": "ready", "head_sha": "old", "artifact_id": "a-guide",
                 "error": null, "comment_url": null, "written_at": "2026-11-08T09:00:00Z"}
                """)
        #expect(chat.mergeWhenReady == MergeWhenReady())
        #expect(chat.pr?.baseBranch == "feature-a")
        #expect(chat.pr?.autoMerge != nil)
        #expect(chat.stack?.parent == "s-under")
        #expect(chat.stack?.restack?.base == "main")
        #expect(chat.stack?.restack?.error == "Rebasing onto main stopped on conflicts.")
        #expect(chat.prGuide?.state == .ready)
        #expect(chat.prGuide?.artifactID == "a-guide")
        // A daemon before B149 sends none of them.
        let old = Fixture.sessionDetail
        #expect(old.mergeWhenReady == nil && old.stack == nil && old.prGuide == nil)
        #expect(session(#""pr_guide": {"state": "later"}"#).prGuide?.state == .unknown)
    }

    @Test func mergeWhenReadyIsOnWhileNestOrGitHubWaitsToMerge() throws {
        var chat = session(openPR)
        #expect(PRBadge.mergesWhenReady(chat))
        #expect(PRBadge.mergeWhenReadyDetail(chat) == "GitHub merges it when checks pass")
        chat.pr?.autoMerge = nil
        #expect(!PRBadge.mergesWhenReady(chat))
        #expect(PRBadge.mergeWhenReadyDetail(chat) == nil)
        chat.mergeWhenReady = MergeWhenReady()
        #expect(PRBadge.mergesWhenReady(chat))
        #expect(
            PRBadge.mergeWhenReadyDetail(chat)
                == "Nest merges it when checks pass, while Nest is running")
        #expect(Fixture.json(AutoMergeRequest(enabled: true)) == #"{"enabled":true}"#)
    }

    @Test func theRestackButtonFollowsWhatIsLeftToDo() {
        var chat = session(openPR)
        chat.prURL = "https://github.com/me/r/pull/12"
        let waiting = Restack(base: "main", rebased: nil, error: nil)
        let rebased = Restack(base: "main", rebased: "def456", error: nil)
        #expect(RestackAction(waiting, of: chat) == .rebaseAndPush)
        #expect(RestackAction(rebased, of: chat) == .push)
        chat.pr?.state = .merged
        #expect(RestackAction(rebased, of: chat) == .rebase)
        chat.prURL = nil
        chat.pr = nil
        #expect(RestackAction(waiting, of: chat) == .rebase)
        let titles = [RestackAction.push, .rebaseAndPush, .rebase].map(\.title)
        #expect(titles == ["Push", "Rebase and push", "Rebase"])
    }

    @Test func restackApprovalsSayWhereTheBranchWent() {
        let approval = Fixture.decode(
            Approval.self,
            json: """
                {"id": "ap-r", "session_id": "s1", "repo": "nest", "title": "Feed", "kind": "restack",
                 "status": "pending", "created_at": "2026-11-08T09:00:00Z",
                 "payload": {"branch": "feature-b", "base": "main", "rebased": true, "error": null,
                  "number": 14, "url": "https://github.com/me/r/pull/14"}}
                """)
        let request = try! #require(approval.restack)
        #expect(request.headline == "feature-b moved onto main")
        #expect(RestackAction(request) == .push)
        #expect(NeedsYouLine.of(approval).detail == "feature-b moved onto main")
        var before = request
        before.rebased = false
        #expect(before.headline == "Move feature-b onto main")
        #expect(RestackAction(before) == .rebaseAndPush)
        before.url = nil
        #expect(RestackAction(before) == .rebase)
    }

    @Test func aGuideForOlderCommitsOffersWriteAgain() throws {
        let pr = try #require(session(openPR).pr)
        func guide(_ state: ReviewGuideState, head: String? = "new", artifact: String? = "a-1")
            -> ReviewGuide
        {
            ReviewGuide(state: state, headSHA: head, artifactID: artifact, error: "No agent")
        }
        #expect(ReviewGuideRow(nil, pr: pr) == .write)
        #expect(ReviewGuideRow(guide(.writing), pr: pr) == .writing)
        #expect(ReviewGuideRow(guide(.failed), pr: pr) == .failed("No agent"))
        #expect(
            ReviewGuideRow(guide(.ready), pr: pr)
                == .ready(artifact: "a-1", commentURL: nil, outdated: false))
        #expect(
            ReviewGuideRow(guide(.ready, head: "old"), pr: pr)
                == .ready(artifact: "a-1", commentURL: nil, outdated: true))
        #expect(ReviewGuideRow(guide(.ready, artifact: nil), pr: pr) == .write)
    }
}

@MainActor
@Suite struct RestackStoreTests {
    let api = FakeAPI()
    let approvals: ApprovalsStore

    init() {
        approvals = ApprovalsStore(api: api)
    }

    @Test func aFailedRestackKeepsItsCardInNeedsYou() async throws {
        var card = Fixture.approval("ap-perm")
        card.id = "ap-restack"
        card.sessionID = "s1"
        card.kind = .restack
        api.set {
            $0.sessions = [Fixture.session("s1")]
            $0.approvals = [card]
        }
        try await approvals.load()

        api.fail("restack", with: APIError.conflict("Rebasing onto main stopped on conflicts."))
        await #expect(throws: APIError.self) { try await approvals.restack(card) }
        #expect(approvals.pending.map(\.id) == ["ap-restack"])
        #expect(approvals.busy.isEmpty)

        api.set { $0.failures = [:] }
        try await approvals.restack(card)
        #expect(approvals.pending.isEmpty)
        #expect(api.calls.filter { $0.hasPrefix("restack") } == ["restack s1", "restack s1"])
    }
}
