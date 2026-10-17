import NestKit
import SwiftUI

/// The project's chats as four columns: Running, Waiting on you, Ready for review, Done,
/// split by dividers over the pane's scanlines.
struct BoardView: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let columns = shell.sessions.board(in: shell.project ?? "")
        HStack(spacing: 0) {
            ForEach(BoardColumn.allCases, id: \.self) { column in
                if column != BoardColumn.allCases.first {
                    Separator(axis: .vertical)
                }
                ColumnView(column: column, sessions: columns[column] ?? [])
            }
        }
    }
}

extension BoardColumn {
    var tone: StatusTone {
        switch self {
        case .running: .running
        case .waiting: .waiting
        case .review: .review
        case .done: .done
        }
    }
}

private struct ColumnView: View {
    let column: BoardColumn
    let sessions: [Session]

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 7) {
                // A label for the column, not a live item: a plain dot even for Running.
                StatusDot(tone: column.tone)
                Text(column.title)
                Text("\(sessions.count)").monospacedDigit()
                Spacer(minLength: 0)
            }
            .font(.ui(TypeSize.meta))
            .foregroundStyle(Palette.t3)
            .padding(.horizontal, 14)
            .frame(height: Metrics.headerHeight)
            ScrollView {
                LazyVStack(spacing: 8) {
                    if sessions.isEmpty {
                        Text("Nothing here")
                            .font(.ui(TypeSize.meta))
                            .foregroundStyle(Palette.t3)
                            .padding(.vertical, 18)
                    }
                    ForEach(sessions) { session in
                        BoardCard(session: session)
                    }
                }
                .padding(.horizontal, 10)
                .padding(.top, 2)
                .padding(.bottom, 10)
            }
            .scrollIndicators(.never)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    }
}

private struct BoardCard: View {
    let session: Session
    @Environment(Shell.self) private var shell

    var body: some View {
        let goals = shell.activity.goals(session: session.id)
        let approval = shell.approvals.pending(session: session.id).first
        let tone = shell.tone(of: session)
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 6) {
                Text(shell.statusLabel(of: session))
                    .foregroundStyle(Self.wordColor(tone))
                Spacer()
                TimelineView(.periodic(from: .now, by: 30)) { context in
                    Text(Elapsed.short(from: session.updatedAt, to: context.date)).monospacedDigit()
                }
            }
            .font(.ui(TypeSize.meta))
            .foregroundStyle(Palette.t3)
            Text(session.title)
                .font(.ui(TypeSize.reading, .medium))
                .foregroundStyle(Palette.t1)
                .fixedSize(horizontal: false, vertical: true)
            if let pr = session.pr {
                PRChip(session: session.id, pr: pr)
            }
            detail(approval: approval)
            if !goals.tasks.isEmpty {
                Text("\(goals.completed) of \(goals.tasks.count) tasks")
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t3)
            }
            Button {
                shell.openChat(session.id)
            } label: {
                Text("Open")
            }
            .buttonStyle(.nest())
            .padding(.top, 3)
            .accessibilityLabel("Open \(session.title)")
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .softFill()
    }

    /// The status word: coloured only when it needs the user or waits for review.
    static func wordColor(_ tone: StatusTone) -> Color {
        switch tone {
        case .waiting, .review, .failed: tone.color
        default: Palette.t3
        }
    }

    @ViewBuilder private func detail(approval: Approval?) -> some View {
        if session.state == .running || session.state == .starting {
            LiveLine(icon: nil, text: shell.liveActivity(of: session.id))
        } else if let approval, approval.kind != .review, approval.kind != .merge {
            let text =
                approval.question?.questions.first?.question
                ?? approval.permission.map {
                    "\($0.tool)  \(ToolSummary.argument(tool: $0.tool, input: $0.input))"
                } ?? (approval.kind == .plan ? "Plan ready for review" : approval.title)
            LiveLine(
                icon: approval.kind == .question
                    ? Icon.question : approval.kind == .plan ? Icon.plan : Icon.shield,
                text: text)
        } else if let review = approval?.review {
            DiffStat(additions: review.additions, deletions: review.deletions, files: review.files)
        }
    }
}

/// One mono line of what the agent is doing, or what it waits for.
private struct LiveLine: View {
    let icon: String?
    let text: String

    var body: some View {
        HStack(spacing: 6) {
            if let icon {
                Image(systemName: icon)
                    .font(.system(size: 10))
                    .foregroundStyle(Palette.t3)
            } else {
                Fireflies(height: 10)
            }
            Text(text)
                .foregroundStyle(icon == nil ? Palette.t3 : Palette.t2)
                .lineLimit(1)
                .truncationMode(.tail)
        }
        .font(.mono(TypeSize.meta))
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
