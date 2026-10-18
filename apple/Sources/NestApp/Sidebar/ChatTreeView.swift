import NestKit
import SwiftUI

/// The tree under a chat in the sidebar (B46): "Pixies" with the pixies and teams the chat
/// called (they stay after they finish), then "Subagents" with those still working, joined
/// by tree lines. A row opens its work read-only; on hover a pixie's or team's "..." has
/// Send away, and a subagent has Stop.
struct ChatTreeView: View {
    let chat: String
    @Environment(Shell.self) private var shell

    var body: some View {
        let rows = ChatTree.rows(
            group: shell.chatPixies.group(session: chat),
            agents: shell.activity.agents(session: chat), pixies: shell.pixies.pixies,
            teams: shell.pixies.teams)
        if !rows.isEmpty {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(rows) { row in
                    ChatTreeLine(chat: chat, row: row)
                }
            }
            // The tree's line starts under the centre of the chat's status mark slot.
            .padding(.leading, SidebarRowMetrics.inset + 1.5)
            .padding(.bottom, 2)
        }
    }
}

private struct ChatTreeLine: View {
    let chat: String
    let row: ChatTreeRow
    @Environment(Shell.self) private var shell
    @Environment(\.revealsHoverControls) private var reveal
    @State private var hovering = false
    /// The width of a row's sprite, spinner or team icon, so names line up.
    private static let icon = 16.0

    var body: some View {
        let group = if case .group = row.kind { true } else { false }
        let controls = (hovering || reveal) && (sendAway != nil || stoppable != nil)
        HStack(spacing: 0) {
            TreeGuides(guides: row.guides, isLast: row.isLast)
                .frame(width: TreeGuides.step * Double(row.depth + 1))
            content
                .font(.ui(TypeSize.ui))
                .lineLimit(1)
                .padding(.horizontal, group ? 3 : 5)
                .padding(.trailing, controls ? 20 : 0)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
                .background(
                    hovering && !group ? Palette.soft : .clear, in: .rounded(Radius.row)
                )
                .overlay(alignment: .trailing) {
                    if controls {
                        if let sendAway {
                            RowActionsMenu(title: title) {
                                Button {
                                    shell.sendAway(sendAway, from: chat, name: title)
                                } label: {
                                    Label("Send away", systemImage: Icon.sendAway)
                                }
                            }
                            .padding(.trailing, 2)
                        } else if let stoppable {
                            StopTaskButton(chat: chat, task: stoppable)
                                .padding(.trailing, 3)
                        }
                    }
                }
                .contentShape(Rectangle())
                .pointerStyle(target == nil ? nil : .link)
                .onHover { hovering = $0 }
                .onTapGesture {
                    if let target {
                        shell.openWork(target)
                    }
                }
        }
        .frame(height: group ? 20 : 24)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibility)
        .accessibilityAddTraits(target == nil ? [] : .isButton)
        .accessibilityAction {
            if let target {
                shell.openWork(target)
            }
        }
        .help(help)
    }

    @ViewBuilder private var content: some View {
        switch row.kind {
        case .group(let group):
            Text(group.title)
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
        case .pixie(let pixie, let entry):
            HStack(spacing: 6) {
                SpriteView(
                    mascot: pixie.mascot, color: pixie.color, size: 12,
                    working: entry.state.isRunning, phaseKey: pixie.id
                )
                .frame(width: Self.icon)
                Text(pixie.name).foregroundStyle(Color(hex: pixie.color))
                Spacer(minLength: 4)
                StateMark(state: entry.state)
            }
        case .team(let team, let color, let entry):
            HStack(spacing: 6) {
                let icon = TeamIcon.cells(of: entry, pixies: shell.pixies.pixies)
                if icon.isEmpty {
                    Image(systemName: Icon.team)
                        .font(.system(size: 9, weight: .semibold))
                        .frame(width: Self.icon)
                        .foregroundStyle(color.map { Color(hex: $0) } ?? Palette.t2)
                } else {
                    TeamIconView(cells: icon)
                }
                Text(team.name)
                    .fontWeight(.medium)
                    .foregroundStyle(color.map { Color(hex: $0) } ?? Palette.t2)
                Text("@\(team.handle)")
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                Spacer(minLength: 4)
                StateMark(state: entry.state)
            }
        case .member(let pixie, let leader, let state, _):
            HStack(spacing: 6) {
                SpriteView(
                    mascot: pixie.mascot, color: pixie.color, size: 11,
                    working: state?.isRunning ?? false, phaseKey: pixie.id
                )
                .frame(width: Self.icon)
                Text(pixie.name).foregroundStyle(Palette.t1)
                if leader {
                    Text("Leader")
                        .font(.ui(TypeSize.micro, .medium))
                        .foregroundStyle(Palette.t2)
                        .padding(.horizontal, 4)
                        .padding(.vertical, 1)
                        .background(Palette.soft, in: .rounded(Radius.button))
                }
                Spacer(minLength: 4)
                StateMark(state: state)
            }
        case .subagent(let agent):
            HStack(spacing: 6) {
                Fireflies(height: 9)
                    .frame(width: Self.icon)
                Text(agent.name).foregroundStyle(Palette.t1)
                if let detail = agent.activity ?? agent.description {
                    Text(detail)
                        .font(.mono(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                        .truncationMode(.middle)
                }
            }
        }
    }

    /// What a click opens.
    private var target: WorkTarget? {
        switch row.kind {
        case .group: nil
        case .pixie(let pixie, _), .member(let pixie, _, _, _):
            .pixie(session: chat, pixieID: pixie.id)
        case .team(let team, _, let entry):
            .team(session: chat, teamID: team.id, members: entry.members.map(\.pixieID))
        case .subagent(let agent): .subagent(session: chat, toolUseID: agent.id)
        }
    }

    /// A subagent can be stopped by its Agent call; the turn goes on.
    private var stoppable: String? {
        if case .subagent(let agent) = row.kind { agent.id } else { nil }
    }

    /// A pixie or team leaves the chat's group with Send away; members go with their team.
    private var sendAway: ChatPixieEntry? {
        switch row.kind {
        case .pixie(_, let entry), .team(_, _, let entry): entry
        default: nil
        }
    }

    private var title: String {
        switch row.kind {
        case .group(let group): group.title
        case .pixie(let pixie, _), .member(let pixie, _, _, _): pixie.name
        case .team(let team, _, _): team.name
        case .subagent(let agent): agent.name
        }
    }

    private var accessibility: String {
        switch row.kind {
        case .group(let group): group.title
        case .pixie(let pixie, let entry): "Pixie \(pixie.name), \(entry.state.label)"
        case .team(let team, _, let entry):
            "Team \(team.name), @\(team.handle), \(entry.state.label)"
        case .member(let pixie, let leader, let state, _):
            "\(pixie.name)\(leader ? ", leader" : ""), \(ChatTree.label(of: state))"
        case .subagent(let agent): "Subagent \(agent.name), working"
        }
    }

    private var help: String {
        switch row.kind {
        case .group: ""
        case .subagent(let agent):
            "\(agent.name): \(agent.description ?? "working"). Click to read its transcript."
        default: "Open \(title)'s work in this chat"
        }
    }
}

/// A call's state at a row's end: a spinner while it works, else its word.
private struct StateMark: View {
    let state: PixieCallState?

    var body: some View {
        if state == .running {
            Fireflies(height: 9)
                .accessibilityHidden(true)
        } else {
            Text(ChatTree.label(of: state))
                .font(.ui(TypeSize.meta))
                .foregroundStyle(state == .failed ? StatusTone.failed.color : Palette.t3)
        }
    }
}

/// The tree lines left of a row: a line for each level above whose parent has more
/// children below, then this row's elbow.
struct TreeGuides: View {
    static let step = 12.0
    let guides: [Bool]
    let isLast: Bool

    var body: some View {
        Canvas { context, size in
            var path = Path()
            let middle = (size.height / 2).rounded() + 0.5
            for (level, continues) in guides.enumerated() where continues {
                let x = Self.step * Double(level) + 4.5
                path.move(to: CGPoint(x: x, y: 0))
                path.addLine(to: CGPoint(x: x, y: size.height))
            }
            let x = Self.step * Double(guides.count) + 4.5
            path.move(to: CGPoint(x: x, y: 0))
            path.addLine(to: CGPoint(x: x, y: isLast ? middle : size.height))
            path.move(to: CGPoint(x: x, y: middle))
            path.addLine(to: CGPoint(x: x + Self.step - 3, y: middle))
            context.stroke(path, with: .color(Palette.divider), lineWidth: 1)
        }
        .accessibilityHidden(true)
    }
}
