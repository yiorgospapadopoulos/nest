import HarnessKit
import SwiftUI

/// The activity panel: Agents, Needs you and Goals cards that share its height; folds
/// into a rail with counts.
struct RightPanel: View {
    static let width = 320.0
    static let railWidth = 56.0

    @Environment(Shell.self) private var shell
    @Environment(\.glass) private var glass

    var body: some View {
        let state = shell.projectState
        let counts = PanelCounts(shell: shell)
        Group {
            if state.rightCollapsed {
                ActivityRail(counts: counts)
                    .frame(width: Self.railWidth)
                    .frame(maxHeight: .infinity, alignment: .top)
                    .panelGlass(radius: glass.radius.panel)
            } else {
                VStack(spacing: glass.spacing.gap) {
                    ForEach(RightCard.allCases, id: \.self) { card in
                        CardView(card: card, open: state.openCards.contains(card), counts: counts)
                    }
                }
                .frame(width: Self.width)
            }
        }
        .task(id: inFlightKey) { await loadActivity() }
    }

    /// Reloads agents, tasks and background work when the watched chats change or the
    /// daemon connects again.
    private var inFlightKey: String {
        let connected = shell.app.connection == .connected
        return ([shell.project ?? "", "\(connected)"] + watched).joined(separator: ",")
    }

    /// Busy chats, open panes, and idle chats whose background work may still run.
    private var watched: [String] {
        let project = shell.project ?? ""
        let open = shell.projectState.layout.leaves.filter {
            PaneKind(paneID: $0) == .chat && !shell.isDraft($0) && !shell.isClaudeChatPane($0)
        }
        return shell.activity.watchList(
            shell.sessions.sessions(in: project), open: open, now: Date())
    }

    private func loadActivity() async {
        for id in watched {
            try? await shell.activity.load(session: id)
        }
    }
}

/// The numbers on the card headers and rail buttons.
@MainActor
struct PanelCounts {
    let agents: Int
    let needs: Int
    let goals: Int

    init(shell: Shell) {
        let project = shell.project ?? ""
        let ids = shell.sessions.sessions(in: project).map(\.id)
        agents = shell.activity.runningAgents(in: ids)
        needs = shell.sessions.attention(of: project)
        let chats = shell.projectState.layout.leaves.filter { PaneKind(paneID: $0) == .chat }
        goals = chats.filter { !shell.isDraft($0) }.count
    }

    func count(_ card: RightCard) -> Int {
        switch card {
        case .agents: agents
        case .needsYou: needs
        case .goals: goals
        }
    }
}

extension RightCard {
    var title: String {
        switch self {
        case .agents: "Agents"
        case .needsYou: "Needs you"
        case .goals: "Goals"
        }
    }

    var icon: String {
        switch self {
        case .agents: Icon.agent
        case .needsYou: Icon.bell
        case .goals: Icon.goals
        }
    }
}

private struct CardView: View {
    let card: RightCard
    let open: Bool
    let counts: PanelCounts
    @Environment(Shell.self) private var shell
    @Environment(\.glass) private var glass

    var body: some View {
        VStack(spacing: 0) {
            Button {
                shell.update { $0.toggleCard(card) }
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: card.icon)
                        .font(.system(size: 13))
                        .foregroundStyle(Palette.t2)
                        .frame(width: 16)
                    Text(card.title)
                        .font(.ui(TypeSize.body, .semibold))
                        .foregroundStyle(Palette.t1)
                    CountBadge(
                        count: counts.count(card), urgent: card == .needsYou && counts.needs > 0)
                    Spacer()
                    Image(systemName: Icon.chevron)
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(Palette.t3)
                        .rotationEffect(.degrees(open ? 0 : -90))
                }
                .padding(.leading, 14)
                .padding(.trailing, 12)
                .frame(height: 44)
                .contentShape(Rectangle())
            }
            .buttonStyle(RowHoverStyle(radius: glass.radius.pane))
            .accessibilityLabel("\(card.title), \(counts.count(card))")
            .accessibilityAddTraits(open ? .isSelected : [])
            if open {
                ScrollView {
                    Group {
                        switch card {
                        case .agents: AgentsCard()
                        case .needsYou: NeedsCard()
                        case .goals: GoalsCard()
                        }
                    }
                    .padding(.horizontal, 10)
                    .padding(.bottom, 10)
                }
                .scrollIndicators(.never)
                .transition(.opacity)
            }
        }
        .frame(maxHeight: open ? .infinity : 44, alignment: .top)
        .panelGlass(radius: glass.radius.pane)
    }
}

private struct ActivityRail: View {
    let counts: PanelCounts
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(spacing: 8) {
            Button {
                shell.update { $0.rightCollapsed = false }
            } label: {
                Image(systemName: Icon.rightPanel).font(.system(size: 15))
            }
            .buttonStyle(RailButtonStyle())
            .help("Expand panel")
            .accessibilityLabel("Expand panel")
            Rectangle().fill(Palette.hair2).frame(width: 24, height: 1).padding(.vertical, 4)
            ForEach(RightCard.allCases, id: \.self) { card in
                let count = counts.count(card)
                Button {
                    shell.update { $0.showCard(card) }
                } label: {
                    Image(systemName: card.icon).font(.system(size: 15))
                }
                .buttonStyle(RailButtonStyle())
                .overlay(alignment: .topTrailing) {
                    if count > 0 {
                        CountBadge(count: count, urgent: card == .needsYou, size: 17)
                            .offset(x: 5, y: -5)
                    }
                }
                .help(card.title)
                .accessibilityLabel("\(card.title), \(count)")
            }
        }
        .padding(.vertical, 10)
    }
}

struct RailButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        HoverReader { hovering in
            configuration.label
                .foregroundStyle(hovering ? Palette.t1 : Palette.t2)
                .frame(width: 38, height: 38)
                .background(
                    hovering ? Palette.fill2 : Palette.fill,
                    in: RoundedRectangle(cornerRadius: 12, style: .continuous)
                )
                .contentShape(Rectangle())
                .pointerStyle(.link)
        }
    }
}

/// A chat title that opens the chat, as card group headers show it.
struct ChatLink: View {
    let chat: String
    let title: String
    @Environment(Shell.self) private var shell
    @State private var hovering = false

    var body: some View {
        Button {
            shell.openChat(chat)
        } label: {
            Text(title)
                .lineLimit(1)
                .underline(hovering)
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .onHover { hovering = $0 }
        .help("Open this chat")
    }
}

/// A pixie's sprite and name that open its page, where its chat shows.
struct PixieLink: View {
    let id: String
    @Environment(Shell.self) private var shell
    @State private var hovering = false

    var body: some View {
        let pixie = shell.pixies.pixies.first { $0.id == id }
        Button {
            shell.revealPixie(id)
        } label: {
            HStack(spacing: 5) {
                SpriteView(
                    mascot: pixie?.mascot ?? .invader, color: pixie?.color ?? PixieColor.standard,
                    size: 14)
                Text(pixie?.name ?? "Pixie")
                    .lineLimit(1)
                    .underline(hovering)
            }
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .onHover { hovering = $0 }
        .help("Open this pixie")
    }
}
