import NestKit
import SwiftUI

/// The pixies down the left, as the sidebar lists chats, with New pixie and New team.
/// Teams are foldable sections with their pixies, the leader marked; pixies with no team
/// follow (B40). A click opens a pixie's pane; drag one onto the workspace to split it
/// like a chat, onto another pixie to put it there (joining that one's team), onto a
/// team's header to join it, or onto No team to leave its team. Each pixie and team has
/// a menu under ⋯ and on right-click.
struct PixieList: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let sections = shell.pixieSections
        let hidden = shell.pixies.pixies.count { $0.hidden }
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Text("Pixies")
                    .font(.ui(TypeSize.reading, .semibold))
                    .foregroundStyle(Palette.t1)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 8)
            .frame(height: 30)

            HStack(spacing: 2) {
                NewButton(title: "New pixie", icon: Icon.plus) {
                    shell.createPixie(CreatePixieRequest(name: "New pixie"), details: true)
                }
                NewButton(title: "New team", icon: "person.2") { shell.ask(.newTeam) }
            }
            .padding(.top, 2)
            .padding(.bottom, 8)

            ScrollView {
                LazyVStack(spacing: 0) {
                    ReportsInbox()
                    ForEach(sections.teams) { section in
                        TeamSection(section: section)
                    }
                    LooseSection(pixies: sections.loose, titled: !sections.teams.isEmpty)
                }
            }
            .scrollIndicators(.never)

            if hidden > 0 {
                Button {
                    shell.showsHiddenPixies.toggle()
                } label: {
                    Label(
                        shell.showsHiddenPixies ? "Hide hidden" : "Show hidden (\(hidden))",
                        systemImage: shell.showsHiddenPixies ? "eye.slash" : "eye")
                }
                .buttonStyle(.nest(.plain))
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.leading, 4)
            }
        }
        .padding(EdgeInsets(top: 8, leading: 6, bottom: 8, trailing: 6))
        .frame(maxHeight: .infinity, alignment: .top)
        .sideSurface()
        .resizableSidebar()
        .pixiePrompts()
    }
}

/// New pixie or New team, side by side under the title.
private struct NewButton: View {
    let title: String
    let icon: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Image(systemName: icon).font(.system(size: 11, weight: .medium))
                Text(title)
                Spacer(minLength: 0)
            }
            .font(.ui(TypeSize.ui))
            .foregroundStyle(Palette.t2)
            .padding(.horizontal, 10)
            .frame(height: Metrics.rowHeight)
            .contentShape(Rectangle())
        }
        .buttonStyle(RowHoverStyle())
    }
}

/// A team: its header, then its pixies unless folded. A pixie dropped on the header
/// joins the team.
private struct TeamSection: View {
    let section: PixieTeamSection
    @Environment(Shell.self) private var shell

    var body: some View {
        let folded = shell.app.foldedTeams.contains(section.id)
        let ids = section.members.map(\.id)
        VStack(spacing: 0) {
            TeamHeader(section: section, folded: folded)
            if !folded {
                ForEach(section.members) { pixie in
                    PixieRow(pixie: pixie, listed: ids, leader: section.isLeader(pixie))
                }
                if section.members.isEmpty {
                    Text("Drag pixies here")
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.leading, 34)
                        .frame(height: 24)
                }
            }
        }
        .padding(.bottom, 6)
    }
}

/// A team's header: fold chevron, name and @handle; ⋯ on hover and right-click open its
/// menu. A click folds or unfolds it.
private struct TeamHeader: View {
    let section: PixieTeamSection
    let folded: Bool
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @Environment(\.revealsHoverControls) private var reveal
    @State private var hovering = false
    @State private var targeted = false

    var body: some View {
        let team = section.team
        HStack(spacing: 6) {
            Image(systemName: Icon.chevron)
                .font(.system(size: 8, weight: .semibold))
                .foregroundStyle(Palette.t3)
                .rotationEffect(.degrees(folded ? -90 : 0))
                .frame(width: 18)
            Text(team.name)
                .font(.ui(TypeSize.ui, .semibold))
                .foregroundStyle(nameColor)
                .layoutPriority(1)
            Text("@\(team.handle)")
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t3)
            Spacer(minLength: 4)
            if hovering || reveal {
                RowActionsMenu(title: team.name) { TeamActions(section: section) }
            }
        }
        .lineLimit(1)
        .padding(.leading, 10)
        .padding(.trailing, 3)
        .frame(height: 28)
        .background(
            targeted ? accent.selection : hovering ? Palette.soft : .clear, in: .rounded(Radius.row)
        )
        .contentShape(Rectangle())
        .pointerStyle(.link)
        .onHover { hovering = $0 }
        .onTapGesture { shell.toggleTeamFold(team.id) }
        .onDrop(of: [.nestChat], isTargeted: $targeted) { _ in
            guard let dragged = draggedPixie else { return false }
            shell.setPixieTeam(dragged, team.id)
            shell.dragging = nil
            return true
        }
        .contextMenu { TeamActions(section: section) }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(
            "Team \(team.name), @\(team.handle), \(section.members.count) pixies\(folded ? ", folded" : "")"
        )
        .accessibilityAddTraits(.isButton)
        .accessibilityAction { shell.toggleTeamFold(team.id) }
    }

    /// A pixie dragged from the list.
    private var draggedPixie: String? {
        guard case .chat(let id) = shell.dragging, shell.pixie(id) != nil else { return nil }
        return id
    }

    /// The leader's colour, as the team's mentions in chats; grey without a leader.
    private var nameColor: Color {
        section.team.leaderColor(among: shell.pixies.pixies).map { Color(hex: $0) } ?? Palette.t2
    }
}

/// The pixies with no team; titled "No team" below teams, where dropping a pixie takes
/// it out of its team.
private struct LooseSection: View {
    let pixies: [Pixie]
    let titled: Bool
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @State private var targeted = false

    var body: some View {
        let ids = pixies.map(\.id)
        VStack(spacing: 0) {
            if titled {
                HStack(spacing: 6) {
                    Text("No team")
                        .font(.ui(TypeSize.ui, .semibold))
                        .foregroundStyle(Palette.t3)
                    Spacer(minLength: 0)
                }
                .padding(.leading, 34)
                .frame(height: 28)
                .background(targeted ? accent.selection : .clear, in: .rounded(Radius.row))
                .contentShape(Rectangle())
                .onDrop(of: [.nestChat], isTargeted: $targeted) { _ in
                    guard case .chat(let id) = shell.dragging, shell.pixie(id) != nil else {
                        return false
                    }
                    shell.setPixieTeam(id, nil)
                    shell.dragging = nil
                    return true
                }
            }
            ForEach(pixies) { pixie in
                PixieRow(pixie: pixie, listed: ids, leader: false)
            }
        }
    }
}

/// A pixie: its sprite, name and @slug, "Leader" for its team's leader; a dot while its
/// chat runs, and a count of what waits for the user. Selected while its pane has focus,
/// softly filled while it is open; ⋯ on hover opens its menu.
private struct PixieRow: View {
    let pixie: Pixie
    /// The ids of the pixies in its section, in order.
    let listed: [String]
    let leader: Bool
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @Environment(\.revealsHoverControls) private var reveal
    @State private var hovering = false
    /// Another pixie is dragged over this one.
    @State private var targeted = false

    var body: some View {
        let state = shell.app.pixieState
        let selected = state.layout.focused == pixie.id
        let open = state.layout.contains(pixie.id)
        let running = shell.isWorking(pixie)
        let waiting =
            shell.approvals.pending.count { $0.repo == "\(Pixie.repoPrefix)\(pixie.id)" }
            + shell.reports.unreadActions(of: pixie.id)
        let showsMenu = hovering || (reveal && selected)
        HStack(spacing: 8) {
            SpriteView(
                mascot: pixie.mascot, color: pixie.color, size: 16, working: running,
                phaseKey: pixie.id
            )
            .frame(width: 18)
            .opacity(pixie.hidden ? 0.5 : 1)
            // The handle gives way first: shown whole or not at all, and the name is cut
            // only once it is gone.
            ViewThatFits(in: .horizontal) {
                label(handle: true).fixedSize()
                label(handle: false)
            }
            .font(.ui(TypeSize.ui))
            .lineLimit(1)
            .frame(maxWidth: .infinity, alignment: .leading)
            if showsMenu {
                RowActionsMenu(title: pixie.name) { PixieActions(pixie: pixie, listed: listed) }
            } else if waiting > 0 {
                CountBadge(count: waiting, urgent: true)
            } else if running {
                // The sprite beside it hops while the pixie works: a plain dot here.
                StatusDot(tone: .running)
            }
        }
        .padding(.leading, 10)
        .padding(.trailing, showsMenu ? 3 : 10)
        .frame(height: 30)
        .background(
            selected ? accent.selection : (open || hovering) ? Palette.soft : .clear,
            in: .rounded(Radius.row)
        )
        .contentShape(Rectangle())
        .overlay(alignment: dropsBelow ? .bottom : .top) {
            if targeted && dragged != pixie.id {
                Capsule()
                    .fill(accent.accent)
                    .frame(height: 2)
                    .offset(y: dropsBelow ? 2 : -2)
                    .allowsHitTesting(false)
            }
        }
        .pointerStyle(.link)
        .onHover { hovering = $0 }
        .onTapGesture { shell.openPixie(pixie.id) }
        // The same drag as a sidebar chat's, so the workspace takes it like one.
        .onDrag {
            shell.dragging = .chat(pixie.id)
            return .chat(pixie.id)
        } preview: {
            SpriteView(mascot: pixie.mascot, color: pixie.color, size: 28)
                .padding(6)
                .background(Palette.sheet, in: .rounded(Radius.row))
        }
        .onDrop(of: [.nestChat], isTargeted: $targeted) { _ in drop() }
        .opacity(dragged == pixie.id ? 0.45 : 1)
        .contextMenu { PixieActions(pixie: pixie, listed: listed) }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(
            "\(pixie.name), @\(pixie.slug)\(leader ? ", leader" : "")\(running ? ", running" : "")\(waiting > 0 ? ", \(waiting) need you" : "")\(open ? ", open" : "")"
        )
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
        .accessibilityAction { shell.openPixie(pixie.id) }
        .accessibilityAction(named: "Move Up") { shell.movePixie(pixie.id, by: -1) }
        .accessibilityAction(named: "Move Down") { shell.movePixie(pixie.id, by: 1) }
    }

    /// The name, "Leader" for the team's leader, and the @slug when `handle`.
    private func label(handle: Bool) -> some View {
        HStack(spacing: 6) {
            Text(pixie.name)
                .foregroundStyle(pixie.hidden ? Palette.t2 : Palette.t1)
            if leader {
                Text("Leader")
                    .font(.ui(TypeSize.micro, .medium))
                    .foregroundStyle(Palette.t2)
                    .padding(.horizontal, 5)
                    .frame(height: 16)
                    .background(Palette.soft, in: .rounded(Radius.chip))
                    .fixedSize()
            }
            if handle {
                Text(pixie.hidden ? "@\(pixie.slug) · Hidden" : "@\(pixie.slug)")
                    .foregroundStyle(Palette.t3)
            }
        }
    }

    /// The pixie being dragged, from any section, for where the drop line shows.
    private var dragged: String? {
        guard case .chat(let id) = shell.dragging, shell.pixie(id) != nil else { return nil }
        return id
    }

    /// A pixie dragged down the list lands below this one, else above it.
    private var dropsBelow: Bool {
        guard let dragged, let from = shell.pixie(dragged)?.position else { return false }
        return from < pixie.position
    }

    /// A pixie dropped here takes this one's place, in this one's team.
    private func drop() -> Bool {
        guard let dragged else { return false }
        shell.placePixie(dragged, onto: pixie.id)
        shell.dragging = nil
        return true
    }
}

/// A pixie's menu: Open, Details, Duplicate, Move to team, Move Up, Move Down, Hide or
/// Show, Delete.
struct PixieActions: View {
    let pixie: Pixie
    /// The ids of the pixies in its section, in order.
    let listed: [String]
    @Environment(Shell.self) private var shell

    var body: some View {
        Button {
            shell.openPixie(pixie.id)
        } label: {
            Label("Open", systemImage: Icon.open)
        }
        Button {
            shell.showPixieDetails(pixie.id)
        } label: {
            Label("Details", systemImage: Icon.rightPanel)
        }
        Button {
            shell.duplicatePixie(pixie.id)
        } label: {
            Label("Duplicate", systemImage: Icon.copy)
        }
        Menu {
            ForEach(shell.pixies.teams) { team in
                Button {
                    shell.setPixieTeam(pixie.id, team.id)
                } label: {
                    TeamChoice(name: team.name, chosen: pixie.teamID == team.id)
                }
            }
            if !shell.pixies.teams.isEmpty {
                Divider()
            }
            Button {
                shell.setPixieTeam(pixie.id, nil)
            } label: {
                TeamChoice(name: "No team", chosen: pixie.teamID == nil)
            }
        } label: {
            Label("Move to team", systemImage: "person.2")
        }
        Divider()
        Button("Move Up") { shell.movePixie(pixie.id, by: -1) }
            .disabled(listed.first == pixie.id)
        Button("Move Down") { shell.movePixie(pixie.id, by: 1) }
            .disabled(listed.last == pixie.id)
        Divider()
        Button {
            shell.updatePixie(pixie.id, UpdatePixieRequest(hidden: !pixie.hidden))
        } label: {
            Label(pixie.hidden ? "Show" : "Hide", systemImage: pixie.hidden ? "eye" : "eye.slash")
        }
        Divider()
        Button(role: .destructive) {
            shell.ask(.deletePixie(pixie.id))
        } label: {
            Label("Delete…", systemImage: Icon.trash)
        }
    }
}

/// A team's menu: Rename, Change handle, Set leader, Delete team.
struct TeamActions: View {
    let section: PixieTeamSection
    @Environment(Shell.self) private var shell

    var body: some View {
        Button {
            shell.ask(.renameTeam(section.id))
        } label: {
            Label("Rename…", systemImage: Icon.edit)
        }
        Button {
            shell.ask(.teamHandle(section.id))
        } label: {
            Label("Change handle…", systemImage: "at")
        }
        Menu {
            ForEach(section.members) { member in
                Button {
                    shell.updateTeam(section.id, UpdatePixieTeamRequest(leaderID: member.id))
                } label: {
                    TeamChoice(name: member.name, chosen: section.isLeader(member))
                }
            }
        } label: {
            Label("Set leader", systemImage: "star")
        }
        .disabled(section.members.isEmpty)
        Divider()
        Button(role: .destructive) {
            shell.ask(.deleteTeam(section.id))
        } label: {
            Label("Delete team…", systemImage: Icon.trash)
        }
    }
}

/// A menu choice, checked when it is the current one.
private struct TeamChoice: View {
    let name: String
    let chosen: Bool

    var body: some View {
        if chosen {
            Label(name, systemImage: Icon.check)
        } else {
            Text(name)
        }
    }
}

extension View {
    /// The Pixies list's questions: a team's name or handle to type, or a delete to
    /// confirm.
    fileprivate func pixiePrompts() -> some View {
        modifier(PixiePrompts())
    }
}

private struct PixiePrompts: ViewModifier {
    @Environment(Shell.self) private var shell

    func body(content: Content) -> some View {
        let prompt = shell.pixiePrompt
        let confirmation = prompt.flatMap(confirmation)
        content
            // A sheet of its own rather than an alert, so the field starts with the
            // team's name or handle, selected.
            .sheet(
                isPresented: Binding(
                    get: { prompt?.isTyped == true }, set: { if !$0 { shell.pixiePrompt = nil } })
            ) {
                if let prompt {
                    PixiePromptSheet(prompt: prompt)
                }
            }
            .confirmationDialog(
                confirmation?.title ?? "",
                isPresented: Binding(
                    get: { confirmation != nil }, set: { if !$0 { shell.pixiePrompt = nil } }),
                titleVisibility: .visible
            ) {
                Button("Delete", role: .destructive) { shell.answerPixiePrompt() }
                Button("Cancel", role: .cancel) { shell.pixiePrompt = nil }
            } message: {
                Text(confirmation?.message ?? "")
            }
    }

    private func confirmation(_ prompt: PixiePrompt) -> PixieConfirmation? {
        switch prompt {
        case .deletePixie(let id): shell.pixie(id).map { PixieConfirm.deletePixie($0.name) }
        case .deleteTeam(let id): shell.pixies.team(id).map { PixieConfirm.deleteTeam($0.name) }
        default: nil
        }
    }
}

/// New team, Rename team or Change handle: one field, starting with what is there,
/// selected, so typing replaces it.
struct PixiePromptSheet: View {
    let prompt: PixiePrompt
    @Environment(Shell.self) private var shell
    @FocusState private var focused: Bool
    @State private var selection: TextSelection?

    var body: some View {
        @Bindable var shell = shell
        VStack(alignment: .leading, spacing: 10) {
            Text(prompt.title)
                .font(.ui(TypeSize.body, .semibold))
                .foregroundStyle(Palette.t1)
            TextField(prompt.field, text: $shell.pixiePromptText, selection: $selection)
                .textFieldStyle(.roundedBorder)
                .font(.ui(TypeSize.reading))
                .focused($focused)
                .onSubmit { shell.answerPixiePrompt() }
            if let note = prompt.note {
                Text(note)
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: 6) {
                Spacer(minLength: 0)
                Button("Cancel", role: .cancel) { shell.pixiePrompt = nil }
                    .keyboardShortcut(.cancelAction)
                    .buttonStyle(.nest())
                Button(prompt.action) { shell.answerPixiePrompt() }
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.nest(.primary))
            }
            .padding(.top, 4)
        }
        .padding(18)
        .frame(width: 320)
        .onAppear {
            let text = shell.pixiePromptText
            selection = TextSelection(range: text.startIndex..<text.endIndex)
            focused = true
        }
    }
}
