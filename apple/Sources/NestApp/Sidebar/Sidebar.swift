import NestKit
import SwiftUI

/// The project's chats, grouped, with New chat; folds into a rail. Settings opens from the
/// app menu (Cmd-comma); the account and connectors live in Settings (B39).
struct Sidebar: View {
    static let railWidth = 48.0

    @Environment(Shell.self) private var shell

    var body: some View {
        let collapsed = shell.projectState.leftCollapsed
        Group {
            if collapsed {
                SidebarRail().frame(width: Self.railWidth)
            } else {
                SidebarFull().resizableSidebar()
            }
        }
        .frame(maxHeight: .infinity)
        .sideSurface()
        .confirmationDialog(
            "Delete this chat?", isPresented: deleteBinding, titleVisibility: .visible
        ) {
            Button("Delete", role: .destructive) {
                if let id = shell.deleting {
                    shell.delete(id)
                }
            }
            Button("Cancel", role: .cancel) { shell.deleting = nil }
        } message: {
            Text(
                "\(shell.deleting.flatMap(shell.sessions.session)?.title ?? "This chat") is removed, with its pane, worktree and approvals."
            )
        }
    }

    private var deleteBinding: Binding<Bool> {
        Binding(
            get: { shell.deleting != nil },
            set: { if !$0 { shell.deleting = nil } })
    }
}

private struct SidebarFull: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let project = shell.project ?? ""
        let groups = shell.sidebarGroups(in: project)
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                ProjectIcon(project: project, repo: shell.app.repo(project), size: 15)
                Text(project)
                    .font(.ui(TypeSize.reading, .semibold))
                    .foregroundStyle(Palette.t1)
                    .lineLimit(1)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Button {
                    shell.update { $0.leftCollapsed = true }
                } label: {
                    Image(systemName: Icon.leftPanel).font(.system(size: 13))
                        .foregroundStyle(Palette.t3)
                }
                .buttonStyle(.nest(.plain, iconOnly: true))
                .help("Collapse sidebar")
                .accessibilityLabel("Collapse sidebar")
            }
            .padding(.leading, 8)
            .padding(.trailing, 2)
            .frame(height: 30)

            Button {
                shell.newChat()
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: Icon.plus)
                        .font(.system(size: 11, weight: .regular))
                        .frame(width: 10)
                    Text("New chat")
                    Spacer(minLength: 0)
                    Text("⌘N").font(.ui(10.5)).foregroundStyle(Palette.t3)
                }
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t2)
                .padding(.horizontal, 10)
                .frame(height: Metrics.rowHeight)
                .contentShape(Rectangle())
            }
            .buttonStyle(RowHoverStyle())
            .padding(.top, 2)
            .help("New chat (⌘N)")

            ScrollView {
                LazyVStack(spacing: 0, pinnedViews: []) {
                    if groups.isEmpty {
                        Text("No chats yet")
                            .font(.ui(TypeSize.ui))
                            .foregroundStyle(Palette.t3)
                            .padding(.vertical, 22)
                    }
                    ForEach(groups) { group in
                        GroupSection(group: group, project: project)
                    }
                }
            }
            .scrollIndicators(.never)
        }
        .padding(EdgeInsets(top: 8, leading: 6, bottom: 4, trailing: 6))
    }
}

private struct GroupSection: View {
    let group: SidebarGroup
    let project: String
    @Environment(Shell.self) private var shell
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        if group.kind == .archived {
            let open = shell.archivedOpen.contains(project)
            Button {
                withAnimation(reduceMotion ? nil : .smooth(duration: 0.2)) {
                    if open {
                        shell.archivedOpen.remove(project)
                    } else {
                        shell.archivedOpen.insert(project)
                    }
                }
            } label: {
                header {
                    Image(systemName: Icon.chevron)
                        .font(.system(size: 8, weight: .semibold))
                        .rotationEffect(.degrees(open ? 0 : -90))
                        .frame(width: 8)
                }
            }
            .buttonStyle(.plain)
            .pointerStyle(.link)
            .accessibilityLabel("Archived, \(group.entries.count)")
            ArchivedRows(open: open) { rows }
        } else {
            header { EmptyView() }
            rows
        }
    }

    private var rows: some View {
        ForEach(group.entries) { entry in
            switch entry {
            case .session(let session):
                ChatRow(session: session, finished: group.kind == .done)
                // Its pixies and running subagents, joined to it by tree lines (B46).
                if group.kind != .archived {
                    ChatTreeView(chat: session.id)
                }
            case .claudeChat(let chat): ClaudeChatRow(chat: chat)
            }
        }
    }

    /// A small grey label with the group's count; Archived leads with its chevron.
    private func header<Marker: View>(@ViewBuilder marker: () -> Marker) -> some View {
        HStack(spacing: 6) {
            marker()
            SectionLabel(text: group.kind.title, count: group.entries.count)
        }
        .padding(EdgeInsets(top: 12, leading: 10, bottom: 4, trailing: 10))
        .contentShape(Rectangle())
    }
}

/// The Archived group's rows, folding under its header: their height closes to nothing
/// as they fade, so nothing slides and the groups above stay put. They stay laid out
/// while closed to know the height to open to.
private struct ArchivedRows<Rows: View>: View {
    let open: Bool
    @ViewBuilder let rows: Rows
    @State private var height: CGFloat?

    var body: some View {
        VStack(spacing: 0) { rows }
            .fixedSize(horizontal: false, vertical: true)
            .onGeometryChange(for: CGFloat.self) {
                $0.size.height
            } action: {
                height = $0
            }
            .frame(height: open ? height : 0, alignment: .top)
            .clipped()
            .opacity(open ? 1 : 0)
            .allowsHitTesting(open)
            .accessibilityHidden(!open)
    }
}

/// The folded sidebar: initials with status dots.
private struct SidebarRail: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let project = shell.project ?? ""
        let state = shell.projectState
        let entries = shell.sidebarGroups(in: project)
            .filter { $0.kind != .archived }
            .flatMap(\.entries)
        VStack(spacing: 6) {
            Button {
                shell.update { $0.leftCollapsed = false }
            } label: {
                Image(systemName: Icon.leftPanel).font(.system(size: 13))
                    .foregroundStyle(Palette.t3)
            }
            .buttonStyle(.nest(.plain, iconOnly: true))
            .help("Expand sidebar")
            .accessibilityLabel("Expand sidebar")
            Button {
                shell.newChat()
            } label: {
                Image(systemName: Icon.plus).font(.system(size: 12))
            }
            .buttonStyle(.nest(.soft, iconOnly: true))
            .help("New chat")
            .accessibilityLabel("New chat")
            Separator().frame(width: 24).padding(.vertical, 4)
            ScrollView {
                VStack(spacing: 6) {
                    ForEach(entries) { entry in
                        RailChat(entry: entry, isOpen: state.layout.contains(entry.id))
                    }
                }
                .padding(.vertical, 4)
                .frame(maxWidth: .infinity)
            }
            .scrollIndicators(.never)
        }
        .padding(.vertical, 10)
    }
}

private struct RailChat: View {
    let entry: SidebarEntry
    let isOpen: Bool
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @State private var hovering = false

    var body: some View {
        let tone = tone
        let shape = RoundedRectangle.rounded(Radius.row)
        Text(Initials.of(entry.title))
            .font(.ui(TypeSize.meta, .medium))
            .foregroundStyle(isOpen ? Palette.t1 : Palette.t2)
            .frame(width: 30, height: 30)
            .background(
                isOpen ? accent.selection : hovering ? Palette.soft : .clear, in: shape
            )
            .overlay(alignment: .topTrailing) {
                StatusDot(tone: tone)
                    .offset(x: -3, y: 3)
            }
            .overlay(alignment: .bottomTrailing) {
                if case .claudeChat = entry {
                    ClaudeCodeBadge()
                        .offset(x: 3, y: 3)
                }
            }
            .contentShape(Rectangle())
            .pointerStyle(.link)
            .onHover { hovering = $0 }
            .onTapGesture { shell.openChat(entry.id) }
            .onDrag {
                shell.dragging = .chat(entry.id)
                return .chat(entry.id)
            } preview: {
                DragGhost(title: entry.title, tone: tone)
            }
            .contextMenu { EntryActions(entry: entry) }
            .help(help)
            .accessibilityElement()
            .accessibilityLabel("\(entry.title), \(status)")
            .accessibilityAddTraits(.isButton)
    }

    private var tone: StatusTone {
        if case .session(let session) = entry {
            return shell.tone(of: session)
        }
        return .done
    }

    private var status: String {
        if case .session(let session) = entry {
            return shell.statusLabel(of: session)
        }
        return "Claude Code chat"
    }

    private var help: String {
        if case .claudeChat = entry {
            return "\(entry.title) (Claude Code)"
        }
        return entry.title
    }
}

/// The actions of a sidebar entry's context menu.
private struct EntryActions: View {
    let entry: SidebarEntry

    var body: some View {
        switch entry {
        case .session(let session): ChatActions(session: session)
        case .claudeChat(let chat): ClaudeChatActions(chat: chat)
        }
    }
}
