import Foundation
import Testing

@testable import NestKit

/// B77: the right panel's one-line summaries of what needs the user, and a goal's
/// progress line.
@Suite struct NeedsYouLineTests {
    func approval(_ kind: ApprovalKind, _ json: String) -> Approval {
        var approval = Fixture.approval("ap-perm")
        approval.kind = kind
        approval.payload = Fixture.decode(JSONValue.self, json: json)
        return approval
    }

    @Test func approvalsReadAsTheirKindAndOneShortDetail() {
        #expect(
            NeedsYouLine.of(Fixture.approval("ap-perm"))
                == NeedsYouLine(kind: "Permission", detail: "Bash npm install zod"))
        #expect(
            NeedsYouLine.of(Fixture.approval("ap-question"))
                == NeedsYouLine(kind: "Question", detail: "Store branches as a DAG or a tree?"))
        #expect(
            NeedsYouLine.of(Fixture.approval("ap-review"))
                == NeedsYouLine(kind: "Ready for review", detail: "+48 -19 in 3 files"))
        #expect(
            NeedsYouLine.of(
                approval(.review, #"{"files": 1, "additions": 2, "deletions": 0, "paths": []}"#)
            )
            .detail == "+2 -0 in 1 file")
        #expect(
            NeedsYouLine.of(approval(.plan, "{\"plan\": \"\\n## Add a search page\\nThen more\"}"))
                == NeedsYouLine(kind: "Plan", detail: "Add a search page"))
        #expect(
            NeedsYouLine.of(
                approval(
                    .merge,
                    #"{"number": 12, "title": "Add RSS", "url": "u", "checks": {"state": "success", "passed": 1, "failed": 0, "pending": 0, "items": []}}"#
                )) == NeedsYouLine(kind: "Ready to merge", detail: "#12 Add RSS"))
    }

    @Test func aPayloadItCannotReadLeavesTheDetailOut() {
        #expect(NeedsYouLine.of(approval(.permission, "{}")) == NeedsYouLine(kind: "Permission"))
        #expect(NeedsYouLine.of(approval(.unknown, "{}")) == NeedsYouLine(kind: "Permission"))
        #expect(NeedsYouLine.of(approval(.question, #"{"questions": []}"#)).detail == nil)
        #expect(NeedsYouLine.of(approval(.review, "{}")).detail == nil)
        #expect(NeedsYouLine.of(approval(.plan, #"{"plan": "  \n "}"#)).detail == nil)
        #expect(NeedsYouLine.of(approval(.merge, "{}")).detail == nil)
    }

    @Test func failedChecksAndStuckChatsReadTheirOwnLine() {
        var session = Fixture.session("s")
        #expect(NeedsYouLine.checksFailed(session) == NeedsYouLine(kind: "Checks failed"))
        session.pr = Fixture.decode(
            PullRequest.self,
            json: """
                {"number": 12, "url": "u", "title": "Add RSS", "state": "open",
                 "checks": {"state": "failure", "passed": 0, "failed": 2, "pending": 0,
                   "items": [{"name": "lint", "state": "failure", "url": null},
                             {"name": "test", "state": "failure", "url": null}]},
                 "mergeable": null, "merge_state": "blocked", "review_decision": null,
                 "head_sha": "abc", "created_at": "2026-10-06T08:00:00Z",
                 "changed_at": "2026-10-06T09:00:00Z", "updated_at": "2026-10-06T09:05:00Z"}
                """)
        #expect(NeedsYouLine.checksFailed(session).detail == "lint, test")

        #expect(NeedsYouLine.stuck(session) == NeedsYouLine(kind: "Stuck"))
        session.stuck = StuckFlag(
            reason: .silent, since: Date(timeIntervalSince1970: 0), details: "Quiet")
        #expect(NeedsYouLine.stuck(session) == NeedsYouLine(kind: "Stuck", detail: "No new output"))
    }

    @Test func goalsReadTheirProgress() {
        func task(_ status: TaskStatus) -> TrackedTask {
            TrackedTask(
                id: "\(status)", subject: "T", description: nil, activeForm: nil, status: status)
        }
        let none = Goals(tasks: [])
        #expect(none.progressLabel == "No plan yet")
        let working = Goals(tasks: [task(.completed), task(.inProgress), task(.pending)])
        #expect(working.progressLabel == "1 of 3")
        let done = Goals(tasks: [task(.completed), task(.completed)])
        #expect(done.progressLabel == "2 of 2")
    }
}
