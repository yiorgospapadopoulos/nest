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
                        .labelStyle(TightLabelStyle())
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(Palette.t2)
                }
                if !diff.commits.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(alignment: .top, spacing: 6) {
                            Image(systemName: Icon.warning)
                                .font(.system(size: 10, weight: .medium))
                            Text(SessionDiff.foreignCommitsWarning)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(StatusTone.failed.color)
                        ForEach(diff.commits) { commit in
                            HStack(spacing: 8) {
                                Text(commit.shortSHA).font(.mono(TypeSize.meta))
                                    .foregroundStyle(Palette.t3)
                                Text(commit.subject).font(.ui(TypeSize.ui))
                                    .lineLimit(1)
                            }
                            .textSelection(.enabled)
                        }
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .softFill()
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}
