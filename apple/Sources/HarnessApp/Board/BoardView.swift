import HarnessKit
import SwiftUI

/// The project's chats as four columns: Running, Waiting on you, Ready for review, Done.
struct BoardView: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let columns = shell.sessions.board(in: shell.project ?? "")
        HStack(spacing: 10) {
            ForEach(BoardColumn.allCases, id: \.self) { column in
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
    @Environment(\.glass) private var glass

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 7) {
                StatusDot(tone: column.tone, pulses: false)
                Text(column.title).font(.ui(TypeSize.callout, .semibold))
                Spacer()
                Text("\(sessions.count)")
                    .font(.ui(TypeSize.label, .semibold))
                    .foregroundStyle(Palette.t3)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 1)
                    .background(Palette.fill, in: Capsule())
            }
            .padding(EdgeInsets(top: 4, leading: 6, bottom: 10, trailing: 6))
            ScrollView {
                LazyVStack(spacing: 8) {
                    if sessions.isEmpty {
                        Text("Nothing here")
                            .font(.ui(TypeSize.small))
                            .foregroundStyle(Palette.t3)
                            .padding(.vertical, 18)
                    }
                    ForEach(sessions) { session in
                        BoardCard(session: session)
                    }
                }
                .padding(2)
            }
            .scrollIndicators(.never)
        }
        .padding(10)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .panelGlass(radius: glass.radius.panel, tint: .clear, raised: false)
    }
}

private struct BoardCard: View {
    let session: Session
    @Environment(Shell.self) private var shell
    @Environment(\.glass) private var glass
    @State private var hovering = false

    var body: some View {
        let goals = shell.activity.goals(session: session.id)
        let approval = shell.approvals.pending(session: session.id).first
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                StatusDot(
                    tone: shell.tone(of: session), hollow: shell.isHollow(session), pulses: false)
                Text(shell.statusLabel(of: session))
                Spacer()
                TimelineView(.periodic(from: .now, by: 30)) { context in
                    Text(Elapsed.short(from: session.updatedAt, to: context.date)).monospacedDigit()
                }
            }
            .font(.ui(TypeSize.caption))
            .foregroundStyle(Palette.t3)
            Text(session.title)
                .font(.ui(TypeSize.body, .semibold))
                .foregroundStyle(Palette.t1)
                .lineSpacing(2)
            if let pr = session.pr {
                PRChip(session: session.id, pr: pr)
            }
            detail(approval: approval)
            if !goals.tasks.isEmpty {
                Text("\(goals.completed) of \(goals.tasks.count) tasks")
                    .font(.ui(TypeSize.caption))
                    .foregroundStyle(Palette.t3)
            }
            Button {
                shell.openChat(session.id)
            } label: {
                Label("Open", systemImage: Icon.open)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.harness(height: 24))
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .panelGlass(radius: glass.radius.card)
        .offset(y: hovering ? -2 : 0)
        .onHover { hover in withAnimation(.smooth(duration: 0.2)) { hovering = hover } }
    }

    @ViewBuilder private func detail(approval: Approval?) -> some View {
        if session.state == .running || session.state == .starting {
            LiveBox(icon: nil, text: shell.liveActivity(of: session.id), waiting: false)
        } else if let approval, approval.kind != .review, approval.kind != .merge {
            let text =
                approval.question?.questions.first?.question
                ?? approval.permission.map {
                    "\($0.tool) \(ToolSummary.argument(tool: $0.tool, input: $0.input))"
                } ?? (approval.kind == .plan ? "Plan ready for review" : approval.title)
            LiveBox(
                icon: approval.kind == .question
                    ? Icon.question : approval.kind == .plan ? Icon.plan : Icon.shield,
                text: text, waiting: true)
        } else if let review = approval?.review {
            DiffStat(additions: review.additions, deletions: review.deletions, files: review.files)
        }
    }
}

/// One line of what the agent is doing, or what it waits for.
private struct LiveBox: View {
    let icon: String?
    let text: String
    let waiting: Bool

    var body: some View {
        HStack(spacing: 7) {
            if let icon {
                Image(systemName: icon).font(.system(size: 11))
            } else {
                Spinner()
            }
            Text(text).lineLimit(1).truncationMode(.tail)
        }
        .font(.mono(TypeSize.caption))
        .foregroundStyle(waiting ? StatusTone.waiting.textColor : Palette.t2)
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            waiting ? StatusTone.waiting.soft : Palette.fill, in: RoundedRectangle(cornerRadius: 8))
    }
}
