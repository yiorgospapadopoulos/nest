import Foundation

/// What needs the user, in the one line the right panel's Needs you rows show under the
/// chat's name (B77): its kind and a short detail; the full item opens below the row.
public struct NeedsYouLine: Sendable, Hashable {
    public var kind: String
    public var detail: String?

    public init(kind: String, detail: String? = nil) {
        self.kind = kind
        self.detail = detail
    }

    public static func of(_ approval: Approval) -> NeedsYouLine {
        switch approval.kind {
        case .question:
            NeedsYouLine(kind: "Question", detail: approval.question?.questions.first?.question)
        case .review:
            NeedsYouLine(
                kind: "Ready for review",
                detail: approval.review.map {
                    "+\($0.additions) -\($0.deletions) in \($0.files) file\($0.files == 1 ? "" : "s")"
                })
        case .plan:
            NeedsYouLine(kind: "Plan", detail: approval.plan.flatMap { firstLine($0.plan) })
        case .merge:
            NeedsYouLine(
                kind: "Ready to merge", detail: approval.merge.map { "#\($0.number) \($0.title)" })
        case .permission, .unknown:
            NeedsYouLine(
                kind: "Permission",
                detail: approval.permission.map {
                    "\($0.tool) \(ToolSummary.argument(tool: $0.tool, input: $0.input))"
                })
        }
    }

    /// A chat whose pull request failed its checks, naming them.
    public static func checksFailed(_ session: Session) -> NeedsYouLine {
        let failing = session.pr?.failingChecks ?? []
        return NeedsYouLine(
            kind: "Checks failed",
            detail: failing.isEmpty ? nil : failing.joined(separator: ", "))
    }

    /// A chat that looks stuck, with the reason.
    public static func stuck(_ session: Session) -> NeedsYouLine {
        NeedsYouLine(kind: "Stuck", detail: session.stuck?.reason.label)
    }

    /// A plan's first line with text, without its Markdown heading marks.
    private static func firstLine(_ markdown: String) -> String? {
        markdown.split(whereSeparator: \.isNewline)
            .map { $0.drop { $0 == "#" }.trimmingCharacters(in: .whitespaces) }
            .first { !$0.isEmpty }
    }
}

extension Goals {
    /// "2 of 4" done, or "No plan yet" without tasks.
    public var progressLabel: String {
        tasks.isEmpty ? "No plan yet" : "\(completed) of \(tasks.count)"
    }
}
