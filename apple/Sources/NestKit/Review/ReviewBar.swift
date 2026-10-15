import Foundation

/// The slim bar above a chat's composer while its review waits, in place of a card in the
/// transcript (B56): how many files and lines changed, and Review, which opens the changes
/// to approve.
public struct ReviewBar: Sendable, Hashable {
    public var approvalID: String
    public var files: Int
    public var additions: Int
    public var deletions: Int

    public init(approvalID: String, files: Int, additions: Int, deletions: Int) {
        self.approvalID = approvalID
        self.files = files
        self.additions = additions
        self.deletions = deletions
    }

    /// The bar for the session's pending review, the newest when there are several; nil
    /// while none waits.
    public static func pending(session: String, in approvals: [Approval]) -> ReviewBar? {
        approvals
            .filter { $0.sessionID == session && $0.kind == .review && $0.status == .pending }
            .max { $0.createdAt < $1.createdAt }?
            .reviewBar
    }

    /// "1 file changed", "3 files changed"; a review whose summary cannot be read still
    /// offers its changes.
    public var filesText: String {
        switch files {
        case 0: "Changes to review"
        case 1: "1 file changed"
        default: "\(files) files changed"
        }
    }
}

extension Approval {
    /// This review's bar, with zero counts when its summary cannot be read.
    public var reviewBar: ReviewBar {
        let review = self.review
        return ReviewBar(
            approvalID: id, files: review?.files ?? 0, additions: review?.additions ?? 0,
            deletions: review?.deletions ?? 0)
    }
}
