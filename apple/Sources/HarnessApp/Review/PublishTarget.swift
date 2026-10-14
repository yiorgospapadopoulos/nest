import HarnessKit
import SwiftUI

/// Where Approve publishes: "Pushes to <branch>", and any commits on the branch that
/// harness did not make, with a warning.
struct PublishTarget: View {
    let diff: SessionDiff

    var body: some View {
        if diff.pushTarget != nil || !diff.commits.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                if let target = diff.pushTarget {
                    Label(target, systemImage: Icon.pullRequest)
                        .font(.ui(TypeSize.label, .medium))
                        .foregroundStyle(Palette.t2)
                }
                if !diff.commits.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(alignment: .top, spacing: 6) {
                            Image(systemName: Icon.warning)
                                .font(.system(size: 11, weight: .semibold))
                            Text(SessionDiff.foreignCommitsWarning)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        .font(.ui(TypeSize.label, .medium))
                        .foregroundStyle(StatusTone.failed.textColor)
                        ForEach(diff.commits) { commit in
                            HStack(spacing: 8) {
                                Text(commit.shortSHA).font(.mono(TypeSize.caption))
                                    .foregroundStyle(Palette.t3)
                                Text(commit.subject).font(.ui(TypeSize.label))
                                    .lineLimit(1)
                            }
                            .textSelection(.enabled)
                        }
                    }
                    .padding(9)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(StatusTone.failed.soft, in: RoundedRectangle(cornerRadius: 10))
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}
