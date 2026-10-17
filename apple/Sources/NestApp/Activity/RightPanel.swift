import NestKit
import SwiftUI

/// The activity panel: Needs you and Goals cards that share its height; squeezes into an
/// accent hairline (B83), the two fading over each other and clipped to the panel while
/// its width animates, as the sidebar does. Agents show in the sidebar tree (B72).
struct RightPanel: View {
    static let width = 320.0
    static let railWidth = 6.0

    @Environment(Shell.self) private var shell

    var body: some View {
        let state = shell.projectState
        let counts = PanelCounts(shell: shell)
        Group {
            if state.rightCollapsed {
                ActivityRail(needs: counts.needs)
                    .frame(width: Self.railWidth)
                    .frame(maxHeight: .infinity)
                    .transition(.opacity)
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
                .transition(.opacity)
            }
        }
        // Folded cards stack at the top rather than meeting in the middle.
        .frame(maxHeight: .infinity, alignment: .top)
        .sideSurface()
        .clipped()
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

/// The numbers on the card headers.
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
}

private struct CardView: View {
    let card: RightCard
    let open: Bool
    let counts: PanelCounts
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(spacing: 0) {
            HoverReader { hovering in
                HStack(spacing: 7) {
                    Text(card.title)
                    CountBadge(
                        count: counts.count(card), urgent: card == .needsYou && counts.needs > 0)
                    Spacer(minLength: 0)
                    Image(systemName: Icon.chevron)
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(hovering ? Palette.t1 : Palette.t3)
                        .rotationEffect(.degrees(open ? 0 : -90))
                }
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .padding(.horizontal, 14)
                .frame(maxWidth: .infinity)
                .frame(height: Metrics.headerHeight)
                // The whole bar is one target: the name, the count, the gap and the chevron
                // all fold the card, wherever the click lands.
                .contentShape(Rectangle())
                .onTapGesture { shell.update { $0.toggleCard(card) } }
                .pointerStyle(.link)
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("\(card.title), \(counts.count(card))")
            .accessibilityAddTraits(open ? [.isButton, .isSelected] : .isButton)
            .accessibilityAction { shell.update { $0.toggleCard(card) } }
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

/// The squeezed panel: a 2 point accent line down the middle of its strip, the whole
/// strip opening the panel.
private struct ActivityRail: View {
    let needs: Int
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent

    var body: some View {
        Rectangle()
            .fill(accent.accent)
            .frame(width: 2)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .contentShape(Rectangle())
            .pointerStyle(.link)
            .onTapGesture { shell.update { $0.rightCollapsed = false } }
            .help("Open details")
            .accessibilityElement()
            .accessibilityLabel("Open details")
            .accessibilityValue(needs > 0 ? "\(needs) need you" : "")
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { shell.update { $0.rightCollapsed = false } }
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
