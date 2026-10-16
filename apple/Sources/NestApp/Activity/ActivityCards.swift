import NestKit
import SwiftUI

/// Pending approvals, failed checks and stuck chats of the project, each with its actions;
/// resolved ones slide out.
struct NeedsCard: View {
    @Environment(Shell.self) private var shell
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        let pending = shell.approvals.pending(repo: shell.project ?? "")
        let failed = shell.sessions.checksFailed(in: shell.project ?? "")
        let stuck = shell.sessions.stuck(in: shell.project ?? "")
        VStack(alignment: .leading, spacing: 8) {
            if pending.isEmpty && failed.isEmpty && stuck.isEmpty {
                EmptyCard(icon: Icon.check, text: "Nothing needs you.", tone: .review)
                    .padding(.horizontal, -10)
                    .transition(.opacity)
            }
            // As on the iPhone: approvals, failed checks, then stuck chats.
            ForEach(NeedsYouSection.allCases, id: \.self) { section in
                switch section {
                case .approvals:
                    ForEach(pending) { approval in
                        ApprovalCard(approval: approval, style: .panel)
                            .transition(slideOut)
                    }
                case .checksFailed:
                    ForEach(failed) { session in
                        ChecksFailedCard(session: session)
                            .transition(slideOut)
                    }
                case .stuck:
                    ForEach(stuck) { session in
                        StuckCard(session: session)
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

/// A chat that looks stuck: the reason and since when, with Send a nudge and Interrupt.
private struct StuckCard: View {
    let session: Session
    @Environment(Shell.self) private var shell

    var body: some View {
        if let flag = session.stuck {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 6) {
                    StatusDot(tone: .waiting)
                    Text("Stuck")
                    Spacer(minLength: 8)
                    ChatLink(chat: session.id, title: session.title)
                        .foregroundStyle(Palette.t3)
                        .frame(maxWidth: 170, alignment: .trailing)
                }
                .font(.ui(TypeSize.meta))
                .foregroundStyle(StatusTone.waiting.color)
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
                .padding(.top, 5)
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
/// tasks in its list, under its title, its checklist always open.
struct GoalsCard: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let entries = shell.activity.goalEntries(shell.sessions.sessions(in: shell.project ?? ""))
        VStack(alignment: .leading, spacing: 0) {
            if entries.isEmpty {
                EmptyCard(icon: Icon.goals, text: "No chats working", tone: nil)
            }
            ForEach(entries) { entry in
                GoalGroup(entry: entry)
            }
        }
    }
}

/// One chat's title, which opens it, over its checklist.
private struct GoalGroup: View {
    let entry: GoalEntry
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 8) {
                StatusDot(
                    tone: shell.tone(of: entry.session), hollow: shell.isHollow(entry.session))
                ChatLink(chat: entry.session.id, title: entry.session.title)
                    .font(.ui(TypeSize.ui, .medium))
                    .foregroundStyle(Palette.t1)
            }
            .padding(EdgeInsets(top: 8, leading: 14, bottom: 2, trailing: 14))
            if entry.goals.tasks.isEmpty {
                Text("No plan yet")
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                    .padding(EdgeInsets(top: 0, leading: 28, bottom: 6, trailing: 14))
            } else {
                Checklist(goals: entry.goals)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
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
        .padding(EdgeInsets(top: 0, leading: 28, bottom: 8, trailing: 14))
    }

    @ViewBuilder private func mark(_ status: TaskStatus) -> some View {
        switch status {
        case .completed:
            Image(systemName: Icon.check)
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(StatusTone.review.color)
        case .inProgress:
            Spinner(size: 9, lineWidth: 1.5)
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
