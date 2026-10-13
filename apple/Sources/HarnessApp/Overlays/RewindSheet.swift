import HarnessKit
import SwiftUI

/// "Restore files to before this message": what would change, then Restore files. Only
/// the files go back, not the conversation (IMP-02).
struct RewindSheet: View {
    static let shownFiles = 8

    @Environment(Shell.self) private var shell

    var body: some View {
        SheetFrame(title: "Restore files", width: 460) {
            if let flow = shell.rewinding {
                content(flow)
            }
        }
    }

    @ViewBuilder private func content(_ flow: RewindFlow) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Restore the files to how they were before this message?")
                .font(.ui(TypeSize.body, .semibold))
                .padding(.top, 14)
            if flow.isLoading {
                HStack(spacing: 8) {
                    Spinner()
                    Text("Checking what would change…")
                        .font(.ui(TypeSize.small))
                        .foregroundStyle(Palette.t3)
                }
            } else if let preview = flow.preview, preview.canRewind {
                Text(preview.summary).font(.mono(TypeSize.small, .semibold))
                ForEach(preview.files.prefix(Self.shownFiles), id: \.self) { path in
                    Text(path)
                        .font(.mono(TypeSize.caption))
                        .foregroundStyle(Palette.t2)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
                if preview.files.count > Self.shownFiles {
                    Text("and \(preview.files.count - Self.shownFiles) more")
                        .font(.ui(TypeSize.caption))
                        .foregroundStyle(Palette.t3)
                }
            }
            if let failure = flow.failure {
                Text(failure)
                    .font(.ui(TypeSize.small, .medium))
                    .foregroundStyle(StatusTone.failed.textColor)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text(RewindFlow.scope)
                .font(.ui(TypeSize.small))
                .foregroundStyle(Palette.t3)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 8) {
                Spacer()
                Button("Cancel") { shell.close() }
                    .buttonStyle(.harness(.plain))
                Button {
                    shell.confirmRewind()
                } label: {
                    Label(
                        flow.isRestoring ? "Restoring…" : "Restore files",
                        systemImage: Icon.rewind)
                }
                .buttonStyle(.harness(.destructive))
                .disabled(!flow.canRestore)
            }
            .padding(.top, 8)
        }
    }
}
