import NestKit
import SwiftUI

/// Pending approvals, failed checks and stuck chats of the project, one short row each
/// that opens to its actions (B77); resolved ones slide out.
struct NeedsCard: View {
    @Environment(Shell.self) private var shell
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        let pending = shell.approvals.pending(repo: shell.project ?? "")
        let failed = shell.sessions.checksFailed(in: shell.project ?? "")
        let stuck = shell.sessions.stuck(in: shell.project ?? "")
        VStack(alignment: .leading, spacing: 0) {
            if pending.isEmpty && failed.isEmpty && stuck.isEmpty {
                EmptyCard(icon: Icon.check, text: "Nothing needs you.", tone: .review)
                    .padding(.horizontal, -8)
                    .transition(.opacity)
            }
            // As on the iPhone: approvals, failed checks, then stuck chats.
            ForEach(NeedsYouSection.allCases, id: \.self) { section in
                switch section {
                case .approvals:
                    ForEach(pending) { approval in
                        ApprovalRow(approval: approval).transition(slideOut)
                    }
                case .checksFailed:
                    ForEach(failed) { session in
                        NeedsRow(
                            tone: .failed, session: session,
                            line: NeedsYouLine.checksFailed(session)
                        ) {
                            ChecksFailedCard(session: session)
                        }
                        .transition(slideOut)
                    }
                case .stuck:
                    ForEach(stuck) { session in
                        NeedsRow(
                            tone: .waiting, session: session, line: NeedsYouLine.stuck(session)
                        ) {
                            StuckCard(session: session)
                        }
                        .transition(slideOut)
                    }
                }
            }
        }
        .animation(
            reduceMotion ? nil : .smooth(duration: 0.3),
            value: pending.map(\.id) + failed.map(\.id) + stuck.map { "stuck-\($0.id)" })
    }

    private var slideOut: AnyTransition {
        .asymmetric(
            insertion: .opacity, removal: .move(edge: .trailing).combined(with: .opacity))
    }
}

/// A pending approval's row: the chat (or pixie) and what it asks, opening to the card.
private struct ApprovalRow: View {
    let approval: Approval
    @Environment(Shell.self) private var shell

    var body: some View {
        let green = approval.kind == .review || approval.kind == .merge
        FoldRow(key: approval.foldKey, tone: green ? .review : .waiting) {
            if let pixieID = Pixie.id(ofRepo: approval.repo) {
                // A pixie's chat belongs to no project: name the pixie and open its page.
                PixieLink(id: pixieID)
            } else {
                ChatLink(chat: approval.sessionID, title: approval.title)
            }
        } line: {
            HStack(spacing: 6) {
                NeedsLineText(line: NeedsYouLine.of(approval))
                if shell.approvals.busy.contains(approval.id) {
                    Fireflies(height: 9)
                }
            }
        } detail: {
            ApprovalCard(approval: approval, style: .panel)
        }
    }
}

/// A chat's row with failed checks or looking stuck, opening to its card.
private struct NeedsRow<Card: View>: View {
    let tone: StatusTone
    let session: Session
    let line: NeedsYouLine
    @ViewBuilder let card: Card

    var body: some View {
        FoldRow(key: "\(line.kind)-\(session.id)", tone: tone) {
            ChatLink(chat: session.id, title: session.title)
        } line: {
            NeedsLineText(line: line)
        } detail: {
            card
        }
    }
}

/// A chat that looks stuck: the reason and since when, with Send a nudge and Interrupt,
/// under its Needs you row, which names the chat.
private struct StuckCard: View {
    let session: Session
    @Environment(Shell.self) private var shell

    var body: some View {
        if let flag = session.stuck {
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .firstTextBaseline) {
                    Text(flag.reason.label)
                        .font(.ui(TypeSize.ui, .medium))
                    Spacer(minLength: 6)
                    TimelineView(.periodic(from: .now, by: 30)) { context in
                        Text("for \(Elapsed.short(from: flag.since, to: context.date))")
                            .font(.ui(TypeSize.meta))
                            .monospacedDigit()
                            .foregroundStyle(Palette.t3)
                    }
                }
                Text(flag.details)
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t2)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 3)
                ActionRow {
                    Button {
                        shell.nudge(session)
                    } label: {
                        Label("Send a nudge", systemImage: Icon.send).grows(.panel)
                    }
                    .buttonStyle(.nest(.primary))
                    .help("Stops the turn and sends \"\(flag.nudge)\"")
                    Button("Interrupt") { shell.interrupt(session.id) }
                        .buttonStyle(.nest(.plain))
                        .fixedSize()
                        .help("Stops the turn")
                }
            }
            .foregroundStyle(Palette.t1)
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .softFill()
        }
    }
}

/// What each chat of the project is planning and doing (D092): every chat working or with
/// tasks in its list, as a row with its progress that opens to its checklist (B77).
struct GoalsCard: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let entries = shell.activity.goalEntries(shell.sessions.sessions(in: shell.project ?? ""))
        VStack(alignment: .leading, spacing: 0) {
            if entries.isEmpty {
                EmptyCard(icon: Icon.goals, text: "No chats working", tone: nil)
                    .padding(.horizontal, -8)
            }
            ForEach(entries) { entry in
                GoalRow(entry: entry)
            }
        }
    }
}

/// One chat's title, which opens it, over its progress; open unless the user closed it.
private struct GoalRow: View {
    let entry: GoalEntry
    @Environment(Shell.self) private var shell

    var body: some View {
        let goals = entry.goals
        FoldRow(
            key: "goal-\(entry.session.id)", tone: shell.tone(of: entry.session),
            openByDefault: true
        ) {
            ChatLink(chat: entry.session.id, title: entry.session.title)
        } line: {
            HStack(spacing: 8) {
                Text(goals.progressLabel).monospacedDigit()
                if !goals.tasks.isEmpty {
                    ProgressTrack(value: goals.progress)
                }
            }
        } detail: {
            if !goals.tasks.isEmpty {
                Checklist(goals: goals)
            }
        }
    }
}

/// A thin bar of the share of tasks done.
private struct ProgressTrack: View {
    let value: Double
    @Environment(\.accentColors) private var accent

    var body: some View {
        Capsule()
            .fill(Palette.soft)
            .frame(width: 54, height: 3)
            .overlay(alignment: .leading) {
                Capsule().fill(accent.accent).frame(width: 54 * value, height: 3)
            }
            .accessibilityHidden(true)
    }
}

private struct Checklist: View {
    let goals: Goals

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(goals.tasks.enumerated()), id: \.element.id) { index, task in
                HStack(alignment: .firstTextBaseline, spacing: 7) {
                    mark(task.status)
                        .frame(width: 10)
                        .alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] + 4 }
                    Text("\(index + 1)")
                        .font(.mono(10))
                        .foregroundStyle(Palette.t3)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(task.subject)
                            .font(.ui(TypeSize.ui))
                            .foregroundStyle(task.status == .completed ? Palette.t3 : Palette.t1)
                        if task.status == .inProgress, let active = task.activeForm {
                            Text(active)
                                .font(.mono(TypeSize.meta))
                                .foregroundStyle(StatusTone.running.color)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(.vertical, 3)
            }
        }
        .padding(.trailing, 6)
    }

    @ViewBuilder private func mark(_ status: TaskStatus) -> some View {
        switch status {
        case .completed:
            Image(systemName: Icon.check)
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(StatusTone.review.color)
        case .inProgress:
            Fireflies(height: 9)
        default:
            Circle().strokeBorder(Palette.t3, lineWidth: 1).frame(width: 8, height: 8)
        }
    }
}

struct EmptyCard: View {
    let icon: String
    let text: String
    let tone: StatusTone?

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: icon)
                .font(.system(size: 10))
                .foregroundStyle(tone?.color ?? Palette.t3)
            Text(text)
        }
        .font(.ui(TypeSize.ui))
        .foregroundStyle(Palette.t3)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
    }
}

/// Stops one running subagent or background command, apart from the composer's Stop,
/// which interrupts the turn (B59). Disabled until its end arrives; hidden while the
/// chat's Claude Code run is closed.
struct StopTaskButton: View {
    let chat: String
    /// The task id, or the id of the tool call that started it.
    let task: String
    @Environment(Shell.self) private var shell

    var body: some View {
        if shell.activity.canStop(session: chat), shell.supports(.stopTask, chat: chat) {
            let stopping = shell.activity.isStopping(task, session: chat)
            Button {
                shell.stopTask(task, in: chat)
            } label: {
                Image(systemName: Icon.stop).font(.system(size: 7))
            }
            .buttonStyle(SmallSquareStyle())
            .disabled(stopping)
            .opacity(stopping ? 0.4 : 1)
            .help(stopping ? "Stopping" : "Stop")
            .accessibilityLabel(stopping ? "Stopping" : "Stop")
        }
    }
}
