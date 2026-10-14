import NestKit
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
                .font(.ui(TypeSize.ui, .medium))
                .padding(.top, 14)
            if flow.isLoading {
                HStack(spacing: 8) {
                    Spinner()
                    Text("Checking what would change…")
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(Palette.t3)
                }
            } else if let preview = flow.preview, preview.canRewind {
                Text(preview.summary).font(.mono(TypeSize.meta, .medium))
                ForEach(preview.files.prefix(Self.shownFiles), id: \.self) { path in
                    Text(path)
                        .font(.mono(TypeSize.meta))
                        .foregroundStyle(Palette.link)
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
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(StatusTone.failed.color)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text(RewindFlow.scope)
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 6) {
                Spacer()
                Button("Cancel") { shell.close() }
                    .buttonStyle(.nest(.soft))
                Button {
                    shell.confirmRewind()
                } label: {
                    Label(flow.restoreLabel, systemImage: Icon.rewind)
                }
                .buttonStyle(.nest(.destructive))
                .disabled(!flow.canRestore)
            }
            .padding(.top, 8)
        }
    }
}
