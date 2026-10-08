import HarnessKit
import SwiftUI

/// A chat in the sidebar: status dot, title and elapsed time; click opens it, drag splits.
struct ChatRow: View {
    let session: Session
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @Environment(\.glass) private var glass
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
        return HStack(spacing: 9) {
            StatusDot(tone: tone, hollow: shell.isHollow(session))
                .frame(width: 10)
            Text(session.title)
                .font(.ui(TypeSize.callout, isOpen ? .semibold : .regular))
                .foregroundStyle(Palette.t1)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
            if let stuck = session.stuck {
                StuckBadge(flag: stuck)
            }
            TimelineView(.periodic(from: .now, by: 30)) { context in
                HStack(spacing: 4) {
                    if session.pinned {
                        Image(systemName: Icon.pin).font(.system(size: 9))
                    }
                    Text(Elapsed.short(from: session.updatedAt, to: context.date))
                        .monospacedDigit()
                }
                .font(.ui(TypeSize.caption))
                .foregroundStyle(Palette.t3)
            }
            .opacity(hovering ? 0 : 1)
        }
        .padding(.horizontal, 9)
        .padding(.vertical, glass.spacing.rowPaddingY)
        .background(
            isSelected ? accent.soft : (isOpen || hovering) ? Palette.fill : .clear,
            in: glass.rounded(glass.radius.item)
        )
        .overlay(alignment: .trailing) {
            if hovering {
                RowActionsMenu(title: session.title) { ChatActions(session: session) }
                    .padding(.trailing, 5)
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
            .font(.ui(TypeSize.callout))
            .padding(.horizontal, 9)
            .frame(height: 32)
            .background(glass.surface, in: glass.rounded(glass.radius.item))
            .overlay(glass.rounded(glass.radius.item).stroke(accent.accent, lineWidth: 2))
            .padding(.vertical, 2)
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
    @Environment(\.glass) private var glass

    var body: some View {
        Menu {
            actions()
        } label: {
            Image(systemName: Icon.more)
                .font(.system(size: 11, weight: .bold))
                .foregroundStyle(Palette.t2)
                .frame(width: 24, height: 24)
                .background(glass.surface, in: glass.rounded(glass.radius.small))
                .shadow(color: glass.shadow, radius: 1.5, y: 1)
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
    @Environment(\.glass) private var glass

    var body: some View {
        HStack(spacing: 8) {
            StatusDot(tone: tone, pulses: false)
            Text(title)
                .font(.ui(TypeSize.callout, .semibold))
                .foregroundStyle(Palette.t1)
                .lineLimit(1)
        }
        .padding(.leading, 11)
        .padding(.trailing, 14)
        .frame(height: 36)
        .background(glass.surface, in: glass.rounded(glass.radius.item))
        .overlay(glass.rounded(glass.radius.item).stroke(glass.stroke))
        .rotationEffect(.degrees(-2))
    }
}
