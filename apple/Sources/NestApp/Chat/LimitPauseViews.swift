import NestKit
import SwiftUI

/// Just above the composer while the chat is paused at the usage limit (B78): which limit,
/// when it resets with a live countdown to when the chat goes on, what happens then, and
/// Resume now. Nothing while the chat is not paused.
struct LimitPauseBar: View {
    let chat: String
    @Environment(Shell.self) private var shell

    var body: some View {
        if let pause = shell.sessions.session(chat)?.limitPause {
            let resuming = shell.sessions.resumingLimit.contains(chat)
            let queued = shell.activity.queued(session: chat).count
            let shape = RoundedRectangle.rounded(Radius.card)
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "pause.circle")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(StatusTone.interrupted.color)
                    .padding(.top, 2)
                VStack(alignment: .leading, spacing: 2) {
                    Text(LimitPauseText.title(pause))
                        .font(.ui(TypeSize.ui, .medium))
                        .foregroundStyle(Palette.t1)
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        Text(
                            LimitPauseText.schedule(pause, now: context.date, calendar: .current)
                        )
                        .monospacedDigit()
                    }
                    Text(LimitPauseText.plan(queued: queued))
                }
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
                Button("Resume now") { shell.resumeAfterLimit(chat) }
                    .buttonStyle(.nest(.soft, height: 22))
                    .disabled(resuming)
                    .help("Go on now instead of waiting for the reset")
            }
            .padding(.leading, 12)
            .padding(.trailing, 4)
            .padding(.vertical, 7)
            .background(shape.strokeBorder(Palette.divider))
            .padding(.horizontal, 12)
            .padding(.bottom, 6)
            .accessibilityElement(children: .contain)
            .accessibilityLabel(LimitPauseText.title(pause))
        }
    }
}

/// Nest's continue message after the usage limit reset, as Nest's line rather than the
/// user's bubble.
struct LimitResumeRow: View {
    let text: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Image(systemName: "play.circle").font(.system(size: 10))
            Text(LimitResumeNote.title).font(.ui(TypeSize.meta, .medium))
            Text(LimitResumeNote.text(text))
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
