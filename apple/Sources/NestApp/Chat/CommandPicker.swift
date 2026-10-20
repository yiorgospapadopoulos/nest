import NestKit
import SwiftUI

/// The list `/model` or `/permissions` opens above the composer, as Claude Code shows
/// its own pickers (B59): each choice with its description and a check on the current
/// one. Picking one applies it as the composer's menus do and closes the list.
struct CommandPicker: View {
    let chat: String
    let picker: ComposerPicker
    let draft: ComposerDraft
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent

    private struct Choice: Identifiable {
        let id: String
        let title: String
        let detail: String
        let checked: Bool
        let pick: () -> Void
    }

    var body: some View {
        let choices = self.choices
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                Text(picker == .model ? "Model" : "Permission mode")
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                Spacer()
                Button(action: close) {
                    Image(systemName: Icon.close)
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(Palette.t3)
                }
                .buttonStyle(.plain)
                .pointerStyle(.link)
                .keyboardShortcut(.cancelAction)
                .accessibilityLabel("Close")
            }
            .padding(.horizontal, 8)
            .padding(.top, 2)
            if choices.isEmpty {
                Text("Models unavailable")
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t3)
                    .padding(8)
            }
            ForEach(choices) { choice in
                Button {
                    choice.pick()
                    close()
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: Icon.check)
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(Palette.t1)
                            .opacity(choice.checked ? 1 : 0)
                            .frame(width: 10)
                        Text(choice.title)
                            .font(.ui(TypeSize.ui, .medium))
                            .foregroundStyle(Palette.t1)
                            .lineLimit(1)
                            .layoutPriority(1)
                        Text(choice.detail)
                            .font(.ui(TypeSize.ui))
                            .foregroundStyle(Palette.t3)
                            .lineLimit(1)
                            .truncationMode(.tail)
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 8)
                    .frame(height: SuggestionList.rowHeight)
                    .background(
                        choice.checked ? accent.selection : .clear, in: .rounded(Radius.row)
                    )
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .pointerStyle(.link)
                .accessibilityAddTraits(choice.checked ? .isSelected : [])
            }
        }
        .padding(6)
        .sheetSurface(radius: Radius.card)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(picker == .model ? "Model" : "Permission mode")
    }

    private var choices: [Choice] {
        let isDraft = shell.isDraft(chat)
        let session = isDraft ? nil : shell.sessions.session(chat)
        let model = isDraft ? draft.model : session?.model
        let catalog = shell.catalog(forChat: chat)
        switch picker {
        case .model:
            return catalog.models.map { info in
                Choice(
                    id: info.value, title: info.displayName, detail: info.description,
                    checked: catalog.isSelected(info, current: model)
                ) { shell.setModel(info, for: chat) }
            }
        case .permissions:
            let current = isDraft ? draft.permission : session?.permissionMode
            return catalog.permissionModes(for: model).map { mode in
                Choice(
                    id: mode.rawValue, title: mode.label, detail: mode.summary,
                    checked: mode == current
                ) { shell.setPermission(mode, for: chat) }
            }
        }
    }

    private func close() {
        withAnimation(.smooth(duration: 0.15)) { draft.picker = nil }
    }
}
