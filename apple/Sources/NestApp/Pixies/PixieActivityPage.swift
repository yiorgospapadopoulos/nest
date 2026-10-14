import NestKit
import SwiftUI

/// What the pixie did in Nest with its tools, newest first (B41): time, tool, the chat
/// it acted on (a click opens it) and a short summary. Read again after each of its turns.
struct PixieActivityPage: View {
    let pixie: Pixie
    @Environment(Shell.self) private var shell
    @State private var entries: [PixieActivityEntry]?
    @State private var failure: String?

    var body: some View {
        VStack(spacing: 0) {
            PanelPageHeader(title: "Activity", back: "Details") {
                shell.pixiePanel = .details
            } trailing: {
                EmptyView()
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    if let failure {
                        DetailLine(text: failure, dim: true)
                    } else if let entries {
                        if entries.isEmpty {
                            DetailNote(text: PixieActivityText.empty)
                                .padding(.top, 8)
                        }
                        ForEach(entries) { entry in
                            ActivityRow(entry: entry)
                        }
                    }
                }
                .padding(EdgeInsets(top: 6, leading: 6, bottom: 14, trailing: 6))
            }
            .scrollIndicators(.never)
        }
        .task(id: working) {
            do {
                entries = try await shell.pixies.activity(pixie.id)
                failure = nil
            } catch {
                failure = "Could not read the activity: \(Shell.describe(error))"
            }
        }
    }

    /// The pixie's chat runs a turn; its end may have added entries.
    private var working: Bool {
        pixie.chatSessionID.flatMap(shell.sessions.session)?.state.isInFlight ?? false
    }
}

private struct ActivityRow: View {
    let entry: PixieActivityEntry
    @Environment(Shell.self) private var shell

    var body: some View {
        let session = entry.sessionID.flatMap(shell.sessions.session)
        let chat = PixieActivityText.chat(entry.sessionID, find: shell.sessions.session)
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 8) {
                Text(PixieActivityText.tool(entry.tool))
                    .font(.ui(TypeSize.ui, .medium))
                    .foregroundStyle(Palette.t1)
                    .lineLimit(1)
                if let session {
                    Button {
                        shell.reveal(chat: session.id, in: session.repo)
                    } label: {
                        Text(session.title)
                            .lineLimit(1)
                            .truncationMode(.tail)
                    }
                    .buttonStyle(.plain)
                    .pointerStyle(.link)
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.link)
                    .help("Open \(session.title)")
                } else if let chat {
                    Text(chat)
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(Palette.t3)
                        .lineLimit(1)
                }
                Spacer(minLength: 4)
                TimelineView(.periodic(from: .now, by: 60)) { context in
                    Text(PixieActivityText.time(entry.ts, now: context.date))
                        .font(.ui(TypeSize.meta))
                        .monospacedDigit()
                        .foregroundStyle(Palette.t3)
                        .fixedSize()
                }
            }
            if !entry.summary.isEmpty {
                Text(entry.summary)
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t2)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .accessibilityElement(children: .contain)
    }
}
