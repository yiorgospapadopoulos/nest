import Foundation
import Testing

@testable import NestKit

/// The bar above a chat's composer while its review waits, in place of a card in the
/// transcript (B56).
@Suite struct ReviewBarTests {
    var review: Approval { Fixture.approval("ap-review") }

    func review(_ id: String, files: Int, created: TimeInterval) -> Approval {
        var approval = review
        approval.id = id
        approval.payload = .object([
            "files": .number(Double(files)), "additions": .number(2), "deletions": .number(1),
            "paths": .array([]),
        ])
        approval.createdAt = Date(timeIntervalSince1970: created)
        return approval
    }

    @Test func showsTheSessionsPendingReview() throws {
        let bar = try #require(ReviewBar.pending(session: review.sessionID, in: Fixture.approvals))
        #expect(
            bar == ReviewBar(approvalID: "ap-review", files: 3, additions: 48, deletions: 19))
        #expect(bar.filesText == "3 files changed")
    }

    @Test func nothingWithoutAPendingReviewForTheSession() {
        let permission = Fixture.approval("ap-perm")
        // Another chat's review, or only a permission prompt, shows no bar.
        #expect(ReviewBar.pending(session: "other", in: Fixture.approvals) == nil)
        #expect(ReviewBar.pending(session: permission.sessionID, in: [permission]) == nil)
        var resolved = review
        resolved.status = .resolved
        #expect(ReviewBar.pending(session: review.sessionID, in: [resolved]) == nil)
    }

    @Test func theNewestReviewWins() {
        let older = review("old", files: 1, created: 10)
        let newer = review("new", files: 2, created: 20)
        #expect(
            ReviewBar.pending(session: review.sessionID, in: [newer, older])?.approvalID == "new")
        #expect(
            ReviewBar.pending(session: review.sessionID, in: [older, newer])?.approvalID == "new")
    }

    @Test func countsFilesInWords() {
        #expect(review("a", files: 1, created: 0).reviewBar.filesText == "1 file changed")
        #expect(review("a", files: 12, created: 0).reviewBar.filesText == "12 files changed")
        // A payload it cannot read still offers the review.
        var unreadable = review
        unreadable.payload = .object([:])
        #expect(
            unreadable.reviewBar
                == ReviewBar(approvalID: "ap-review", files: 0, additions: 0, deletions: 0))
        #expect(unreadable.reviewBar.filesText == "Changes to review")
    }
}
