import NestKit
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
            HStack(spacing: 6) {
                StatusDot(tone: shell.tone(of: session), size: 5)
                ChatLink(chat: session.id, title: session.title)
            }
            .font(.ui(TypeSize.meta))
            .foregroundStyle(Palette.t3)
            .padding(EdgeInsets(top: 6, leading: 14, bottom: 2, trailing: 14))
            ForEach(shell.activity.agents(session: session.id)) { agent in
                AgentRow(session: session.id, agent: agent)
            }
            ForEach(shell.activity.background(session: session.id).runningCommands) { command in
                CommandRow(chat: session.id, command: command)
            }
        }
    }
}

/// A background command still running, under its chat's agents.
private struct CommandRow: View {
    let chat: String
    let command: BackgroundItem

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            StatusDot(tone: .running)
                .alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] + 4 }
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 5) {
                    Image(systemName: Icon.terminal)
                        .font(.system(size: 9))
                        .foregroundStyle(Palette.t3)
                    Text(command.name)
                        .font(.mono(TypeSize.meta))
                        .foregroundStyle(Palette.t1)
                        .lineLimit(1)
                }
                Text(command.description ?? "Background command")
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            TimelineView(.periodic(from: .now, by: 30)) { context in
                Text(command.startedAt.map { Elapsed.short(from: $0, to: context.date) } ?? "")
                    .font(.ui(TypeSize.meta))
                    .monospacedDigit()
                    .foregroundStyle(Palette.t3)
            }
            StopTaskButton(chat: chat, task: command.id)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 7)
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
        // The main agent stops with the composer's Stop.
        let stoppable = !agent.isMain && agent.status == .running
        VStack(alignment: .leading, spacing: 0) {
            Button {
                shell.update {
                    if $0.expandedAgents.remove(key) == nil {
                        $0.expandedAgents.insert(key)
                    }
                }
            } label: {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    StatusDot(tone: tone, hollow: agent.status == .unknown)
                        .alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] + 4 }
                    VStack(alignment: .leading, spacing: 1) {
                        Text(agent.isMain ? "main" : agent.name)
                            .font(.ui(TypeSize.ui))
                            .foregroundStyle(Palette.t1)
                            .lineLimit(1)
                        Text(agent.activity ?? agent.description ?? statusText)
                            .font(.mono(TypeSize.meta))
                            .foregroundStyle(Palette.t3)
                            .lineLimit(1)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    TimelineView(.periodic(from: .now, by: 30)) { context in
                        Text(elapsed(at: context.date))
                            .font(.ui(TypeSize.meta))
                            .monospacedDigit()
                            .foregroundStyle(Palette.t3)
                    }
                    if stoppable {
                        // Room for Stop, which sits over the row as a button of its own.
                        Color.clear.frame(width: 18, height: 1)
                    }
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 6)
                .contentShape(Rectangle())
            }
            .buttonStyle(RowHoverStyle())
            .overlay(alignment: .trailing) {
                if stoppable {
                    StopTaskButton(chat: session, task: agent.id)
                        .padding(.trailing, 8)
                }
            }
            .padding(.horizontal, 6)
            .accessibilityAddTraits(expanded ? .isSelected : [])
            if expanded {
                StepList(agent: agent)
            }
        }
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
        VStack(alignment: .leading, spacing: 3) {
            if steps.isEmpty {
                Text("No steps yet").font(.ui(TypeSize.meta)).foregroundStyle(Palette.t3)
            }
            ForEach(Array(steps.enumerated()), id: \.element.id) { index, step in
                let last = index == steps.count - 1
                HStack(spacing: 6) {
                    if last && agent.status == .running && step.result == nil {
                        Spinner(size: 9, lineWidth: 1.5)
                    } else {
                        Image(systemName: Icon.tool(ToolSummary.kind(of: step.tool)))
                            .font(.system(size: 9))
                            .foregroundStyle(Palette.t3)
                            .frame(width: 10)
                    }
                    Text(step.tool).font(.ui(TypeSize.meta, .medium)).foregroundStyle(Palette.t2)
                    Text(step.arg)
                        .font(.mono(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                        .lineLimit(1)
                        .truncationMode(.middle)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    if let result = step.result {
                        Text(result)
                            .font(.ui(TypeSize.meta))
                            .foregroundStyle(Palette.t3)
                            .lineLimit(1)
                    }
                }
            }
        }
        .padding(.leading, 10)
        .overlay(alignment: .leading) { Separator(axis: .vertical) }
        .padding(EdgeInsets(top: 2, leading: 28, bottom: 8, trailing: 14))
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

/// The open chats' task lists: progress, the current task and the checklist.
struct GoalsCard: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let chats = shell.projectState.layout.leaves.compactMap(shell.sessions.session)
        VStack(alignment: .leading, spacing: 0) {
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
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    StatusDot(tone: shell.tone(of: session), hollow: shell.isHollow(session))
                        .alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] + 4 }
                    VStack(alignment: .leading, spacing: 3) {
                        Text(session.title)
                            .font(.ui(TypeSize.ui))
                            .foregroundStyle(Palette.t1)
                            .lineLimit(1)
                        Text(
                            hasTasks
                                ? "\(nowText) · \(goals.completed) of \(goals.tasks.count)"
                                : "No tasks yet"
                        )
                        .font(.ui(TypeSize.meta))
                        .monospacedDigit()
                        .foregroundStyle(Palette.t3)
                        .lineLimit(1)
                        if hasTasks {
                            Meter(value: goals.progress, height: 2).padding(.top, 2)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    if hasTasks {
                        Image(systemName: Icon.chevron)
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(Palette.t3)
                            .rotationEffect(.degrees(expanded ? 0 : -90))
                            .frame(width: 12)
                    }
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 6)
                .contentShape(Rectangle())
            }
            .buttonStyle(RowHoverStyle())
            .padding(.horizontal, 6)
            if expanded && hasTasks {
                Checklist(goals: goals)
            }
        }
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
