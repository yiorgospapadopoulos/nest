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
