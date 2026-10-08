import HarnessKit
import SwiftUI

/// Busy chats with their main agent, subagents and background commands; each agent opens
/// to its last steps. An idle chat stays while its background work runs.
struct AgentsCard: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let project = shell.project ?? ""
        let chats = shell.sessions.sessions(in: project)
            .filter { session in
                shell.activity.hasRunningWork(session: session.id) || session.state.isInFlight
            }
            .sorted { ($0.state == .waiting ? 0 : 1) < ($1.state == .waiting ? 0 : 1) }
        LazyVStack(alignment: .leading, spacing: 0) {
            if chats.isEmpty {
                EmptyCard(icon: Icon.agent, text: "No agents have run yet.", tone: nil)
            }
            ForEach(chats) { session in
                AgentGroup(session: session)
            }
        }
    }
}

/// One busy chat's agents under its title.
private struct AgentGroup: View {
    let session: Session
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 7) {
                StatusDot(tone: shell.tone(of: session), pulses: false)
                ChatLink(chat: session.id, title: session.title)
            }
            .font(.ui(TypeSize.label, .bold))
            .foregroundStyle(Palette.t2)
            .padding(EdgeInsets(top: 10, leading: 4, bottom: 5, trailing: 4))
            ForEach(shell.activity.agents(session: session.id)) { agent in
                AgentRow(session: session.id, agent: agent)
            }
            ForEach(shell.activity.background(session: session.id).runningCommands) { command in
                CommandRow(command: command)
            }
        }
    }
}

/// A background command still running, under its chat's agents.
private struct CommandRow: View {
    let command: BackgroundItem

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 9) {
                StatusDot(tone: .running, pulses: false)
                Image(systemName: Icon.terminal)
                    .font(.system(size: 10))
                    .foregroundStyle(Palette.t2)
                Text(command.name)
                    .font(.mono(11.5))
                    .lineLimit(1)
                Spacer(minLength: 4)
                TimelineView(.periodic(from: .now, by: 30)) { context in
                    Text(command.startedAt.map { Elapsed.short(from: $0, to: context.date) } ?? "")
                        .font(.ui(TypeSize.caption))
                        .monospacedDigit()
                        .foregroundStyle(Palette.t3)
                }
                .padding(.trailing, 21)
            }
            Text(command.description ?? "Background command")
                .font(.ui(TypeSize.label))
                .foregroundStyle(Palette.t2)
                .lineLimit(1)
                .padding(.leading, 17)
                .padding(.trailing, 21)
        }
        .foregroundStyle(Palette.t1)
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(Palette.fill, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .padding(.bottom, 5)
        .help(command.name)
    }
}

private struct AgentRow: View {
    let session: String
    let agent: TrackedAgent
    @Environment(Shell.self) private var shell

    var body: some View {
        let key = "\(session)/\(agent.id)"
        let expanded = shell.projectState.expandedAgents.contains(key)
        VStack(alignment: .leading, spacing: 0) {
            Button {
                shell.update {
                    if $0.expandedAgents.remove(key) == nil {
                        $0.expandedAgents.insert(key)
                    }
                }
            } label: {
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 9) {
                        StatusDot(tone: tone, hollow: agent.status == .unknown, pulses: false)
                        Text(agent.isMain ? "main" : agent.name)
                            .font(.ui(TypeSize.callout, .semibold))
                            .lineLimit(1)
                        Spacer(minLength: 4)
                        TimelineView(.periodic(from: .now, by: 30)) { context in
                            Text(elapsed(at: context.date))
                                .font(.ui(TypeSize.caption))
                                .monospacedDigit()
                                .foregroundStyle(Palette.t3)
                        }
                        Image(systemName: Icon.chevron)
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(Palette.t3)
                            .rotationEffect(.degrees(expanded ? 0 : -90))
                            .frame(width: 12)
                    }
                    Text(agent.activity ?? agent.description ?? statusText)
                        .font(.mono(10.5))
                        .foregroundStyle(Palette.t2)
                        .lineLimit(1)
                        .padding(.leading, 17)
                        .padding(.trailing, 21)
                }
                .foregroundStyle(Palette.t1)
                .padding(.horizontal, 10)
                .padding(.vertical, 8)
                .contentShape(Rectangle())
            }
            .buttonStyle(RowHoverStyle())
            if expanded {
                StepList(agent: agent)
            }
        }
        .background(Palette.fill, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .padding(.bottom, 5)
    }

    private var tone: StatusTone {
        switch agent.status {
        case .running: .running
        case .failed: .failed
        default: .done
        }
    }

    private var statusText: String {
        switch agent.status {
        case .running: "Working"
        case .done: "Done"
        case .failed: "Failed"
        case .unknown: "Idle"
        }
    }

    private func elapsed(at now: Date) -> String {
        guard let start = agent.startedAt else { return "" }
        return Elapsed.short(from: start, to: agent.finishedAt ?? now)
    }
}

private struct StepList: View {
    let agent: TrackedAgent
    @Environment(Shell.self) private var shell

    var body: some View {
        let steps = shell.activity.recentSteps(of: agent)
        VStack(alignment: .leading, spacing: 4) {
            if steps.isEmpty {
                Text("No steps yet").font(.ui(TypeSize.caption)).foregroundStyle(Palette.t3)
            }
            ForEach(Array(steps.enumerated()), id: \.element.id) { index, step in
                let last = index == steps.count - 1
                HStack(spacing: 6) {
                    if last && agent.status == .running && step.result == nil {
                        Spinner(size: 11, lineWidth: 1.5)
                    } else {
                        Image(systemName: Icon.tool(ToolSummary.kind(of: step.tool)))
                            .font(.system(size: 10))
                            .foregroundStyle(Palette.t3)
                            .frame(width: 12)
                    }
                    Text(step.tool).font(.ui(TypeSize.caption, .semibold))
                    Text(step.arg)
                        .font(.mono(10.5))
                        .foregroundStyle(Palette.t2)
                        .lineLimit(1)
                        .truncationMode(.middle)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    if let result = step.result {
                        Text(result)
                            .font(.ui(10.5))
                            .foregroundStyle(Palette.t3)
                            .lineLimit(1)
                    }
                }
            }
        }
        .padding(EdgeInsets(top: 6, leading: 27, bottom: 10, trailing: 10))
        .overlay(alignment: .top) { Rectangle().fill(Palette.hair).frame(height: 1) }
    }
}

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
                    .transition(.opacity)
            }
            // As on the iPhone: approvals, failed checks, then stuck chats.
            ForEach(pending) { approval in
                ApprovalCard(approval: approval, style: .panel)
                    .transition(slideOut)
            }
            ForEach(failed) { session in
                ChecksFailedCard(session: session)
                    .transition(slideOut)
            }
            ForEach(stuck) { session in
                StuckCard(session: session)
                    .transition(slideOut)
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
                    Image(systemName: Icon.warning).font(.system(size: 11, weight: .semibold))
                    Text("Stuck")
                    Spacer(minLength: 8)
                    ChatLink(chat: session.id, title: session.title)
                        .font(.ui(TypeSize.caption, .medium))
                        .foregroundStyle(Palette.t3)
                        .frame(maxWidth: 170, alignment: .trailing)
                }
                .font(.ui(TypeSize.caption, .bold))
                .foregroundStyle(StatusTone.waiting.textColor)
                HStack(alignment: .firstTextBaseline) {
                    Text(flag.reason.label)
                        .font(.ui(TypeSize.small, .semibold))
                    Spacer(minLength: 6)
                    TimelineView(.periodic(from: .now, by: 30)) { context in
                        Text("for \(Elapsed.short(from: flag.since, to: context.date))")
                            .font(.ui(TypeSize.caption))
                            .monospacedDigit()
                            .foregroundStyle(Palette.t3)
                    }
                }
                .padding(.top, 7)
                Text(flag.details)
                    .font(.ui(TypeSize.small))
                    .foregroundStyle(Palette.t2)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 3)
                ActionRow {
                    Button {
                        shell.nudge(session)
                    } label: {
                        Label("Send a nudge", systemImage: Icon.send).grows(.panel)
                    }
                    .buttonStyle(.card(.primary))
                    .help("Stops the turn and sends \"\(flag.nudge)\"")
                    Button("Interrupt") { shell.interrupt(session.id) }
                        .buttonStyle(.card(.ghost))
                        .fixedSize()
                        .help("Stops the turn")
                }
            }
            .foregroundStyle(Palette.t1)
            .padding(.horizontal, 12)
            .padding(.vertical, 11)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Palette.fill, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
    }
}

/// The open chats' task lists: progress, the current task and the checklist.
struct GoalsCard: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let chats = shell.projectState.layout.leaves.compactMap(shell.sessions.session)
        VStack(alignment: .leading, spacing: 7) {
            if chats.isEmpty {
                EmptyCard(icon: Icon.goals, text: "No open chats", tone: nil)
            }
            ForEach(chats) { session in
                GoalRow(session: session, goals: shell.activity.goals(session: session.id))
            }
        }
    }
}

private struct GoalRow: View {
    let session: Session
    let goals: Goals
    @Environment(Shell.self) private var shell

    var body: some View {
        let expanded = shell.projectState.expandedGoals.contains(session.id)
        let hasTasks = !goals.tasks.isEmpty
        VStack(alignment: .leading, spacing: 0) {
            Button {
                guard hasTasks else { return }
                shell.update {
                    if $0.expandedGoals.remove(session.id) == nil {
                        $0.expandedGoals.insert(session.id)
                    }
                }
            } label: {
                VStack(alignment: .leading, spacing: 5) {
                    HStack(spacing: 9) {
                        StatusDot(
                            tone: shell.tone(of: session), hollow: shell.isHollow(session),
                            pulses: false)
                        Text(session.title)
                            .font(.ui(TypeSize.callout, .semibold))
                            .lineLimit(1)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        if hasTasks {
                            Image(systemName: Icon.chevron)
                                .font(.system(size: 9, weight: .semibold))
                                .foregroundStyle(Palette.t3)
                                .rotationEffect(.degrees(expanded ? 0 : -90))
                                .frame(width: 12)
                        }
                    }
                    if hasTasks {
                        VStack(spacing: 4) {
                            Meter(value: goals.progress)
                            HStack {
                                Text(nowText)
                                    .lineLimit(1)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                Text("\(goals.completed) of \(goals.tasks.count)")
                                    .monospacedDigit()
                            }
                        }
                        .font(.ui(10.5))
                        .foregroundStyle(Palette.t3)
                        .padding(.leading, 17)
                    } else {
                        Text("No tasks yet")
                            .font(.ui(10.5))
                            .foregroundStyle(Palette.t3)
                            .padding(.leading, 17)
                    }
                }
                .foregroundStyle(Palette.t1)
                .padding(.horizontal, 10)
                .padding(.vertical, 9)
                .contentShape(Rectangle())
            }
            .buttonStyle(RowHoverStyle())
            if expanded && hasTasks {
                Checklist(goals: goals)
            }
        }
        .background(Palette.fill, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    private var nowText: String {
        if let current = goals.current {
            return "Now: \(current.activeForm ?? current.subject)"
        }
        return goals.completed == goals.tasks.count ? "All done" : "Up next"
    }
}

private struct Checklist: View {
    let goals: Goals

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            ForEach(Array(goals.tasks.enumerated()), id: \.element.id) { index, task in
                HStack(alignment: .top, spacing: 8) {
                    mark(task.status)
                    Text("\(index + 1)")
                        .font(.mono(10.5, .semibold))
                        .foregroundStyle(Palette.t3)
                        .frame(height: 16)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(task.subject)
                            .font(.ui(TypeSize.small))
                            .foregroundStyle(task.status == .completed ? Palette.t2 : Palette.t1)
                        if task.status == .inProgress, let active = task.activeForm {
                            Text(active)
                                .font(.mono(10.5))
                                .foregroundStyle(StatusTone.running.textColor)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(.horizontal, task.status == .inProgress ? 6 : 2)
                .padding(.vertical, task.status == .inProgress ? 6 : 5)
                .background(
                    task.status == .inProgress ? StatusTone.running.soft : .clear,
                    in: RoundedRectangle(cornerRadius: 8)
                )
                .padding(.horizontal, task.status == .inProgress ? -4 : 0)
            }
        }
        .padding(EdgeInsets(top: 6, leading: 10, bottom: 10, trailing: 10))
        .overlay(alignment: .top) { Rectangle().fill(Palette.hair).frame(height: 1) }
    }

    @ViewBuilder private func mark(_ status: TaskStatus) -> some View {
        switch status {
        case .completed:
            Image(systemName: Icon.check)
                .font(.system(size: 8, weight: .heavy))
                .foregroundStyle(.white)
                .frame(width: 16, height: 16)
                .background(StatusTone.review.color, in: Circle())
        case .inProgress:
            Spinner(size: 16)
        default:
            Circle().strokeBorder(Palette.t3, lineWidth: 1.5).frame(width: 16, height: 16)
        }
    }
}

struct EmptyCard: View {
    let icon: String
    let text: String
    let tone: StatusTone?

    var body: some View {
        VStack(spacing: 4) {
            Image(systemName: icon)
                .font(.system(size: 20))
                .foregroundStyle(tone?.textColor ?? Palette.t3)
            Text(text)
        }
        .font(.ui(TypeSize.small))
        .foregroundStyle(Palette.t3)
        .frame(maxWidth: .infinity)
        .padding(.vertical, 22)
    }
}
