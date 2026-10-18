import NestKit
import SwiftUI

/// Design I (B90): the project, the question and the composer docked at the bottom, where
/// a chat's composer sits once it starts; beside them, while there is room, what waits on
/// the user in the project and its latest chats. Over a chat background a fade from the
/// base colour keeps the text readable.
struct StartSession: View {
    /// From the workspace's edges.
    static let sides = 28.0
    static let bottom = 18.0
    static let gap = 32.0
    @Environment(Shell.self) private var shell
    /// Taken when the screen appears and kept while it stays, through typing and resizing.
    @State private var question: Int?

    var body: some View {
        let project = shell.project
        let draft = shell.startDraft()
        let screen = StartScreen(
            approvals: shell.approvals.pending(repo: project ?? ""),
            checksFailed: shell.sessions.checksFailed(in: project ?? ""),
            stuck: shell.sessions.stuck(in: project ?? ""),
            sessions: shell.sessions.sessions(in: project ?? ""))
        GeometryReader { geometry in
            let column = screen.showsColumn(width: geometry.size.width)
            let width =
                geometry.size.width - 2 * Self.sides
                - (column ? StartScreen.columnWidth + Self.gap : 0)
            HStack(alignment: .bottom, spacing: Self.gap) {
                VStack(alignment: .leading, spacing: 0) {
                    if let project {
                        HStack(spacing: 8) {
                            ProjectIcon(project: project, repo: shell.repo, size: 14)
                            Text(project)
                                .lineLimit(1)
                        }
                        .font(.ui(TypeSize.label))
                        .foregroundStyle(Palette.t2)
                        .padding(.horizontal, 12)
                        .padding(.bottom, 6)
                    }
                    Text(StartScreen.question(question ?? 0, project: project))
                        .font(.ui(30, .medium))
                        .tracking(-0.6)
                        .lineSpacing(4)
                        .foregroundStyle(Palette.t1)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.horizontal, 12)
                        .padding(.bottom, 16)
                        .accessibilityAddTraits(.isHeader)
                    Composer(start: shell.startDraftID)
                        .id(shell.startDraftID)
                        .environment(\.paneFit, PaneFit(width: width))
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                if column {
                    StartColumn(screen: screen)
                        .frame(width: StartScreen.columnWidth)
                        .padding(.bottom, 4)
                }
            }
            .padding(.horizontal, Self.sides)
            .padding(.bottom, Self.bottom)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
        }
        .background(alignment: .bottom) { StartFade() }
        // Appearing again: after a board or artifacts view, the last pane closing, the
        // Pixies tab; a project tab's switch keeps this view, so it asks again too.
        .onAppear { question = shell.startQuestions.next() }
        .onChange(of: project) { question = shell.startQuestions.next() }
        .onChange(of: shell.agents.defaults == nil) { _, missing in
            if !missing && draft.text.isEmpty {
                shell.startDefaultsLoaded()
            }
        }
    }
}

/// The base colour rising from the bottom over the chat background, transparent to 95
/// percent over the lower 60 percent of the workspace (at most 480 points), so a full
/// column stays readable; none without a background, where the base colour is all there
/// is.
private struct StartFade: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        if shell.chatBackground != nil {
            let base = Palette.windowOpaque
            GeometryReader { geometry in
                LinearGradient(
                    stops: [
                        .init(color: base.opacity(0), location: 0),
                        .init(color: base.opacity(0.8), location: 0.3),
                        .init(color: base.opacity(0.95), location: 1),
                    ], startPoint: .top, endPoint: .bottom
                )
                .frame(height: min(480, geometry.size.height * 0.6))
                .frame(maxHeight: .infinity, alignment: .bottom)
            }
            .allowsHitTesting(false)
            .accessibilityHidden(true)
        }
    }
}

/// "Waiting on you" and "Recent", grey labels over plain rows that open their chat; a
/// list with nothing in it is left out.
private struct StartColumn: View {
    let screen: StartScreen

    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            if !screen.waiting.isEmpty {
                SectionLabel(text: "Waiting on you \u{00B7} \(screen.waiting.count)")
                    .padding(.horizontal, 8)
                    .padding(.bottom, 5)
                ForEach(screen.waiting) { item in
                    StartRow(chat: item.chat) {
                        HStack(alignment: .top, spacing: 8) {
                            StatusMark(tone: item.tone).padding(.top, 3.5)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(item.title)
                                    .foregroundStyle(Palette.t1)
                                NeedsLineText(line: item.line)
                                    .font(.ui(TypeSize.meta))
                                    .foregroundStyle(Palette.t3)
                            }
                            .lineLimit(1)
                        }
                    }
                }
            }
            if !screen.recent.isEmpty {
                SectionLabel(text: "Recent")
                    .padding(.horizontal, 8)
                    .padding(.top, screen.waiting.isEmpty ? 0 : 14)
                    .padding(.bottom, 5)
                TimelineView(.periodic(from: .now, by: 30)) { context in
                    VStack(alignment: .leading, spacing: 1) {
                        ForEach(screen.recent) { item in
                            StartRow(chat: item.chat) {
                                HStack(spacing: 8) {
                                    Text(item.title)
                                        .foregroundStyle(Palette.t1)
                                        .lineLimit(1)
                                    Spacer(minLength: 0)
                                    Text(StartScreen.age(from: item.date, to: context.date))
                                        .font(.ui(TypeSize.meta))
                                        .monospacedDigit()
                                        .foregroundStyle(Palette.t3)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

/// A row of the start column: the hover fill, and a click anywhere opens the chat.
private struct StartRow<Label: View>: View {
    let chat: String
    @ViewBuilder let label: Label
    @Environment(Shell.self) private var shell

    var body: some View {
        HoverReader { hovering in
            Button {
                shell.openChat(chat)
            } label: {
                label
                    .font(.ui(TypeSize.ui))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 5)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(hovering ? Palette.soft : .clear, in: .rounded(Radius.row))
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .pointerStyle(.link)
            .help("Open this chat")
        }
    }
}
