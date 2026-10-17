import NestKit
import SwiftUI

/// The project's chats, grouped, with New chat; squeezes into a rail of status dots.
/// Either form fades over the other while the width animates, clipped to the bar so the
/// full list keeps its own width and is uncovered rather than reflowed (B83). Settings opens from the
/// app menu (Cmd-comma); the account and connectors live in Settings (B39).
struct Sidebar: View {
    static let railWidth = 20.0
    /// Squeezing or opening a side bar.
    static let squeeze = Animation.smooth(duration: 0.28)

    @Environment(Shell.self) private var shell

    var body: some View {
        let collapsed = shell.projectState.leftCollapsed
        Group {
            if collapsed {
                SidebarRail().frame(width: Self.railWidth).transition(.opacity)
            } else {
                SidebarFull().resizableSidebar().transition(.opacity)
            }
        }
        .frame(maxHeight: .infinity)
        .sideSurface()
        // The resize handle's outer half reaches past the bar; the mask keeps it.
        .mask { Rectangle().padding(.trailing, -ResizableSidebar.handleWidth / 2) }
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
            ProjectHeader()

            Button {
                shell.newChat()
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: Icon.plus)
                        .font(.system(size: 11, weight: .regular))
                        .frame(width: 10)
                    Text("New chat")
                    Spacer(minLength: 0)
                }
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t2)
                .padding(.horizontal, 10)
                .frame(height: Metrics.rowHeight)
                .contentShape(Rectangle())
            }
            .buttonStyle(RowHoverStyle())
            .padding(.top, 2)
            .help("New chat (\(shell.shortcuts.shortcut(for: .newChat).display))")

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
        } else if group.showsTitle {
            header { EmptyView() }
            rows
        } else {
            // The only list, untitled while nothing is pinned (B77).
            Color.clear.frame(height: 6)
            rows
        }
    }

    private var rows: some View {
        ForEach(group.entries) { entry in
            switch entry {
            case .session(let session):
                ChatRow(session: session, finished: session.state == .closed)
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

/// The squeezed sidebar: one status dot per chat (B83). A click anywhere on the strip,
/// a dot included, opens the sidebar, as does the footer's triangle; a dot still shows
/// its chat's title on hover, drags, and has the chat's menu.
private struct SidebarRail: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let project = shell.project ?? ""
        let state = shell.projectState
        let entries = shell.sidebarGroups(in: project)
            .filter { $0.kind != .archived }
            .flatMap(\.entries)
        ScrollView {
            VStack(spacing: 0) {
                ForEach(entries) { entry in
                    RailChat(entry: entry, isOpen: state.layout.contains(entry.id))
                }
            }
            .frame(maxWidth: .infinity)
        }
        .scrollIndicators(.never)
        .padding(.top, 10)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .contentShape(Rectangle())
        .pointerStyle(.link)
        .onTapGesture { shell.update { $0.leftCollapsed = false } }
        .help("Open sidebar")
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Open sidebar")
        .accessibilityAddTraits(.isButton)
        .accessibilityAction { shell.update { $0.leftCollapsed = false } }
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
        // A plain circle rather than StatusDot, which hides itself from accessibility.
        Circle().fill(tone.color).frame(width: 7, height: 7)
            .frame(maxWidth: .infinity)
            .frame(height: 14)
            .background(
                isOpen ? accent.selection : hovering ? Palette.soft : .clear,
                in: .rounded(Radius.chip)
            )
            .padding(.horizontal, 3)
            .contentShape(Rectangle())
            .pointerStyle(.link)
            .onHover { hovering = $0 }
            .onTapGesture { shell.update { $0.leftCollapsed = false } }
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
            .accessibilityAction { shell.update { $0.leftCollapsed = false } }
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
