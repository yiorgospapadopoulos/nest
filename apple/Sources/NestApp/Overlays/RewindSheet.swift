import NestKit
import SwiftUI

/// Rewind to before a user message, as Claude Code's Esc Esc: restore the conversation,
/// the code, or both, with what the code part would change (B59, IMP-02). Edit opens it
/// only when files changed since the message.
struct RewindSheet: View {
    static let shownFiles = 8

    @Environment(Shell.self) private var shell

    var body: some View {
        let flow = shell.rewinding
        SheetFrame(title: flow?.purpose == .edit ? "Edit message" : "Rewind", width: 460) {
            if let flow {
                content(flow)
            }
        }
    }

    @ViewBuilder private func content(_ flow: RewindFlow) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(
                flow.purpose == .edit
                    ? "Files changed since this message. Restore them too?"
                    : "Go back to before this message?"
            )
            .font(.ui(TypeSize.ui, .medium))
            .padding(.top, 14)
            if flow.isLoading {
                HStack(spacing: 8) {
                    Fireflies()
                    Text("Checking what would change…")
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(Palette.t3)
                }
            } else {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(flow.choices, id: \.self) { restore in
                        RewindOption(
                            restore: restore, reason: flow.reason(restore),
                            selected: flow.selected == restore
                        ) { flow.select(restore) }
                    }
                }
                if let files = flow.files, files.canRewind, files.filesChanged > 0,
                    flow.selected != .conversation
                {
                    FileList(preview: files)
                }
                if let selected = flow.selected {
                    Text(selected.scope)
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            if let failure = flow.failure {
                Text(failure)
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(StatusTone.failed.color)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: 6) {
                Spacer()
                Button("Cancel") { shell.close() }
                    .buttonStyle(.nest(.soft))
                Button {
                    shell.confirmRewind()
                } label: {
                    Label(flow.confirmLabel, systemImage: Icon.rewind)
                }
                .buttonStyle(.nest(.destructive))
                .disabled(!flow.canConfirm)
                .keyboardShortcut(.defaultAction)
            }
            .padding(.top, 8)
        }
    }
}

/// One choice of the sheet, with why it cannot be chosen when it cannot.
private struct RewindOption: View {
    let restore: RewindRestore
    let reason: String?
    let selected: Bool
    let choose: () -> Void

    var body: some View {
        Button(action: choose) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Image(systemName: selected ? "largecircle.fill.circle" : "circle")
                    .font(.system(size: 11))
                    .foregroundStyle(selected ? Palette.t1 : Palette.t3)
                VStack(alignment: .leading, spacing: 1) {
                    Text(restore.label)
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(reason == nil ? Palette.t1 : Palette.t3)
                    if let reason {
                        Text(reason)
                            .font(.ui(TypeSize.meta))
                            .foregroundStyle(Palette.t3)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(.vertical, 4)
            .padding(.horizontal, 8)
            .background(selected ? Palette.soft : .clear, in: .rounded(Radius.button))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(reason != nil)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

/// What restoring the code changes: the summary and the first files.
private struct FileList: View {
    let preview: RewindPreview

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(preview.summary).font(.mono(TypeSize.meta, .medium))
            ForEach(preview.files.prefix(RewindSheet.shownFiles), id: \.self) { path in
                Text(path)
                    .font(.mono(TypeSize.meta))
                    .foregroundStyle(Palette.link)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            if preview.files.count > RewindSheet.shownFiles {
                Text("and \(preview.files.count - RewindSheet.shownFiles) more")
                    .font(.ui(TypeSize.caption))
                    .foregroundStyle(Palette.t3)
            }
        }
        .padding(.leading, 27)
    }
}
