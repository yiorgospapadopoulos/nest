import NestKit
import SwiftUI

/// Autopilot's button in the composer's row (B120): quiet while off, red while on. Its
/// popover has the switch and what may stop the run; changes reach a running chat at once.
struct AutopilotButton: View {
    /// The draft's key.
    let chat: String
    /// The chat that exists, if any.
    let session: Session?
    @Environment(Shell.self) private var shell
    @State private var open = false

    var body: some View {
        let control = shell.autopilotControl(chat: chat, session: session)
        Button {
            open.toggle()
        } label: {
            Image(systemName: Icon.infinity)
                .font(.system(size: 12, weight: control.on ? .semibold : .regular))
                .foregroundStyle(control.on ? StatusTone.failed.color : Palette.t3)
        }
        .buttonStyle(.nest(.plain, iconOnly: true))
        .background(control.on ? StatusTone.failed.soft : .clear, in: .rounded(Radius.button))
        .disabled(session?.state == .closed)
        .help(AutopilotText.title)
        .accessibilityLabel("\(AutopilotText.title): \(control.on ? "on" : "off")")
        .popover(isPresented: $open, arrowEdge: .top) {
            AutopilotPopover(control: control) { change in
                shell.applyAutopilot(change, chat: chat, session: session?.id)
            }
        }
    }
}

/// The switch, then Stop after and Weekly usage cap.
struct AutopilotPopover: View {
    let control: AutopilotControl
    let apply: (AutopilotChange) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(AutopilotText.title)
                    .font(.ui(TypeSize.ui, .medium))
                    .foregroundStyle(Palette.t1)
                Spacer(minLength: 8)
                Toggle(
                    AutopilotText.title,
                    isOn: Binding(
                        get: { control.on }, set: { apply(control.turning(on: $0)) })
                )
                .toggleStyle(.switch)
                .controlSize(.mini)
                .labelsHidden()
                .tint(StatusTone.failed.color)
                .pointerStyle(.link)
            }
            SectionLabel(text: "Stop after")
                .padding(.top, 6)
            Segmented(
                options: AutopilotText.stopAfter, selection: control.stopAfter, fillsWidth: true
            ) { apply(control.stopping(after: $0)) }
            if control.stopAfter == .time, let minutes = control.budget.stopAfterMinutes {
                Segmented(options: AutopilotText.times, selection: minutes, fillsWidth: true) {
                    apply(control.stopping(afterMinutes: $0))
                }
            }
            SectionLabel(text: "Weekly usage cap")
                .padding(.top, 6)
            Segmented(
                options: AutopilotText.weeklyCaps, selection: control.budget.weeklyCap,
                fillsWidth: true
            ) { apply(control.capping(at: $0)) }
        }
        .padding(12)
        .frame(width: 300, alignment: .leading)
    }
}

/// Just above the composer while the chat runs on Autopilot: its current step, how long, its
/// decisions so far, and Turn off. Nothing otherwise.
struct AutopilotBar: View {
    let chat: String
    @Environment(Shell.self) private var shell

    var body: some View {
        if let run = shell.sessions.session(chat)?.autopilot {
            let shape = RoundedRectangle.rounded(Radius.card)
            HStack(spacing: 8) {
                Image(systemName: Icon.infinity)
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(StatusTone.failed.color)
                Text(AutopilotText.title)
                    .font(.ui(TypeSize.ui, .medium))
                    .foregroundStyle(Palette.t1)
                if let step = AutopilotText.step(shell.activity.goals(session: chat).tasks) {
                    Text(step)
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t2)
                        .lineLimit(1)
                        .truncationMode(.tail)
                        .help(step)
                }
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    Text(AutopilotText.line(run, now: context.date))
                        .font(.ui(TypeSize.meta))
                        .monospacedDigit()
                        .foregroundStyle(Palette.t3)
                        .lineLimit(1)
                        .fixedSize()
                }
                .layoutPriority(1)
                Spacer(minLength: 4)
                Button("Turn off") { shell.turnOffAutopilot(chat) }
                    .buttonStyle(.nest(.soft, height: 22))
                    .disabled(shell.sessions.settingAutopilot.contains(chat))
            }
            .padding(.leading, 12)
            .padding(.trailing, 4)
            .frame(height: 30)
            .background(shape.strokeBorder(Palette.divider))
            .padding(.horizontal, 12)
            .padding(.bottom, 6)
            .accessibilityElement(children: .contain)
            .accessibilityLabel(AutopilotText.title)
        }
    }
}

/// Autopilot's message that keeps the chat going, as Nest's line rather than the user's
/// bubble.
struct AutopilotMessageRow: View {
    let text: String

    var body: some View {
        NestLineRow(icon: Icon.infinity, title: AutopilotText.title, text: text)
    }
}

/// How a run ended and what it decided, where it ended in the chat.
struct AutopilotReportCard: View {
    /// Its row in the transcript.
    let id: String
    let report: AutopilotReport

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: Icon.infinity)
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(StatusTone.failed.color)
                Text(AutopilotText.ended(report.ended))
                    .font(.ui(TypeSize.ui, .medium))
                    .foregroundStyle(Palette.t1)
            }
            if let summary = report.summary {
                MarkdownText(text: summary, copyable: false)
            }
            if !report.decisions.isEmpty {
                SectionLabel(text: AutopilotText.decided)
                    .padding(.top, 2)
                ForEach(report.decisions.indices, id: \.self) { index in
                    DecisionLine(
                        id: "\(id)-\(index)",
                        decision: report.decisions[index])
                }
            }
        }
        .padding(EdgeInsets(top: 8, leading: 12, bottom: 10, trailing: 8))
        .frame(maxWidth: .infinity, alignment: .leading)
        .softFill()
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Autopilot report")
    }
}

/// One decision, in the chat and in the report: the small red infinity, what was asked and
/// the answer in red. It opens to the options and the reason, or to a plan's text.
struct DecisionLine: View {
    /// Its row in `shell.expandedItems`.
    let id: String
    let decision: AutopilotDecision
    @Environment(Shell.self) private var shell

    private var red: Color { StatusTone.failed.color }

    var body: some View {
        let opens = decision.opens
        let expanded = opens && shell.expandedItems.contains(id)
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Image(systemName: Icon.infinity)
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(red)
                    .frame(width: 12)
                line
                    .font(.ui(TypeSize.ui))
                    .fixedSize(horizontal: false, vertical: true)
                if opens {
                    Image(systemName: Icon.chevron)
                        .font(.system(size: 8, weight: .medium))
                        .foregroundStyle(Palette.t3)
                        .rotationEffect(.degrees(expanded ? 0 : -90))
                }
                Spacer(minLength: 0)
            }
            .frame(minHeight: 21)
            .contentShape(Rectangle())
            .pointerStyle(opens ? .link : nil)
            .onTapGesture {
                if opens {
                    toggle(id, in: shell)
                }
            }
            if expanded {
                DecisionBody(decision: decision)
                    .padding(.leading, 12)
                    .overlay(alignment: .leading) {
                        Rectangle().fill(red).frame(width: 1)
                    }
                    .padding(.leading, 5)
                    .padding(.bottom, 4)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityValue(!opens ? "" : expanded ? "Expanded" : "Collapsed")
    }

    /// One text, so a long title wraps with its answer.
    private var line: Text {
        let answer = Text(decision.shownAnswer).fontWeight(.semibold).foregroundStyle(red)
        let title = Text(decision.title).foregroundStyle(Palette.t2)
        guard decision.kind == .denied else { return Text("\(title)  \(answer)") }
        let cross = Text(Image(systemName: Icon.close)).font(.system(size: 8, weight: .bold))
            .foregroundStyle(red)
        return Text("\(title)  \(cross) \(answer)")
    }
}

/// What opens under a decision: every option with the picked one in red, a plan's text, the
/// reason.
private struct DecisionBody: View {
    let decision: AutopilotDecision

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(decision.options.indices, id: \.self) { index in
                option(decision.options[index])
            }
            if let detail = decision.detail {
                MarkdownText(text: detail, copyable: false)
            }
            if let why = decision.why {
                Text(why)
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func option(_ option: DecisionOption) -> some View {
        let red = StatusTone.failed.color
        return HStack(alignment: .firstTextBaseline, spacing: 6) {
            Image(systemName: Icon.check)
                .font(.system(size: 8, weight: .bold))
                .frame(width: 10)
                .opacity(option.picked ? 1 : 0)
            Text(option.label)
                .font(.ui(TypeSize.meta, .medium))
                .foregroundStyle(option.picked ? red : Palette.t2)
            if let description = option.description {
                Text(description)
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(option.picked ? red : Palette.t3)
            }
        }
        .foregroundStyle(red)
        .textSelection(.enabled)
        .fixedSize(horizontal: false, vertical: true)
    }
}
