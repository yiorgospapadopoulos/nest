import HarnessKit
import SwiftUI

/// A chat in the sidebar: status dot, title and elapsed time; click opens it, drag splits.
struct ChatRow: View {
    let session: Session
    /// A row of the Done group: its name is grey, whatever its status.
    var finished = false
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @State private var hovering = false
    @FocusState private var renameFocused: Bool

    var body: some View {
        if shell.renaming == session.id {
            renameField
        } else {
            row
        }
    }

    private var row: some View {
        let state = shell.projectState
        let isOpen = state.layout.contains(session.id)
        let isSelected = state.selectedChat == session.id
        let tone = shell.tone(of: session)
        return HStack(spacing: 8) {
            StatusDot(tone: tone, hollow: shell.isHollow(session))
            Text(session.title)
                .font(.ui(TypeSize.ui))
                .foregroundStyle(finished && !isSelected ? Palette.t2 : Palette.t1)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
            if let stuck = session.stuck {
                StuckBadge(flag: stuck)
            }
            TimelineView(.periodic(from: .now, by: 30)) { context in
                HStack(spacing: 4) {
                    if session.pinned {
                        Image(systemName: Icon.pin).font(.system(size: 8))
                    }
                    Text(Elapsed.short(from: session.updatedAt, to: context.date))
                        .monospacedDigit()
                }
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
            }
            .opacity(hovering ? 0 : 1)
        }
        .padding(.horizontal, 10)
        .frame(height: Metrics.rowHeight)
        .background(
            isSelected ? accent.selection : (isOpen || hovering) ? Palette.soft : .clear,
            in: .rounded(Radius.row)
        )
        .overlay(alignment: .trailing) {
            if hovering {
                RowActionsMenu(title: session.title) { ChatActions(session: session) }
                    .padding(.trailing, 3)
            }
        }
        .contentShape(Rectangle())
        .pointerStyle(.link)
        .onHover { hovering = $0 }
        .onTapGesture { shell.openChat(session.id) }
        .onDrag {
            shell.dragging = .chat(session.id)
            return .chat(session.id)
        } preview: {
            DragGhost(title: session.title, tone: tone)
        }
        .chatContextMenu(session)
        .opacity(shell.dragging == .chat(session.id) ? 0.45 : 1)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(
            "\(session.title), \(shell.statusLabel(of: session))\(session.stuck == nil ? "" : ", stuck")\(isOpen ? ", open" : "")\(session.pinned ? ", pinned" : "")"
        )
        .accessibilityAddTraits(.isButton)
        .accessibilityAction { shell.openChat(session.id) }
    }

    private var renameField: some View {
        @Bindable var shell = shell
        return TextField("Rename chat", text: $shell.renameText)
            .textFieldStyle(.plain)
            .font(.ui(TypeSize.ui))
            .padding(.horizontal, 10)
            .frame(height: Metrics.rowHeight)
            .background(Palette.soft, in: .rounded(Radius.row))
            .overlay(
                RoundedRectangle.rounded(Radius.row).strokeBorder(accent.focus, lineWidth: 1)
            )
            .focused($renameFocused)
            .onAppear { renameFocused = true }
            .onSubmit { shell.commitRename(save: true) }
            .onExitCommand { shell.commitRename(save: false) }
            .onChange(of: renameFocused) { _, focused in
                if !focused && shell.renaming == session.id {
                    shell.commitRename(save: true)
                }
            }
    }
}

/// A sidebar row's "..." button that shows on hover.
struct RowActionsMenu<Actions: View>: View {
    let title: String
    @ViewBuilder let actions: () -> Actions

    var body: some View {
        Menu {
            actions()
        } label: {
            Image(systemName: Icon.more)
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(Palette.t2)
                .frame(width: 20, height: 20)
                .background(Palette.soft, in: .rounded(Radius.button))
                .contentShape(Rectangle())
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .menuIndicator(.hidden)
        .fixedSize()
        .help("More")
        .accessibilityLabel("Actions for \(title)")
    }
}

/// Pin, rename, continue in Claude Code, archive and delete.
struct ChatActions: View {
    let session: Session
    @Environment(Shell.self) private var shell

    var body: some View {
        if !session.isArchived {
            Button {
                shell.togglePin(session.id)
            } label: {
                Label(session.pinned ? "Unpin" : "Pin", systemImage: Icon.pin)
            }
        } else {
            Button {
                shell.setArchived(session.id, false)
            } label: {
                Label("Unarchive", systemImage: Icon.archive)
            }
        }
        Button {
            shell.beginRename(session.id)
        } label: {
            Label("Rename", systemImage: Icon.edit)
        }
        Button {
            shell.continueInClaudeCode(session.id)
        } label: {
            Label("Continue in Claude Code", systemImage: Icon.terminal)
        }
        if let folder = shell.folder(ofPane: session.id), session.state != .closed {
            Button {
                shell.openTerminal(in: folder)
            } label: {
                Label("Terminal here", systemImage: Icon.terminal)
            }
        }
        if !session.isArchived {
            Button {
                shell.setArchived(session.id, true)
            } label: {
                Label("Archive", systemImage: Icon.archive)
            }
        }
        Divider()
        Button(role: .destructive) {
            shell.deleting = session.id
        } label: {
            Label("Delete…", systemImage: Icon.trash)
        }
    }
}

extension View {
    func chatContextMenu(_ session: Session) -> some View {
        contextMenu { ChatActions(session: session) }
    }
}

/// What follows the pointer while a chat or pane is dragged.
struct DragGhost: View {
    let title: String
    let tone: StatusTone

    var body: some View {
        HStack(spacing: 8) {
            StatusDot(tone: tone)
            Text(title)
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t1)
                .lineLimit(1)
        }
        .padding(.horizontal, 10)
        .frame(height: 30)
        .sheetSurface(radius: Radius.row)
        .rotationEffect(.degrees(-2))
    }
}
