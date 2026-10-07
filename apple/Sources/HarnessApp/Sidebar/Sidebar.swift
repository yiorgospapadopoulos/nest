import HarnessKit
import SwiftUI

/// The project's chats, grouped, with New chat and the account row; folds into a rail.
struct Sidebar: View {
    static let width = 252.0
    static let railWidth = 56.0

    @Environment(Shell.self) private var shell
    @Environment(\.glass) private var glass

    var body: some View {
        let collapsed = shell.projectState.leftCollapsed
        Group {
            if collapsed {
                SidebarRail()
            } else {
                SidebarFull()
            }
        }
        .frame(width: collapsed ? Self.railWidth : Self.width)
        .frame(maxHeight: .infinity)
        .panelGlass(radius: glass.radius.panel)
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
    @Environment(\.accentColors) private var accent
    @Environment(\.glass) private var glass

    var body: some View {
        let project = shell.project ?? ""
        let groups = shell.sidebarGroups(in: project)
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                ProjectMarkView(name: project, size: 22)
                Text(project)
                    .font(.ui(TypeSize.subhead, .bold))
                    .lineLimit(1)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Button {
                    shell.update { $0.leftCollapsed = true }
                } label: {
                    Image(systemName: Icon.leftPanel).font(.system(size: 14))
                }
                .buttonStyle(.harness(.ghost, iconOnly: true))
                .help("Collapse sidebar")
                .accessibilityLabel("Collapse sidebar")
            }
            .padding(.leading, 6)
            .padding(.bottom, 10)

            Button {
                shell.newChat()
            } label: {
                Label("New chat", systemImage: Icon.plus)
                    .frame(maxWidth: .infinity)
                    .frame(height: 32)
                    .background(
                        accent.accent,
                        in: glass.rounded(min(glass.radius.item + 1, glass.radius.control))
                    )
                    .foregroundStyle(accent.onAccent)
                    .font(.ui(TypeSize.callout, .semibold))
                    .labelStyle(TightLabelStyle())
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .pointerStyle(.link)
            .padding(.bottom, 4)

            ScrollView {
                LazyVStack(spacing: 0, pinnedViews: []) {
                    if groups.isEmpty {
                        Text("No chats yet")
                            .font(.ui(TypeSize.small))
                            .foregroundStyle(Palette.t3)
                            .padding(.vertical, 22)
                    }
                    ForEach(groups) { group in
                        GroupSection(group: group, project: project)
                    }
                }
                .padding(.horizontal, 4)
            }
            .scrollIndicators(.never)
            .padding(.horizontal, -4)

            AccountRow()
        }
        .padding(EdgeInsets(top: 12, leading: 10, bottom: 10, trailing: 10))
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
                        .font(.system(size: 9, weight: .bold))
                        .rotationEffect(.degrees(open ? 0 : -90))
                }
            }
            .buttonStyle(.plain)
            .pointerStyle(.link)
            .accessibilityLabel("Archived, \(group.entries.count)")
            ArchivedRows(open: open) { rows }
        } else {
            header { marker }
            rows
        }
    }

    private var rows: some View {
        ForEach(group.entries) { entry in
            switch entry {
            case .session(let session): ChatRow(session: session)
            case .claudeChat(let chat): ClaudeChatRow(chat: chat)
            }
        }
    }

    @ViewBuilder private var marker: some View {
        switch group.kind {
        case .pinned: Image(systemName: Icon.pin).font(.system(size: 10, weight: .semibold))
        case .needsYou: StatusDot(tone: .waiting, pulses: false)
        case .running: StatusDot(tone: .running, pulses: false)
        case .idle: StatusDot(tone: .done, hollow: true)
        case .done, .archived: StatusDot(tone: .done)
        }
    }

    private func header<Marker: View>(@ViewBuilder marker: () -> Marker) -> some View {
        HStack(spacing: 6) {
            marker()
            Text(group.kind.title)
            Spacer()
            Text("\(group.entries.count)").fontWeight(.semibold)
        }
        .font(.ui(TypeSize.caption, .bold))
        .foregroundStyle(Palette.t3)
        .padding(EdgeInsets(top: 12, leading: 8, bottom: 4, trailing: 8))
        .contentShape(Rectangle())
    }
}

/// The user's account (opens Connectors in B09) and the Settings gear.
struct AccountRow: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        HStack(spacing: 9) {
            Button {
                shell.show(.connectors)
            } label: {
                HStack(spacing: 9) {
                    Avatar(name: shell.accountName)
                    VStack(alignment: .leading, spacing: 0) {
                        Text(shell.accountName)
                            .font(.ui(TypeSize.callout, .semibold))
                            .foregroundStyle(Palette.t1)
                            .lineLimit(1)
                        Text(shell.agents.plan)
                            .font(.ui(TypeSize.caption))
                            .foregroundStyle(Palette.t3)
                    }
                    Spacer(minLength: 0)
                }
                .padding(4)
                .contentShape(Rectangle())
            }
            .buttonStyle(RowHoverStyle())
            .padding(.vertical, -4)
            .padding(.leading, -4)
            .help("Connectors")
            SettingsButton()
        }
        .padding(EdgeInsets(top: 10, leading: 4, bottom: 0, trailing: 2))
        .overlay(alignment: .top) { Rectangle().fill(Palette.hair).frame(height: 1) }
        .padding(.top, 8)
    }
}

struct SettingsButton: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        Button {
            shell.show(.settings)
        } label: {
            Image(systemName: Icon.gear).font(.system(size: 14))
        }
        .buttonStyle(.harness(.ghost, iconOnly: true))
        .help("Settings")
        .accessibilityLabel("Settings")
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
                Image(systemName: Icon.leftPanel).font(.system(size: 14))
            }
            .buttonStyle(.harness(.ghost, iconOnly: true))
            .help("Expand sidebar")
            .accessibilityLabel("Expand sidebar")
            Button {
                shell.newChat()
            } label: {
                Image(systemName: Icon.plus).font(.system(size: 13, weight: .semibold))
            }
            .buttonStyle(.harness(.primary, iconOnly: true))
            .help("New chat")
            .accessibilityLabel("New chat")
            Rectangle().fill(Palette.hair2).frame(width: 24, height: 1).padding(.vertical, 4)
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
            VStack(spacing: 8) {
                Button {
                    shell.show(.connectors)
                } label: {
                    Avatar(name: shell.accountName)
                }
                .buttonStyle(.plain)
                .pointerStyle(.link)
                .help("\(shell.accountName), Connectors")
                SettingsButton()
            }
            .padding(.top, 10)
            .frame(width: 36)
            .overlay(alignment: .top) { Rectangle().fill(Palette.hair).frame(height: 1) }
        }
        .padding(.vertical, 12)
        .padding(.bottom, -2)
    }
}

private struct RailChat: View {
    let entry: SidebarEntry
    let isOpen: Bool
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @Environment(\.glass) private var glass
    @State private var hovering = false

    var body: some View {
        let tone = tone
        let shape = glass.rounded(min(glass.radius.item + 2, 12))
        Text(Initials.of(entry.title))
            .font(.ui(TypeSize.label, .bold))
            .foregroundStyle(Palette.t1)
            .frame(width: 36, height: 36)
            .background(
                isOpen ? accent.soft : hovering ? Palette.fill2 : Palette.fill, in: shape
            )
            .overlay {
                if isOpen {
                    shape.strokeBorder(accent.accent, lineWidth: 1.5)
                }
            }
            .overlay(alignment: .topTrailing) {
                StatusDot(tone: tone, hollow: hollow, size: 10, pulses: false)
                    .background(Circle().fill(glass.surface).padding(-2))
                    .offset(x: 2, y: -2)
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
                return NSItemProvider(object: entry.id as NSString)
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

    private var hollow: Bool {
        if case .session(let session) = entry {
            return shell.isHollow(session)
        }
        return true
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
