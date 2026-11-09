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
    @Environment(\.reducedMotion) private var reduceMotion
    @State private var hovering = false
    @FocusState private var renameFocused: Bool
    @FocusState private var focus: RowFocus?

    private var showsMenu: Bool { hovering || revealsHoverControls || focus != nil }

    /// Whether the row's earlier worktrees are folded out, kept with the shell's other
    /// folds; closed until the user opens them.
    private var earlierOpen: Bool { shell.foldedRows[session.earlierFoldKey] ?? false }

    var body: some View {
        if shell.renaming == session.id {
            renameField
        } else {
            VStack(alignment: .leading, spacing: 0) {
                row
                if earlierOpen && !session.earlier.isEmpty {
                    EarlierWorktreesList(worktrees: session.earlier)
                        .transition(.opacity)
                }
            }
        }
    }

    private func toggleEarlier() {
        withAnimation(reduceMotion ? nil : .smooth(duration: 0.2)) {
            shell.foldedRows[session.earlierFoldKey] = !earlierOpen
        }
    }

    private var row: some View {
        let state = shell.projectState
        let rowState = state.layout.rowState(of: session.id)
        let isOpen = rowState != .closed
        let tone = shell.tone(of: session)
        let startedBy = PixieLabels.startedBy(session, pixies: shell.pixies.pixies)
        let place = ChatPlace.of(session, repo: shell.repo)
        return HStack(alignment: .firstTextBaseline, spacing: 8) {
            StatusMark(tone: tone)
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 4) {
                    Text(session.shownTitle)
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(
                            finished && rowState != .focused ? Palette.t2 : rowState.titleColor
                        )
                        .lineLimit(1)
                    // Computer use (B150): the chat is using an app right now.
                    if !shell.model.computer.targets(of: session.id).isEmpty {
                        Image(systemName: Icon.pointer)
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(Palette.link)
                            .help("Using an app")
                            .accessibilityLabel("Using an app")
                    }
                }
                if place != nil || session.issue != nil || session.pinned || session.stuck != nil
                    || startedBy != nil
                {
                    HStack(spacing: 4) {
                        if let place {
                            PlaceMark(place: place, project: session.repo)
                        }
                        if let issue = ChatPlace.issueMark(of: session) {
                            if place != nil {
                                Text("\u{00B7}")
                            }
                            Text(issue).monospacedDigit()
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
                    // Room for the count of earlier worktrees at the line's end, which
                    // stays put whether or not the "..." shows.
                    .padding(.trailing, session.earlier.isEmpty ? 0 : (showsMenu ? 26 : 46))
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            // Room for the "..." button, so the lines end before it rather than under it.
            .padding(.trailing, showsMenu ? 20 : 0)
        }
        .padding(.horizontal, SidebarRowMetrics.inset)
        .padding(.vertical, 5)
        .frame(minHeight: SidebarRowMetrics.height)
        .sidebarRow(rowState, hovering: hovering)
        .rowGlow(tone == .running, radius: 0)
        .overlay(alignment: .trailing) {
            if showsMenu {
                RowActionsMenu(title: session.title) { ChatActions(session: session) }
                    .focused($focus, equals: .control)
                    .padding(.trailing, 3)
            }
        }
        .overlay(alignment: .bottomTrailing) {
            if !session.earlier.isEmpty {
                EarlierCount(
                    title: session.title, count: session.earlier.count, open: earlierOpen,
                    toggle: toggleEarlier
                )
                // Always clear of the "...": it must not move under the pointer on hover.
                .padding(.trailing, SidebarRowMetrics.inset + 20)
                .padding(.bottom, 5)
            }
        }
        .contentShape(Rectangle())
        .pointerStyle(.link)
        .onHover { hovering = $0 }
        .onTapGesture { shell.openChat(session.id) }
        .keyboardActivatable { shell.openChat(session.id) }
        .focused($focus, equals: .row)
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
            "\(session.title), \(shell.statusLabel(of: session))\(place.map { ", \($0.accessibilityLabel)" } ?? "")\(session.earlierAccessibility.map { ", \($0)" } ?? "")\(ChatPlace.issueAccessibility(of: session).map { ", \($0)" } ?? "")\(session.stuck == nil ? "" : ", stuck")\(startedBy.map { ", \($0.text)" } ?? "")\(isOpen ? ", open" : "")\(session.pinned ? ", pinned" : "")"
        )
        .accessibilityAddTraits(rowState == .focused ? [.isButton, .isSelected] : .isButton)
        .accessibilityAction { shell.openChat(session.id) }
        .accessibilityActions {
            if !session.earlier.isEmpty {
                Button("Earlier worktrees", action: toggleEarlier)
            }
        }
    }

    private var renameField: some View {
        @Bindable var shell = shell
        return TextField("Rename chat", text: $shell.renameText)
            .textFieldStyle(.plain)
            .font(.ui(TypeSize.ui))
            .padding(.horizontal, SidebarRowMetrics.inset)
            .frame(height: SidebarRowMetrics.height)
            .background(Palette.soft)
            .overlay(Rectangle().strokeBorder(accent.focus, lineWidth: 1))
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
/// worktree name in mono, shortened in the middle, the name in its branch map lane colour
/// once the map has it (B96).
struct PlaceMark: View {
    let place: ChatPlace
    let project: String
    @Environment(Shell.self) private var shell

    var body: some View {
        HStack(spacing: 3) {
            BranchIcon(size: 8)
            Text(place.name)
                .font(.mono(TypeSize.meta))
                .lineLimit(1)
                .truncationMode(.middle)
                .foregroundStyle(
                    shell.branchMaps.color(of: place, in: project).map(Color.init)
                        ?? Palette.t3)
        }
        .help(place.help)
        .accessibilityHidden(true)
    }
}

/// The count at a chat row's right end, which folds out its earlier worktrees (B119).
private struct EarlierCount: View {
    let title: String
    let count: Int
    let open: Bool
    let toggle: () -> Void

    var body: some View {
        Button(action: toggle) {
            HStack(spacing: 1) {
                Image(systemName: Icon.chevronRight)
                    .font(.system(size: 8, weight: .semibold))
                    .rotationEffect(.degrees(open ? 90 : 0))
                Text("\(count)")
                    .font(.ui(TypeSize.meta))
                    .monospacedDigit()
            }
            .foregroundStyle(Palette.t3)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .help("Earlier worktrees of \(title)")
    }
}

/// A chat's earlier worktrees beneath its row, under its title: each one's branch and
/// whether the worktree was kept or deleted.
private struct EarlierWorktreesList: View {
    let worktrees: [EarlierWorktree]

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            ForEach(worktrees, id: \.self) { worktree in
                HStack(spacing: 8) {
                    Text(worktree.name)
                        .font(.mono(TypeSize.meta))
                        .lineLimit(1)
                        .truncationMode(.middle)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    Text(worktree.state.rawValue)
                        .font(.ui(TypeSize.meta))
                }
                .help(worktree.path)
            }
        }
        .foregroundStyle(Palette.t3)
        // Under the title: the row's inset, the 12 point mark slot and the 8 point gap.
        .padding(
            EdgeInsets(
                top: 0, leading: SidebarRowMetrics.inset + 20, bottom: 4,
                trailing: SidebarRowMetrics.inset))
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
        .localOnly(shell, DaemonText.appsOff)
        if let folder = shell.folder(ofPane: session.id), session.state != .closed {
            Button {
                shell.openTerminal(in: folder)
            } label: {
                Label("Terminal here", systemImage: Icon.terminal)
            }
            .localOnly(shell, DaemonText.terminalOff)
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
