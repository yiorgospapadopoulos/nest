import NestKit
import SwiftUI

/// The activity panel: Needs you and Goals cards that share its height; folds into a rail
/// with counts. Agents show in the sidebar tree (B72).
struct RightPanel: View {
    static let width = 320.0
    static let railWidth = 56.0

    @Environment(Shell.self) private var shell

    var body: some View {
        let state = shell.projectState
        let counts = PanelCounts(shell: shell)
        Group {
            if state.rightCollapsed {
                ActivityRail(counts: counts)
                    .frame(width: Self.railWidth)
                    .frame(maxHeight: .infinity, alignment: .top)
            } else {
                VStack(spacing: 0) {
                    ForEach(RightCard.allCases, id: \.self) { card in
                        if card != RightCard.allCases.first {
                            Separator()
                        }
                        CardView(card: card, open: state.openCards.contains(card), counts: counts)
                    }
                }
                .frame(width: Self.width)
            }
        }
        // Folded cards stack at the top rather than meeting in the middle.
        .frame(maxHeight: .infinity, alignment: .top)
        .sideSurface()
        .task(id: inFlightKey) { await loadActivity() }
    }

    /// Reloads the project's goals, and agents, tasks and background work, when the
    /// project or the watched chats change or the daemon connects again.
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
        if let project = shell.project {
            try? await shell.activity.loadGoals(
                repo: project, sessions: shell.sessions.sessions(in: project))
        }
        for id in watched {
            try? await shell.activity.load(session: id)
        }
    }
}

/// The numbers on the card headers and rail buttons.
@MainActor
struct PanelCounts {
    let needs: Int
    let goals: Int

    init(shell: Shell) {
        let project = shell.project ?? ""
        needs = shell.sessions.attention(of: project)
        goals = shell.activity.goalEntries(shell.sessions.sessions(in: project)).count
    }

    func count(_ card: RightCard) -> Int {
        switch card {
        case .needsYou: needs
        case .goals: goals
        }
    }
}

extension RightCard {
    var title: String {
        switch self {
        case .needsYou: "Needs you"
        case .goals: "Goals"
        }
    }

    var icon: String {
        switch self {
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

    var body: some View {
        VStack(spacing: 0) {
            Button {
                shell.update { $0.toggleCard(card) }
            } label: {
                HStack(spacing: 7) {
                    Text(card.title)
                    CountBadge(
                        count: counts.count(card), urgent: card == .needsYou && counts.needs > 0)
                    Spacer()
                    Image(systemName: Icon.chevron)
                        .font(.system(size: 9, weight: .semibold))
                        .rotationEffect(.degrees(open ? 0 : -90))
                }
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .padding(.horizontal, 14)
                .frame(height: Metrics.headerHeight)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .pointerStyle(.link)
            .accessibilityLabel("\(card.title), \(counts.count(card))")
            .accessibilityAddTraits(open ? .isSelected : [])
            if open {
                ScrollView {
                    Group {
                        switch card {
                        case .needsYou: NeedsCard()
                        case .goals: GoalsCard()
                        }
                    }
                    // Rows' chevrons line up under the header's (B77).
                    .padding(.horizontal, 8)
                    .padding(.bottom, 10)
                }
                .scrollIndicators(.never)
                .transition(.opacity)
            }
        }
        .frame(maxHeight: open ? .infinity : Metrics.headerHeight, alignment: .top)
    }
}

private struct ActivityRail: View {
    let counts: PanelCounts
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(spacing: 6) {
            Button {
                shell.update { $0.rightCollapsed = false }
            } label: {
                Image(systemName: Icon.rightPanel).font(.system(size: 13))
            }
            .buttonStyle(RailButtonStyle())
            .help("Expand panel")
            .accessibilityLabel("Expand panel")
            Separator().frame(width: 24).padding(.vertical, 4)
            ForEach(RightCard.allCases, id: \.self) { card in
                let count = counts.count(card)
                Button {
                    shell.update { $0.showCard(card) }
                } label: {
                    Image(systemName: card.icon).font(.system(size: 13))
                }
                .buttonStyle(RailButtonStyle())
                .overlay(alignment: .topTrailing) {
                    if count > 0 {
                        CountBadge(count: count, urgent: card == .needsYou)
                            .offset(x: 6, y: -4)
                    }
                }
                .help(card.title)
                .accessibilityLabel("\(card.title), \(count)")
            }
        }
        .padding(.vertical, 8)
    }
}

struct RailButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        HoverReader { hovering in
            configuration.label
                .foregroundStyle(hovering ? Palette.t1 : Palette.t3)
                .frame(width: 30, height: 30)
                .background(
                    hovering || configuration.isPressed ? Palette.soft : .clear,
                    in: .rounded(Radius.row)
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
