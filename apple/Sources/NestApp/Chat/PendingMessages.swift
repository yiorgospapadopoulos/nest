import NestKit
import SwiftUI

/// Messages sent while Claude works that it has not read yet, above the composer as in the
/// Claude desktop app, oldest first, each with Edit, Send now and Remove (B59). Once Claude
/// reads one it leaves here and shows in the transcript where it was read.
struct PendingMessages: View {
    /// The chat that runs.
    let chat: String
    /// The composer Edit puts the message back into.
    let draftKey: String
    @Environment(Shell.self) private var shell

    var body: some View {
        let list = shell.activity.queued(session: chat)
        if !list.isEmpty {
            let working = shell.sessions.session(chat)?.state.isInFlight ?? false
            VStack(spacing: 4) {
                ForEach(list) { message in
                    PendingRow(
                        message: message,
                        note: shell.activity.note(for: message, session: chat, working: working),
                        taken: shell.activity.isTaken(message.id, session: chat),
                        sendingNow: shell.activity.isSendingNow(message.id, session: chat),
                        edit: { shell.editPending(message, in: chat, draftKey: draftKey) },
                        sendNow: { shell.sendPendingNow(message, in: chat) },
                        remove: { shell.removePending(message, in: chat) })
                }
            }
            .transition(.opacity.combined(with: .move(edge: .bottom)))
        }
    }
}

private struct PendingRow: View {
    let message: QueuedMessage
    let note: String
    /// Claude read it before Remove reached it.
    let taken: Bool
    let sendingNow: Bool
    let edit: () -> Void
    let sendNow: () -> Void
    let remove: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            VStack(alignment: .leading, spacing: 3) {
                Text(message.text)
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t1)
                    .lineLimit(3)
                    .truncationMode(.tail)
                    .textSelection(.enabled)
                if !message.attachments.isEmpty {
                    HStack(spacing: 4) {
                        ForEach(message.attachments) { attachment in
                            Chip(icon: Icon.attach, text: attachment.filename)
                        }
                    }
                }
                Text(note)
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if !taken {
                HStack(spacing: 2) {
                    Button(action: edit) {
                        Image(systemName: Icon.edit).font(.system(size: 10))
                    }
                    .buttonStyle(.nest(.plain, height: 22, iconOnly: true))
                    .help("Edit: take the message back into the composer")
                    .accessibilityLabel("Edit pending message")
                    Button("Send now", action: sendNow)
                        .buttonStyle(.nest(.soft, height: 22))
                        .disabled(sendingNow)
                        .help("Stop the turn and send this message now")
                    Button(action: remove) {
                        Image(systemName: Icon.close).font(.system(size: 9, weight: .bold))
                    }
                    .buttonStyle(.nest(.plain, height: 22, iconOnly: true))
                    .help("Remove this message")
                    .accessibilityLabel("Remove pending message")
                }
                .fixedSize()
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(Palette.raised, in: .rounded(Radius.bubble))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Pending: \(message.text)")
    }
}
