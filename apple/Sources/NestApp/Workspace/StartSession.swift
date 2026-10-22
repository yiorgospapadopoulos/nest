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
    @State private var refresher: IssueRefresher?

    var body: some View {
        let project = shell.project
        let draft = shell.startDraft()
        let screen = StartScreen(
            approvals: shell.approvals.pending(repo: project ?? ""),
            checksFailed: shell.sessions.checksFailed(in: project ?? ""),
            stuck: shell.sessions.stuck(in: project ?? ""),
            sessions: shell.sessions.sessions(in: project ?? ""),
            issues: project.flatMap(shell.model.issues.list))
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
        // The project's open issues, read when the screen appears, then kept current
        // while it shows: every minute, and when the app or window comes back (B101).
        .task(id: project) {
            let refresher = refresher ?? IssueRefresher(issues: shell.model.issues)
            self.refresher = refresher
            refresher.stop()
            if let project, shell.repo?.git != false {
                await shell.model.issues.load(project)
                refresher.start(project)
            }
        }
        .onDisappear { refresher?.stop() }
        .onReceive(
            NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)
        ) { _ in
            Task { await refresher?.wake() }
        }
        .onReceive(NotificationCenter.default.publisher(for: NSWindow.didBecomeKeyNotification)) {
            _ in
            Task { await refresher?.wake() }
        }
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

/// "Waiting on you", "Open issues" (B101) and "Recent chats", grey labels over plain rows that
/// open their chat, or start one from the issue; a list with nothing in it is left out.
private struct StartColumn: View {
    let screen: StartScreen
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            if !screen.waiting.isEmpty {
                SectionLabel(text: "Waiting on you \u{00B7} \(screen.waiting.count)")
                    .padding(.horizontal, 8)
                    .padding(.bottom, 5)
                ForEach(screen.waiting) { item in
                    StartRow(help: "Open this chat") {
                        shell.openChat(item.chat)
                    } label: {
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
            if screen.showsIssues {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    SectionLabel(text: screen.issuesLabel)
                    Spacer(minLength: 0)
                    if let project = shell.project {
                        IssueShowSwitch(project: project)
                    }
                }
                .padding(.horizontal, 8)
                .padding(.top, screen.waiting.isEmpty ? 0 : 14)
                .padding(.bottom, 5)
                IssueRows(screen: screen)
            }
            if !screen.recent.isEmpty {
                SectionLabel(text: "Recent chats")
                    .padding(.horizontal, 8)
                    .padding(.top, screen.waiting.isEmpty && !screen.showsIssues ? 0 : 14)
                    .padding(.bottom, 5)
                TimelineView(.periodic(from: .now, by: 30)) { context in
                    VStack(alignment: .leading, spacing: 1) {
                        ForEach(screen.recent) { item in
                            StartRow(help: "Open this chat") {
                                shell.openChat(item.chat)
                            } label: {
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

/// Every open issue, five rows high and scrolling past them; the rows' own height sets the
/// list's, so five fit exactly (B101).
private struct IssueRows: View {
    let screen: StartScreen
    @Environment(Shell.self) private var shell
    @State private var rowHeight: CGFloat = 0

    var body: some View {
        if screen.issuesScroll {
            ScrollView {
                rows
            }
            .frame(height: rowHeight > 0 ? rowHeight * CGFloat(StartScreen.issueRows) : nil)
        } else {
            rows
        }
    }

    private var rows: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(screen.issues) { issue in
                StartRow(help: issue.help) {
                    switch issue.click(option: NSEvent.modifierFlags.contains(.option)) {
                    case .open(let chat): shell.openChat(chat)
                    case .start: shell.startFromIssue(issue)
                    }
                } label: {
                    VStack(alignment: .leading, spacing: 1) {
                        Text(issue.title)
                            .foregroundStyle(Palette.t1)
                        IssueLine(issue: issue)
                    }
                    .lineLimit(1)
                }
                .padding(.bottom, 1)
                .onGeometryChange(for: CGFloat.self) {
                    $0.size.height
                } action: {
                    rowHeight = $0
                }
            }
        }
    }
}

/// "#9 · PR #10 · 1 comment" in grey, with the pull request mark before its part (B101).
private struct IssueLine: View {
    let issue: IssueSummary

    var body: some View {
        HStack(spacing: 0) {
            Text("#\(String(issue.number))")
            if let prs = issue.prsText {
                Text(" \u{00B7} ")
                PullRequestGlyph(size: 9).padding(.trailing, 3)
                Text(prs)
            }
            if let rest = issue.lineAfterPRs {
                Text(" \u{00B7} \(rest)")
            }
        }
        .font(.ui(TypeSize.meta))
        .monospacedDigit()
        .foregroundStyle(Palette.t3)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(issue.line)
    }
}

/// "All" and "Mine" at the right of the Open issues label, small and grey like it, the
/// chosen one in primary text; a switch reads the issues again (B101).
private struct IssueShowSwitch: View {
    let project: String
    @Environment(Shell.self) private var shell

    var body: some View {
        let current = shell.model.issues.show(project)
        HStack(spacing: 8) {
            ForEach([(IssueShow.all, "All"), (.mine, "Mine")], id: \.0) { show, title in
                let on = current == show
                Button(title) {
                    Task { await shell.model.issues.setShow(show, for: project) }
                }
                .buttonStyle(.plain)
                .font(.ui(TypeSize.meta, on ? .medium : .regular))
                .foregroundStyle(on ? Palette.t1 : Palette.t3)
                .pointerStyle(.link)
                .help(show == .mine ? "Issues assigned to you" : "All open issues")
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
        .fixedSize()
    }
}

/// A row of the start column: the hover fill, and a click anywhere opens the chat or starts
/// one from the issue.
private struct StartRow<Label: View>: View {
    let help: String
    let action: () -> Void
    @ViewBuilder let label: Label

    var body: some View {
        HoverReader { hovering in
            Button(action: action) {
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
            .help(help)
        }
    }
}
