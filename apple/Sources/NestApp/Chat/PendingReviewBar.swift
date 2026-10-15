import NestKit
import SwiftUI

/// One quiet line just above the composer while the chat's review waits (B56), in place of
/// a card in the transcript: "3 files changed +48 -19" and Review, which opens the changes
/// to approve. Nothing while no review waits.
struct PendingReviewBar: View {
    let chat: String
    @Environment(Shell.self) private var shell

    var body: some View {
        if let bar = ReviewBar.pending(session: chat, in: shell.approvals.pending) {
            let shape = RoundedRectangle.rounded(Radius.card)
            HStack(spacing: 8) {
                Image(systemName: Icon.diff)
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(StatusTone.review.color)
                Text(bar.filesText)
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t2)
                    .lineLimit(1)
                HStack(spacing: 4) {
                    Text("+\(bar.additions)").foregroundStyle(StatusTone.review.color)
                    Text("-\(bar.deletions)").foregroundStyle(StatusTone.failed.color)
                }
                .font(.ui(TypeSize.meta))
                .monospacedDigit()
                Spacer(minLength: 4)
                Button("Review") { shell.show(.diff(bar.approvalID)) }
                    .buttonStyle(.nest(.soft, height: 22))
                    .help("See the changes and approve them")
            }
            .padding(.leading, 12)
            .padding(.trailing, 4)
            .frame(height: 30)
            .background(shape.strokeBorder(Palette.divider))
            .padding(.horizontal, 12)
            .padding(.bottom, 6)
            .accessibilityElement(children: .contain)
            .accessibilityLabel(
                "\(bar.filesText), \(bar.additions) added, \(bar.deletions) removed")
        }
    }
}
