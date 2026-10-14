import NestKit
import SwiftUI

// What a pixie's Nest tools leave in chats (B41): who started a chat, who sent a
// message, the report when its chats finish and the live cards in its own chat.

/// "Started by Scout" with Scout's mascot; with `compact`, only the mascot and the name.
struct StartedByLabel: View {
    let label: PixieLabel
    var compact = false

    var body: some View {
        HStack(spacing: 4) {
            if let pixie = label.pixie {
                SpriteView(mascot: pixie.mascot, color: pixie.color, size: 11)
            }
            Text(compact ? label.pixie?.name ?? label.text : label.text)
                .lineLimit(1)
                .truncationMode(.tail)
        }
        .font(.ui(TypeSize.meta))
        .foregroundStyle(Palette.t3)
        .help(label.text)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(label.text)
    }
}

/// A sidebar row's mark for a chat a pixie started: its mascot, with "Started by Scout"
/// as the tooltip and spoken label; the row's title keeps its room.
struct StartedByMark: View {
    let label: PixieLabel

    var body: some View {
        Group {
            if let pixie = label.pixie {
                SpriteView(mascot: pixie.mascot, color: pixie.color, size: 11)
            } else {
                Image(systemName: "sparkle")
                    .font(.system(size: 9))
                    .foregroundStyle(Palette.t3)
            }
        }
        .help(label.text)
        .accessibilityLabel(label.text)
    }
}

/// "from Scout" with its mascot, above a message the pixie sent.
struct FromPixieLabel: View {
    let label: PixieLabel

    var body: some View {
        HStack(spacing: 4) {
            if let pixie = label.pixie {
                SpriteView(mascot: pixie.mascot, color: pixie.color, size: 11)
            }
            Text(label.text)
        }
        .font(.ui(TypeSize.meta))
        .foregroundStyle(Palette.t3)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(label.text)
    }
}

/// The daemon's report that the chats a pixie started finished: a quiet row, not the
/// user's bubble.
struct ReportBackRow: View {
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: "checklist").font(.system(size: 10))
                Text(ReportBack.title).font(.ui(TypeSize.meta, .medium))
            }
            .foregroundStyle(Palette.t2)
            Text(ReportBack.lines(text))
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .lineSpacing(2)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .softFill()
        .accessibilityElement(children: .combine)
    }
}

/// A card in a pixie's chat: a chat or pull request live from the sessions store (B41), a
/// report, reply choices or a suggested habit (B42).
struct PixieCardView: View {
    let card: PixieCard
    /// The pixie's chat the card is in.
    let chat: String
    /// A later user message spent a choices card's buttons.
    var answered = false
    @Environment(Shell.self) private var shell

    var body: some View {
        switch card.kind {
        case .session, .pr:
            if let session = card.sessionID.flatMap(shell.sessions.session) {
                if card.kind == .session {
                    SessionCard(session: session)
                } else {
                    PullRequestCard(session: session)
                }
            } else {
                SystemLine(text: "A chat that is no longer here")
                    .frame(maxWidth: .infinity)
            }
        case .report:
            if let report = card.reportID.flatMap(shell.reports.report) {
                ReportCard(report: report)
            } else {
                SystemLine(text: ReportText.missing)
                    .frame(maxWidth: .infinity)
            }
        case .choices:
            if let pixie {
                ChoicesCard(options: card.options ?? [], pixie: pixie, answered: answered)
            }
        case .habitSuggestion:
            if let pixie, let habit = card.habit {
                HabitSuggestionCard(suggestion: habit, pixie: pixie)
            }
        case .unknown:
            EmptyView()
        }
    }

    /// The pixie whose chat this is.
    private var pixie: String? {
        shell.pixies.pixies.first { $0.chatSessionID == chat }?.id
            ?? shell.sessions.session(chat)?.pixieID
    }
}

/// A chat the pixie started: its title, project and live state, and Open.
private struct SessionCard: View {
    let session: Session
    @Environment(Shell.self) private var shell

    var body: some View {
        let tone = shell.tone(of: session)
        HStack(alignment: .center, spacing: 10) {
            VStack(alignment: .leading, spacing: 4) {
                Text(session.title)
                    .font(.ui(TypeSize.ui, .medium))
                    .foregroundStyle(Palette.t1)
                    .lineLimit(1)
                HStack(spacing: 8) {
                    HStack(spacing: 5) {
                        ProjectIcon(name: session.repo, size: 12)
                        Text(session.repo).lineLimit(1)
                    }
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                    StatusLabel(
                        tone: tone, label: shell.sessions.cardState(of: session),
                        hollow: shell.isHollow(session))
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            OpenButton(session: session)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .softFill()
        .accessibilityElement(children: .contain)
        .accessibilityLabel(
            "\(session.title), \(session.repo), \(shell.sessions.cardState(of: session))")
    }
}

/// A chat's pull request: number and title, checks and review, and Open.
private struct PullRequestCard: View {
    let session: Session
    @Environment(Shell.self) private var shell

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            VStack(alignment: .leading, spacing: 4) {
                if let pr = session.pr {
                    HStack(spacing: 6) {
                        Image(systemName: Icon.pullRequest)
                            .font(.system(size: 10, weight: .medium))
                            .foregroundStyle(Palette.t3)
                        Text("#\(String(pr.number)) \(pr.title)")
                            .font(.ui(TypeSize.ui, .medium))
                            .foregroundStyle(Palette.t1)
                            .lineLimit(1)
                    }
                    let dot = PRBadge.dot(of: pr)
                    HStack(spacing: 5) {
                        StatusDot(tone: dot.tone, hollow: dot.hollow)
                        Text(
                            "\(PRBadge.checksSummary(pr.checks)) · \(PRBadge.reviewLabel(pr.reviewDecision)) · \(PRBadge.stateLabel(pr.state))"
                        )
                        .lineLimit(1)
                    }
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                } else {
                    Text(session.title)
                        .font(.ui(TypeSize.ui, .medium))
                        .foregroundStyle(Palette.t1)
                        .lineLimit(1)
                    Text("No pull request yet")
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if let pr = session.pr {
                Button {
                    shell.openOnGitHub(pr.url)
                } label: {
                    Image(systemName: Icon.open)
                }
                .buttonStyle(.nest(.plain, iconOnly: true))
                .help("Open on GitHub")
                .accessibilityLabel("Open on GitHub")
            }
            OpenButton(session: session)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .softFill()
        .accessibilityElement(children: .contain)
    }
}

/// Opens the chat in its project.
private struct OpenButton: View {
    let session: Session
    @Environment(Shell.self) private var shell

    var body: some View {
        Button("Open") { shell.reveal(chat: session.id, in: session.repo) }
            .buttonStyle(.nest(.soft))
            .fixedSize()
            .help("Open \(session.title)")
    }
}

/// A pixie's report: its severity mark (info grey, warning amber, needs action red),
/// title, body, link and the habit it came from.
struct ReportCard: View {
    let report: PixieReport
    @Environment(Shell.self) private var shell

    var body: some View {
        let tone = report.severity.tone
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                StatusDot(tone: tone)
                Text(report.severity.label)
                    .font(.ui(TypeSize.meta, .medium))
                    .foregroundStyle(tone == .done ? Palette.t3 : tone.color)
                Spacer(minLength: 8)
                if let from = ReportText.from(
                    report, habits: shell.habits.habits(of: report.pixieID))
                {
                    Text(from)
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }
            }
            Text(report.title)
                .font(.ui(TypeSize.ui, .semibold))
                .foregroundStyle(Palette.t1)
                .fixedSize(horizontal: false, vertical: true)
            if !report.body.isEmpty {
                Text(report.body)
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t2)
                    .lineSpacing(2)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let link = report.link, SafeLink.url(link) != nil {
                Button {
                    shell.openOnGitHub(link)
                } label: {
                    Label(link, systemImage: Icon.open)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
                .buttonStyle(.plain)
                .pointerStyle(.link)
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.link)
                .help("Open \(link)")
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .softFill()
        .overlay(alignment: .leading) {
            if tone != .done {
                Capsule()
                    .fill(tone.color)
                    .frame(width: 3)
                    .padding(.vertical, 10)
            }
        }
        .accessibilityElement(children: .combine)
        // A report from a habit names its habit, read once.
        .task(id: report.habitID) {
            if report.habitID != nil, shell.habits.habits(of: report.pixieID) == nil {
                try? await shell.habits.load(report.pixieID)
            }
        }
    }
}

/// Up to four replies; a click sends one as the user's message, and the buttons are spent.
private struct ChoicesCard: View {
    let options: [String]
    let pixie: String
    let answered: Bool
    @Environment(Shell.self) private var shell
    @State private var sent: String?

    var body: some View {
        let spent = answered || sent != nil
        FlowLayout(spacing: 6) {
            ForEach(Array(options.prefix(4).enumerated()), id: \.offset) { _, option in
                Button(option) {
                    sent = option
                    shell.sendChoice(option, to: pixie)
                }
                .buttonStyle(.nest(sent == option ? .primary : .soft))
                .disabled(spent)
                .help(spent ? "Already answered" : "Reply \"\(option)\"")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Reply choices")
    }
}

/// A habit the pixie proposes: its name, schedule and triggers, the instructions folded,
/// and Start, which creates and enables it; "Started" once a habit of that name exists.
private struct HabitSuggestionCard: View {
    let suggestion: HabitSuggestion
    let pixie: String
    @Environment(Shell.self) private var shell
    @State private var showsPrompt = false
    @State private var starting = false

    var body: some View {
        let started = suggestion.isStarted(among: shell.habits.habits(of: pixie))
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: "repeat").font(.system(size: 10, weight: .medium))
                Text("Suggested habit").font(.ui(TypeSize.meta, .medium))
            }
            .foregroundStyle(Palette.t3)
            Text(suggestion.name)
                .font(.ui(TypeSize.ui, .semibold))
                .foregroundStyle(Palette.t1)
            if !suggestion.summary.isEmpty {
                Text(suggestion.summary)
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Button {
                withAnimation(.smooth(duration: 0.2)) { showsPrompt.toggle() }
            } label: {
                HStack(spacing: 4) {
                    Image(systemName: Icon.chevron)
                        .font(.system(size: 8, weight: .semibold))
                        .rotationEffect(.degrees(showsPrompt ? 0 : -90))
                    Text(showsPrompt ? "Hide instructions" : "Show instructions")
                }
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .pointerStyle(.link)
            if showsPrompt {
                Text(suggestion.prompt)
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t2)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack {
                if started {
                    StatusLabel(tone: .review, label: "Started")
                } else {
                    Button {
                        starting = true
                        Task {
                            _ = await shell.startSuggestedHabit(suggestion, for: pixie)
                            starting = false
                        }
                    } label: {
                        Label("Start", systemImage: "play.fill")
                    }
                    .buttonStyle(.nest(.primary))
                    .disabled(starting)
                    .help("Create this habit and turn it on")
                }
            }
            .padding(.top, 2)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .softFill()
        .accessibilityElement(children: .contain)
        // Whether it was started already: a habit of the same name.
        .task(id: pixie) {
            if shell.habits.habits(of: pixie) == nil {
                try? await shell.habits.load(pixie)
            }
        }
    }
}

/// The message that starts a pixie's turn after a habit reported: a quiet row like the
/// report that its chats finished, not the user's bubble.
struct HabitReportRow: View {
    let text: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Image(systemName: Icon.bell).font(.system(size: 10))
            Text(HabitReportNote.title).font(.ui(TypeSize.meta, .medium))
            Text(HabitReportNote.text(text))
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .lineLimit(2)
                .textSelection(.enabled)
        }
        .foregroundStyle(Palette.t2)
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .softFill()
        .accessibilityElement(children: .combine)
    }
}
