import NestKit
import SwiftUI

/// A chat in the sidebar: status dot (the fireflies and a glow while it runs, B80) and its
/// whole title over where it works and its marks, as Claude Code chats' rows; click opens
/// it, drag splits. In a git project every chat names its branch: the project folder's
/// current one for in-place chats, its worktree's for worktree chats (B55).
struct ChatRow: View {
    let session: Session
    /// A row of the Done group: its name is grey, whatever its status.
    var finished = false
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @Environment(\.revealsHoverControls) private var revealsHoverControls
    @State private var hovering = false
    @FocusState private var renameFocused: Bool

    private var showsMenu: Bool { hovering || revealsHoverControls }

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
        let startedBy = PixieLabels.startedBy(session, pixies: shell.pixies.pixies)
        let place = ChatPlace.of(session, repo: shell.repo)
        return HStack(alignment: .firstTextBaseline, spacing: 8) {
            StatusMark(tone: tone)
            VStack(alignment: .leading, spacing: 1) {
                Text(session.title)
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(finished && !isSelected ? Palette.t2 : Palette.t1)
                    .lineLimit(1)
                if place != nil || session.pinned || session.stuck != nil || startedBy != nil {
                    HStack(spacing: 4) {
                        if let place {
                            PlaceMark(place: place)
                        }
                        if session.pinned {
                            Image(systemName: Icon.pin).font(.system(size: 8))
                        }
                        if let stuck = session.stuck {
                            if place != nil || session.pinned {
                                Text("·")
                            }
                            StuckBadge(flag: stuck)
                        }
                        if let startedBy {
                            StartedByMark(label: startedBy)
                        }
                    }
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                    .lineLimit(1)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            // Room for the "..." button, so the lines end before it rather than under it.
            .padding(.trailing, showsMenu ? 20 : 0)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(
            isSelected ? accent.selection : (isOpen || hovering) ? Palette.soft : .clear,
            in: .rounded(Radius.row)
        )
        .rowGlow(tone == .running)
        .overlay(alignment: .trailing) {
            if showsMenu {
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
            "\(session.title), \(shell.statusLabel(of: session))\(place.map { ", \($0.accessibilityLabel)" } ?? "")\(session.stuck == nil ? "" : ", stuck")\(startedBy.map { ", \($0.text)" } ?? "")\(isOpen ? ", open" : "")\(session.pinned ? ", pinned" : "")"
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

/// Where a chat works, in its sidebar row's second line: the branch icon and the branch or
/// worktree name in mono, shortened in the middle.
struct PlaceMark: View {
    let place: ChatPlace

    var body: some View {
        HStack(spacing: 3) {
            Image(systemName: Icon.branch).font(.system(size: 8))
            Text(place.name)
                .font(.mono(TypeSize.meta))
                .lineLimit(1)
                .truncationMode(.middle)
        }
        .help(place.help)
        .accessibilityHidden(true)
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
