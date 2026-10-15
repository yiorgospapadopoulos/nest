import NestKit
import SwiftUI

/// Where Approve goes: "Pushes to <branch>" or "Commits to <branch>, not pushed".
struct PublishTarget: View {
    let diff: SessionDiff
    /// Approve pushes, to open a pull request (B56).
    let pushes: Bool

    var body: some View {
        if let target = diff.target(pushes: pushes) {
            Label(target, systemImage: pushes ? Icon.pullRequest : Icon.branch)
                .labelStyle(TightLabelStyle())
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t2)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}
