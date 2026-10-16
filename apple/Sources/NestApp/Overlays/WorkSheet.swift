import NestKit
import SwiftUI

/// What a subagent, pixie or team did in a chat, read-only (B46): each call newest first
/// with what it was asked, its messages and tool calls as the chat shows them, and its
/// report, live while it works. There is no composer: follow-ups go in the chat.
struct WorkSheet: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let work = shell.chatPixies.work
        SheetFrame(title: work.map(title) ?? "Work", width: 700, maxHeight: 820) {
            if let work {
                WorkContent(work: work)
            }
        }
    }

    private func title(_ work: AgentWorkStore) -> String {
        switch work.target {
        case .subagent(let chat, let tool):
            shell.activity.agents(session: chat).first { $0.id == tool }?.name ?? "Subagent"
        case .pixie(_, let id): shell.pixie(id)?.name ?? "Pixie"
        case .team(_, let id, _): shell.pixies.teams.first { $0.id == id }?.name ?? "Team"
        }
    }
}

private struct WorkContent: View {
    let work: AgentWorkStore
    @Environment(Shell.self) private var shell

    var body: some View {
        let chat = work.target.session
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 6) {
                Image(systemName: Icon.agent).font(.system(size: 9))
                Text(kind)
                Text("in")
                Button {
                    shell.close()
                    shell.openChat(chat)
                } label: {
                    Text(shell.sessions.session(chat)?.title ?? "this chat")
                        .foregroundStyle(Palette.link)
                        .lineLimit(1)
                }
                .buttonStyle(.plain)
                .pointerStyle(.link)
                .help("Open the chat; follow-ups go there")
                Spacer(minLength: 8)
                Text("Read-only")
            }
            .font(.ui(TypeSize.meta))
            .foregroundStyle(Palette.t3)
            .padding(.top, 10)
            if !work.isLoaded {
                HStack(spacing: 8) {
                    Spinner(size: 11, lineWidth: 1.5)
                    Text("Loading")
                }
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t3)
            } else if let error = work.loadError {
                SystemLine(text: "Could not load this work: \(error)")
            } else if work.sections.isEmpty {
                SystemLine(text: "No calls in this chat yet")
            }
            ForEach(Array(work.sections.enumerated()), id: \.element.id) { index, section in
                if index > 0 {
                    Separator()
                }
                WorkCall(section: section, chat: chat, running: isRunning(section))
            }
        }
    }

    private var kind: String {
        switch work.target {
        case .subagent: "Subagent"
        case .pixie: "Pixie"
        case .team: "Team"
        }
    }

    /// A subagent's own status has the last word: it may end without a report.
    private func isRunning(_ section: AgentWorkSection) -> Bool {
        guard case .subagent(let chat, let tool) = work.target else {
            return section.state.isRunning
        }
        let agent = shell.activity.agents(session: chat).first { $0.id == tool }
        return section.state.isRunning && (agent.map { $0.status == .running } ?? true)
    }
}

/// One call: who and when, what it was asked, its messages and its report.
private struct WorkCall: View {
    let section: AgentWorkSection
    let chat: String
    let running: Bool
    @Environment(Shell.self) private var shell

    var body: some View {
        let entries = TranscriptGrouping.entries(section.items, live: running)
        VStack(alignment: .leading, spacing: 12) {
            header
            if let prompt = section.prompt, !prompt.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Asked")
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                    MarkdownText(text: prompt, copyable: false)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 9)
                .frame(maxWidth: .infinity, alignment: .leading)
                .softFill()
            }
            ForEach(entries) { entry in
                switch entry {
                case .item(let item):
                    TranscriptRow(item: item, chat: chat)
                case .tools(let group):
                    ToolGroupRow(group: group, chat: chat, highlighted: nil)
                case .pixieCall(let call):
                    PixieCallRow(entry: call, chat: chat)
                }
            }
            if running {
                HStack(spacing: 8) {
                    Spinner(size: 10, lineWidth: 1.5)
                    Text(entries.isEmpty ? "Starting" : "Working")
                }
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t3)
            }
            if let report = section.report, !report.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Report")
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                    MarkdownText(text: report)
                }
            } else if !running && !section.state.isRunning {
                SystemLine(text: "Ended without a report")
            }
        }
    }

    private var header: some View {
        HStack(spacing: 7) {
            if let id = section.pixieID, let pixie = shell.pixie(id) {
                SpriteView(mascot: pixie.mascot, color: pixie.color, size: 14)
                Text(pixie.name)
                    .font(.ui(TypeSize.ui, .medium))
                    .foregroundStyle(Color(hex: pixie.color))
            }
            if let started = section.startedAt {
                TimelineView(.periodic(from: .now, by: 30)) { context in
                    Text("Called \(Elapsed.short(from: started, to: context.date)) ago")
                        .monospacedDigit()
                }
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
            }
            if section.continued {
                Text("Continued")
                    .font(.ui(TypeSize.micro, .medium))
                    .foregroundStyle(Palette.t2)
                    .padding(.horizontal, 5)
                    .padding(.vertical, 1)
                    .background(Palette.soft, in: .rounded(Radius.button))
                    .help("It went on from its earlier call in this chat, with that work in mind")
            }
            Spacer(minLength: 8)
            Text(running ? "working" : section.state.label)
                .font(.ui(TypeSize.meta))
                .foregroundStyle(section.state == .failed ? StatusTone.failed.color : Palette.t3)
        }
    }
}
