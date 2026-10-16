import AppKit
import NestKit
import SwiftUI

/// A chat's transcript, following new content while scrolled to the bottom. A search hit
/// scrolls to its message, which glows briefly.
struct TranscriptView: View {
    let chat: String
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @State private var store: TranscriptStore?
    @State private var loadError: String?
    @State private var position = ScrollPosition(edge: .bottom)
    @State private var follow = ScrollFollow()
    /// The item a search hit scrolls to, and the one that glows.
    @State private var scrollTarget: String?
    @State private var highlighted: String?

    var body: some View {
        let items = store?.visibleItems ?? []
        let session = shell.sessions.session(chat)
        let working = session.map { $0.state == .running || $0.state == .starting } ?? false
        let streaming = items.last?.id == "streaming"
        let hasNewer = store?.hasNewer == true
        let background = Set(shell.activity.background(session: chat).runningItems.map(\.id))
        // A call waiting on a permission prompt still runs; one whose turn ended stopped.
        let inFlight = session?.state.isInFlight ?? false
        let pixies = PixieCalls.slugs(shell.pixies.pixies)
        let entries =
            store?.entries(live: inFlight, background: background, pixies: pixies) ?? []
        let answered = PixieCards.answered(items)
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 14) {
                    if store?.hasOlder == true {
                        PageButton(title: "Load earlier messages") {
                            try await store?.loadOlder()
                        }
                    }
                    ForEach(entries) { entry in
                        switch entry {
                        case .item(let item):
                            TranscriptRow(
                                item: item, chat: chat, answered: answered.contains(item.id)
                            )
                            .background {
                                if highlighted == item.id {
                                    Highlight(accent: accent)
                                }
                            }
                        case .tools(let group):
                            ToolGroupRow(group: group, chat: chat, highlighted: highlighted)
                        case .pixieCall(let call):
                            PixieCallRow(entry: call, chat: chat)
                                .background {
                                    if highlighted == call.id {
                                        Highlight(accent: accent)
                                    }
                                }
                        }
                    }
                    if hasNewer {
                        PageButton(title: "Load newer messages") {
                            try await store?.loadNewer()
                        }
                    } else if working && !streaming {
                        WorkingLine(
                            since: store?.turnStartedAt, thinking: store?.isThinking == true,
                            thought: store?.liveThinking ?? "")
                    }
                    // `!` commands run since the last message, until it carries them (B59).
                    ForEach(shell.bash.rows(chat: chat)) { row in
                        BashRow(
                            id: row.id, command: row.command, output: row.run?.output ?? "",
                            notes: row.run?.notes ?? [], running: row.isRunning,
                            failure: row.failure)
                    }
                    if let failure = store?.catchUpFailure {
                        // Live events wait until the missed ones load (audit BUG-101).
                        VStack(spacing: 4) {
                            SystemLine(text: "\(TranscriptStore.catchUpFailedText): \(failure)")
                            PageButton(title: "Retry") { await store?.retryCatchUp() }
                        }
                        .frame(maxWidth: .infinity)
                    }
                    if let loadError {
                        SystemLine(text: loadError)
                            .frame(maxWidth: .infinity)
                    } else if store?.isLoaded == true && items.isEmpty && !working {
                        EmptyTranscript()
                    }
                }
                .padding(EdgeInsets(top: 18, leading: 20, bottom: 12, trailing: 20))
            }
            .onChange(of: scrollTarget) { _, target in
                if let target {
                    withAnimation(.smooth(duration: 0.3)) {
                        proxy.scrollTo(target, anchor: .center)
                    }
                }
            }
        }
        .scrollPosition($position)
        .defaultScrollAnchor(.bottom, for: .initialOffset)
        .onScrollGeometryChange(for: ScrollMetrics.self) { geometry in
            ScrollMetrics(
                offset: geometry.contentOffset.y, viewport: geometry.containerSize.height,
                content: geometry.contentSize.height)
        } action: { _, metrics in
            // Text views settle their height after layout, so growth arrives here too.
            if follow.update(metrics) {
                position.scrollTo(edge: .bottom)
            }
        }
        .onChange(of: items.last) {
            if follow.contentArrived() {
                position.scrollTo(edge: .bottom)
            }
        }
        .overlay(alignment: .bottom) {
            if follow.showsJump {
                JumpToLatest {
                    follow.jumpToLatest()
                    withAnimation(.smooth(duration: 0.3)) { position.scrollTo(edge: .bottom) }
                }
                .padding(.bottom, 10)
                .transition(.opacity.combined(with: .scale(scale: 0.9)))
            }
        }
        .animation(.smooth(duration: 0.2), value: follow.showsJump)
        .task(id: chat) { await load() }
        // A load that failed while the daemon was down is retried when it connects again.
        .onChange(of: store?.isLoaded) { _, loaded in
            if loaded == true {
                loadError = nil
            }
        }
        .onChange(of: store?.focus) { _, focus in
            if focus != nil {
                Task { await reveal() }
            }
        }
        // A Claude Code chat that moved on in Claude Code is read again.
        .onChange(of: shell.claudeChat(inPane: chat)?.lastActivityAt) { old, new in
            if old != nil, new != nil {
                Task { await reloadClaudeChat() }
            }
        }
    }

    private func load() async {
        follow = ScrollFollow()
        let transcript = shell.model.transcripts.transcript(for: chat)
        store = transcript
        if transcript.isLoaded && transcript.needsLoad {
            // Behind after a failed catch-up: its own line says so if it fails again.
            await transcript.retryCatchUp()
        } else if transcript.needsLoad {
            do {
                try await transcript.load()
                loadError = nil
            } catch {
                loadError = "Could not load this chat: \(Shell.describe(error))"
            }
        }
        if !shell.isClaudeChatPane(chat) {
            try? await shell.activity.load(session: chat)
        }
        position.scrollTo(edge: .bottom)
        if transcript.focus != nil {
            await reveal()
        }
    }

    /// Scrolls to the requested message, loading its page when needed, and lets it glow.
    private func reveal() async {
        guard let store, let target = try? await store.resolveFocus() else { return }
        follow.hold()
        // A hit inside a collapsed group of tool calls opens the group first.
        let entries = store.entries(live: false, pixies: PixieCalls.slugs(shell.pixies.pixies))
        if let group = TranscriptGrouping.group(containing: target, in: entries) {
            shell.expandedItems.insert(group)
        }
        scrollTarget = nil
        // The loaded items lay out first, and the same target can be shown again.
        try? await Task.sleep(for: .milliseconds(60))
        scrollTarget = target
        withAnimation(.smooth(duration: 0.2)) { highlighted = target }
        try? await Task.sleep(for: .seconds(1.8))
        if highlighted == target {
            withAnimation(.smooth(duration: 0.6)) { highlighted = nil }
        }
    }

    private func reloadClaudeChat() async {
        guard let store, store.source == .claudeChat else { return }
        do {
            try await store.load()
            loadError = nil
        } catch {
            loadError = "Could not load this chat: \(Shell.describe(error))"
        }
    }
}

struct TranscriptRow: View {
    let item: TranscriptItem
    let chat: String
    /// A choices card with a user message after it.
    var answered = false
    @Environment(Shell.self) private var shell

    var body: some View {
        switch item.content {
        case .user(let text, let attachments):
            let canRewind = RewindFlow.isAvailable(for: shell.sessions.session(chat))
            let canFork = SessionsStore.canFork(shell.sessions.session(chat))
            VStack(alignment: .trailing, spacing: 4) {
                if let from = item.fromPixie {
                    FromPixieLabel(label: PixieLabels.from(from, pixies: shell.pixies.pixies))
                }
                UserBubble(
                    text: text, attachments: attachments,
                    mentions: MentionHighlights.find(
                        in: text, pixies: shell.pixies.pixies, teams: shell.pixies.teams,
                        plain: shell.plainMentions(forChat: chat)),
                    actions: item.eventID.flatMap { event in
                        canRewind || canFork
                            ? MessageActions(
                                edit: canRewind ? { shell.startEdit(chat, message: event) } : nil,
                                rewind: canRewind
                                    ? { shell.startRewind(chat, message: event) } : nil,
                                fork: canFork ? { shell.fork(chat, message: event) } : nil)
                            : nil
                    })
            }
            .frame(maxWidth: .infinity, alignment: .trailing)
        case .assistant(let text, _):
            AssistantText(text: text, chat: chat)
        case .thinking(let text, let duration):
            ThinkingRow(id: item.id, text: text, durationMS: duration)
        case .tool(let call):
            ToolRow(id: item.id, call: call)
        case .approval(let id, let kind, let status, let rejected, let answers):
            ApprovalPlaceholder(
                id: id, kind: kind, status: status, rejected: rejected, answers: answers)
        case .result(let result):
            SystemLine(text: result.failure)
                .frame(maxWidth: .infinity)
        case .notice(let text):
            SystemLine(text: text)
                .frame(maxWidth: .infinity)
        case .turnEnd(let end):
            TurnEndLine(end: end)
        case .reportBack(let text):
            ReportBackRow(text: text)
        case .pixieCard(let card):
            PixieCardView(card: card, chat: chat, answered: answered)
        case .habitReport(let text):
            HabitReportRow(text: text)
        case .hook(let run):
            HookRow(id: item.id, run: run)
        case .bash(let block):
            BashRow(id: item.id, command: block.command, output: block.output)
        }
    }
}

private struct UserBubble: View {
    let text: String
    let attachments: [Attachment]
    /// Pixie and team mentions, drawn in their colour and semibold (B40).
    let mentions: [MentionHighlight]
    /// Edit, Rewind and Fork from here, while no turn runs (B59).
    let actions: MessageActions?
    @Environment(\.revealsHoverControls) private var reveal
    @State private var hovering = false

    var body: some View {
        VStack(alignment: .trailing, spacing: 6) {
            if !text.isEmpty {
                let color = NSColor(Palette.Mac.textPrimary)
                SelectableText(key: "\(color)\n\(mentions)\n\(text)", hugsWidth: true) {
                    let styled = NSMutableAttributedString(
                        attributedString: TextStyling.plain(
                            text, font: TextStyling.ui(TypeSize.reading), color: color,
                            lineSpacing: 3))
                    for mention in mentions {
                        styled.addAttributes(
                            [
                                .foregroundColor: NSColor(Color(hex: mention.color)),
                                .font: TextStyling.ui(TypeSize.reading, .semibold),
                            ], range: mention.range)
                    }
                    return styled
                }
                .padding(.horizontal, 11)
                .padding(.vertical, 7)
                .background(Palette.raised, in: .rounded(Radius.bubble))
                .overlay(alignment: .leading) {
                    if let actions, hovering || reveal {
                        MessageActionsMenu(actions: actions)
                            .offset(x: -30)
                            .transition(.opacity)
                    }
                }
            }
            ForEach(attachments) { attachment in
                Chip(icon: Icon.attach, text: attachment.filename)
            }
        }
        .frame(maxWidth: .infinity, alignment: .trailing)
        .padding(.leading, 48)
        .onHover { hovering = $0 }
    }
}

/// Assistant text: headings, paragraphs, lists and code blocks as one selectable text.
struct MarkdownText: View {
    let text: String
    /// Off inside a message that has its own Copy button.
    var copyable = true

    var body: some View {
        if copyable {
            content
                .padding(.trailing, HoverCopy.gutter)
                .hoverCopy(text)
        } else {
            content
        }
    }

    private var content: some View {
        SelectableText(key: text, linkColor: NSColor(Palette.Mac.link)) {
            TextStyling.message(RichText.paragraphs(text))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// An assistant message; shell commands in it get their own block with Copy and Run in
/// terminal, the rest stays one selectable text per stretch.
private struct AssistantText: View {
    let text: String
    let chat: String

    var body: some View {
        let segments = ShellCommand.segments(text)
        if segments.contains(where: \.isCommand) {
            VStack(alignment: .leading, spacing: 10) {
                ForEach(Array(segments.enumerated()), id: \.offset) { _, segment in
                    switch segment {
                    case .markdown(let part): MarkdownText(text: part, copyable: false)
                    case .command(let command): CommandBlock(command: command, chat: chat)
                    }
                }
            }
            .padding(.trailing, HoverCopy.gutter)
            .hoverCopy(text)
        } else {
            MarkdownText(text: text)
        }
    }
}

extension MessageSegment {
    fileprivate var isCommand: Bool {
        if case .command = self { true } else { false }
    }
}

/// A shell command from the transcript in mono, with Copy and, for one line, Run in
/// terminal.
private struct CommandBlock: View {
    let command: String
    let chat: String
    @Environment(Shell.self) private var shell

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            SelectableText(key: command) {
                TextStyling.plain(
                    command, font: TextStyling.mono(TypeSize.meta), color: TextStyling.primary,
                    lineSpacing: 3)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, 3)
            HStack(spacing: 2) {
                Button {
                    shell.copyText(command)
                } label: {
                    Label("Copy", systemImage: Icon.copy)
                }
                .help("Copy the command")
                // A command of several lines would run line by line; Copy still offers it.
                if TerminalInput.line(for: command) != nil {
                    Button {
                        shell.runInTerminal(command: command, from: chat)
                    } label: {
                        Label("Run in terminal", systemImage: Icon.terminal)
                    }
                    .help("Run the command in a terminal pane in the chat's folder")
                }
            }
            .buttonStyle(.nest(.plain, height: 22))
            .fixedSize()
        }
        .padding(.leading, 10)
        .padding(.trailing, 4)
        .padding(.vertical, 4)
        .softFill()
    }
}

/// What can be done with one of the user's messages while no turn runs, as in Claude
/// Code: edit it, rewind to before it, or fork a new chat from it (B59).
private struct MessageActions {
    let edit: (() -> Void)?
    let rewind: (() -> Void)?
    let fork: (() -> Void)?
}

/// The hover menu beside a user message.
private struct MessageActionsMenu: View {
    let actions: MessageActions

    var body: some View {
        Menu {
            if let edit = actions.edit {
                Button("Edit", systemImage: Icon.edit, action: edit)
            }
            if let rewind = actions.rewind {
                Button("Rewind…", systemImage: Icon.rewind, action: rewind)
            }
            if let fork = actions.fork {
                Button("Fork from here", systemImage: Icon.fork, action: fork)
            }
        } label: {
            Image(systemName: Icon.more)
                .font(.system(size: 11))
                .foregroundStyle(Palette.t3)
                .frame(width: 22, height: 22)
                .contentShape(Rectangle())
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .menuIndicator(.hidden)
        .pointerStyle(.link)
        .fixedSize()
        .help("Edit, rewind or fork from this message")
        .accessibilityLabel("Message actions")
    }
}

/// A Copy button over the top trailing corner while the pointer is over the content.
private struct HoverCopy: ViewModifier {
    /// Room kept free at the trailing edge so the button never covers text.
    static let gutter: Double = 28

    let text: String
    @State private var hovering = false
    @Environment(Shell.self) private var shell
    @Environment(\.revealsHoverControls) private var reveal

    func body(content: Content) -> some View {
        content
            .onHover { hovering = $0 }
            .overlay(alignment: .topTrailing) {
                if hovering || reveal {
                    Button {
                        shell.copyText(text)
                    } label: {
                        Image(systemName: Icon.copy)
                            .font(.system(size: 11))
                            .foregroundStyle(Palette.t3)
                    }
                    .buttonStyle(.nest(.plain, height: 22, iconOnly: true))
                    .padding(.top, 2)
                    .help("Copy")
                    .accessibilityLabel("Copy")
                    .transition(.opacity)
                }
            }
    }
}

extension View {
    fileprivate func hoverCopy(_ text: String) -> some View {
        modifier(HoverCopy(text: text))
    }
}

/// "Thought for 8s", opening to the thinking text in muted italics; thinking with no
/// text (redacted) cannot open.
private struct ThinkingRow: View {
    static let font = NSFontManager.shared.convert(
        TextStyling.ui(TypeSize.ui), toHaveTrait: .italicFontMask)

    let id: String
    let text: String
    let durationMS: Int?
    @Environment(Shell.self) private var shell

    var body: some View {
        let expanded = shell.expandedItems.contains(id)
        let expandable = !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        VStack(alignment: .leading, spacing: 6) {
            Button {
                toggle(id, in: shell)
            } label: {
                HStack(spacing: 7) {
                    Image(systemName: "brain").font(.system(size: 10))
                        .frame(width: 12)
                    Text(TurnText.thought(durationMS: durationMS))
                    if expandable {
                        Image(systemName: Icon.chevron)
                            .font(.system(size: 8, weight: .medium))
                            .rotationEffect(.degrees(expanded ? 0 : -90))
                    }
                }
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t3)
                .frame(minHeight: 21)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .pointerStyle(expandable ? .link : nil)
            .disabled(!expandable)
            .accessibilityValue(expandable ? (expanded ? "Expanded" : "Collapsed") : "")
            if expanded && expandable {
                SelectableText(key: text) {
                    TextStyling.plain(
                        text, font: Self.font, color: TextStyling.secondary)
                }
                .padding(.leading, 19)
            }
        }
    }
}

/// Tool calls in a row as one line, "Ran 3 commands, read 2 files", shimmering while
/// any runs; opens to the calls and the thinking between them.
struct ToolGroupRow: View {
    let group: ToolGroup
    let chat: String
    let highlighted: String?
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent

    var body: some View {
        let expanded = shell.expandedItems.contains(group.id)
        VStack(alignment: .leading, spacing: 2) {
            Button {
                toggle(group.id, in: shell)
            } label: {
                HStack(spacing: 7) {
                    Image(systemName: Icon.tool(dominantKind))
                        .font(.system(size: 10))
                        .foregroundStyle(Palette.t3)
                        .frame(width: 12)
                    Text(group.summary)
                        .foregroundStyle(Palette.t2)
                        .lineLimit(1)
                        .truncationMode(.tail)
                        .shimmer(group.isRunning)
                    Image(systemName: Icon.chevron)
                        .font(.system(size: 8, weight: .medium))
                        .foregroundStyle(Palette.t3)
                        .rotationEffect(.degrees(expanded ? 0 : -90))
                }
                .font(.ui(TypeSize.ui))
                .frame(minHeight: 21)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .pointerStyle(.link)
            .accessibilityLabel(group.summary)
            .accessibilityValue(expanded ? "Expanded" : "Collapsed")
            if expanded {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(group.items) { item in
                        TranscriptRow(item: item, chat: chat)
                            .background {
                                if highlighted == item.id {
                                    Highlight(accent: accent)
                                }
                            }
                    }
                }
                .padding(.leading, 14)
            }
        }
    }

    /// The icon of the group's first kind of call.
    private var dominantKind: ToolSummary.Kind {
        group.calls.first.map { ToolSummary.kind(of: $0.name) } ?? .other
    }
}

/// A tool call: icon, name, argument and result note; opens to show the output, or for
/// an agent call what its subagent did and is doing.
private struct ToolRow: View {
    let id: String
    let call: ToolCall
    @Environment(Shell.self) private var shell

    var body: some View {
        let expanded = shell.expandedItems.contains(id)
        let output = ToolSummary.output(of: call).map { $0.trimmingCharacters(in: .newlines) } ?? ""
        let kind = ToolSummary.kind(of: call.name)
        let isAgent = kind == .agent
        let live = !call.liveText.isEmpty || !call.liveThinking.isEmpty
        let diff = EditDiff(call)
        let expandable =
            diff == nil && (!output.isEmpty || isAgent && (!call.steps.isEmpty || live))
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 7) {
                Image(systemName: Icon.tool(kind))
                    .font(.system(size: 10))
                    .foregroundStyle(Palette.t3)
                    .frame(width: 12)
                Text(call.name)
                    .font(.ui(TypeSize.ui, .medium))
                    .foregroundStyle(Palette.t1)
                    .fixedSize()
                Text(ToolSummary.argument(of: call))
                    .font(.mono(TypeSize.meta))
                    .foregroundStyle(kind == .read || kind == .edit ? Palette.link : Palette.t2)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .layoutPriority(1)
                let note = ToolSummary.result(of: call)
                if let diff {
                    HStack(spacing: 4) {
                        Text("+\(diff.additions)").foregroundStyle(StatusTone.review.color)
                        Text("-\(diff.deletions)").foregroundStyle(StatusTone.failed.color)
                    }
                    .font(.ui(TypeSize.meta))
                    .monospacedDigit()
                    .fixedSize()
                    .accessibilityLabel(
                        "\(diff.additions) added, \(diff.deletions) removed")
                } else if kind == .edit && note == "done" {
                    Image(systemName: Icon.check)
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(StatusTone.review.color)
                        .accessibilityLabel("done")
                } else if !note.isEmpty {
                    Text(call.isError ? note : "\u{00B7} \(note)")
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(call.isError ? StatusTone.failed.color : Palette.t3)
                        .lineLimit(1)
                        .fixedSize()
                }
                if expandable {
                    Image(systemName: Icon.chevron)
                        .font(.system(size: 8, weight: .medium))
                        .foregroundStyle(Palette.t3)
                        .rotationEffect(.degrees(expanded ? 0 : -90))
                }
                Spacer(minLength: 0)
            }
            .frame(minHeight: 21)
            .contentShape(Rectangle())
            .pointerStyle(expandable ? .link : nil)
            .onTapGesture {
                if expandable {
                    toggle(id, in: shell)
                }
            }
            if expanded && isAgent {
                AgentCallSteps(call: call, answer: false)
                    .padding(.leading, 6)
            } else if !expanded, let line = ThinkingPreview.line(call.liveText) {
                LivePreview(text: line)
            }
            if let diff {
                EditDiffView(id: id, diff: diff)
            } else if expanded && !output.isEmpty {
                ToolOutputView(id: id, output: output)
            }
            if !call.images.isEmpty {
                ToolImages(images: call.images)
            }
        }
        .accessibilityElement(children: .combine)
    }
}

/// An edit's change under its call, like Claude's apps: removed lines in red, added ones
/// in green, its first lines with Show more when long (B59).
private struct EditDiffView: View {
    let id: String
    let diff: EditDiff
    @Environment(Shell.self) private var shell

    private var showAllID: String { "\(id)-diff" }

    var body: some View {
        let showsAll = shell.expandedItems.contains(showAllID)
        let hunks = diff.shown(expanded: showsAll)
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(hunks.enumerated()), id: \.offset) { index, hunk in
                if index > 0 {
                    Text("\u{22EF}")
                        .font(.mono(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                        .padding(.leading, 8)
                        .padding(.vertical, 1)
                }
                ForEach(Array(hunk.enumerated()), id: \.offset) { _, line in
                    EditDiffLine(line: line)
                }
            }
            if let label = diff.expandLabel {
                Button(showsAll ? "Show less" : label) {
                    toggle(showAllID, in: shell)
                }
                .buttonStyle(.plain)
                .pointerStyle(.link)
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.link)
                .padding(EdgeInsets(top: 6, leading: 8, bottom: 2, trailing: 8))
            }
        }
        .padding(.vertical, 4)
        .frame(maxWidth: .infinity, alignment: .leading)
        .softFill()
        .clipShape(.rounded(Radius.card))
        .padding(.leading, 19)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(
            "Changes to \(diff.path): \(diff.additions) added, \(diff.deletions) removed")
    }
}

private struct EditDiffLine: View {
    let line: EditDiff.Line

    var body: some View {
        let (mark, tint): (String, Color?) =
            switch line.kind {
            case .add: ("+", StatusTone.review.color)
            case .delete: ("-", StatusTone.failed.color)
            default: (" ", nil)
            }
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Text(mark)
                .foregroundStyle(tint ?? Palette.t3)
                .frame(width: 8)
            Text(line.text.isEmpty ? " " : line.text)
                .foregroundStyle(tint == nil ? Palette.t2 : Palette.t1)
                .lineLimit(1)
                .truncationMode(.tail)
        }
        .font(.mono(TypeSize.meta))
        .padding(.horizontal, 8)
        .padding(.vertical, 1)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(tint.map { $0.opacity(0.12) } ?? .clear)
    }
}

/// A tool's output, whole when short, else its first lines with Show more, like Claude's
/// apps; nothing is cut (B59).
private struct ToolOutputView: View {
    let id: String
    let output: String
    @Environment(Shell.self) private var shell

    private var showAllID: String { "\(id)-all" }

    var body: some View {
        let collapsed = CollapsedOutput(output)
        let showsAll = shell.expandedItems.contains(showAllID)
        let shown = showsAll ? collapsed.full : collapsed.preview
        VStack(alignment: .leading, spacing: 6) {
            SelectableText(key: shown) {
                TextStyling.plain(
                    shown, font: TextStyling.mono(TypeSize.meta),
                    color: TextStyling.secondary, lineSpacing: 4)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if let label = collapsed.expandLabel {
                Button(showsAll ? "Show less" : label) {
                    toggle(showAllID, in: shell)
                }
                .buttonStyle(.plain)
                .pointerStyle(.link)
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.link)
            }
        }
        .padding(EdgeInsets(top: 8, leading: 10, bottom: 8, trailing: HoverCopy.gutter + 4))
        .hoverCopy(output)
        .softFill()
        .padding(.leading, 19)
    }
}

/// The latest line a subagent wrote, under its collapsed call while it streams.
private struct LivePreview: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.ui(TypeSize.meta))
            .foregroundStyle(Palette.t3)
            .lineLimit(1)
            .truncationMode(.head)
            .padding(.leading, 19)
            .accessibilityLabel("Latest: \(text)")
    }
}

/// A hook's line, muted like Claude Code's: what it says, or its output or failure
/// opening below. A failure is tinted and opens by default.
private struct HookRow: View {
    let id: String
    let run: HookRun
    @Environment(Shell.self) private var shell

    var body: some View {
        let detail = run.detail
        let expanded = detail != nil && run.isFailure != shell.expandedItems.contains(id)
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 7) {
                Image(systemName: run.isFailure ? Icon.warning : Icon.hook)
                    .font(.system(size: 10))
                    .frame(width: 12)
                Text(run.title)
                    .lineLimit(expanded ? nil : 1)
                    .truncationMode(.tail)
                if detail != nil {
                    Image(systemName: Icon.chevron)
                        .font(.system(size: 8, weight: .medium))
                        .rotationEffect(.degrees(expanded ? 0 : -90))
                }
                Spacer(minLength: 0)
            }
            .font(.ui(TypeSize.ui))
            .foregroundStyle(run.isFailure ? StatusTone.waiting.color : Palette.t3)
            .frame(minHeight: 21)
            .contentShape(Rectangle())
            .pointerStyle(detail != nil ? .link : nil)
            .onTapGesture {
                if detail != nil {
                    toggle(id, in: shell)
                }
            }
            if expanded, let detail {
                ToolOutputView(id: id, output: detail)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityValue(detail == nil ? "" : expanded ? "Expanded" : "Collapsed")
    }
}

/// A pixie's call (B40): its mascot and name with what it was asked and how it went,
/// shimmering while it runs. A click opens its steps and answer in place; the mascot or
/// name opens the pixie in the Pixies tab.
struct PixieCallRow: View {
    let entry: PixieCallEntry
    let chat: String
    @Environment(Shell.self) private var shell

    var body: some View {
        let expanded = shell.expandedItems.contains(entry.id)
        let pixie = shell.pixies.pixies.first { $0.slug == entry.slug }
        let name = pixie?.name ?? entry.slug
        let task = entry.call.input["description"]?.stringValue ?? ""
        let note = ToolSummary.result(of: entry.call)
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 7) {
                Button {
                    if let pixie {
                        shell.revealPixie(pixie.id)
                    }
                } label: {
                    HStack(spacing: 6) {
                        if let pixie {
                            SpriteView(
                                mascot: pixie.mascot, color: pixie.color, size: 13,
                                working: entry.isRunning, phaseKey: pixie.id)
                        }
                        Text(name)
                            .font(.ui(TypeSize.ui, .medium))
                            .foregroundStyle(Palette.t1)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .pointerStyle(.link)
                .fixedSize()
                .help("Open \(name) in Pixies")
                .accessibilityLabel("Open \(name)")
                Group {
                    Text(task)
                        .foregroundStyle(Palette.t2)
                        .lineLimit(1)
                        .truncationMode(.tail)
                        .shimmer(entry.isRunning)
                        .layoutPriority(1)
                    Text(entry.call.isError ? note : "\u{00B7} \(note)")
                        .foregroundStyle(entry.call.isError ? StatusTone.failed.color : Palette.t3)
                        .lineLimit(1)
                        .fixedSize()
                    Image(systemName: Icon.chevron)
                        .font(.system(size: 8, weight: .medium))
                        .foregroundStyle(Palette.t3)
                        .rotationEffect(.degrees(expanded ? 0 : -90))
                    Spacer(minLength: 0)
                }
                .font(.ui(TypeSize.ui))
                .contentShape(Rectangle())
                .pointerStyle(.link)
                .onTapGesture { toggle(entry.id, in: shell) }
                if entry.isRunning {
                    StopTaskButton(chat: chat, task: entry.id)
                }
            }
            .frame(minHeight: 21)
            .accessibilityElement(children: .contain)
            .accessibilityValue(expanded ? "Expanded" : "Collapsed")
            .accessibilityAction(named: expanded ? "Collapse" : "Expand") {
                toggle(entry.id, in: shell)
            }
            if expanded {
                AgentCallSteps(call: entry.call, answer: true)
                    .padding(.leading, 6)
            } else if let line = ThinkingPreview.line(entry.call.liveText) {
                LivePreview(text: line)
            }
        }
    }
}

/// An opened agent or pixie call: its subagent's thinking, text and tool calls in order,
/// what it is writing now, then (for a pixie, with `answer`) its answer.
private struct AgentCallSteps: View {
    let call: ToolCall
    let answer: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(call.steps) { step in
                switch step.kind {
                case .thinking(let text):
                    SelectableText(key: text) {
                        TextStyling.plain(
                            text, font: ThinkingRow.font, color: TextStyling.secondary)
                    }
                case .text(let text):
                    MarkdownText(text: text, copyable: false)
                case .tool(let name, _):
                    HStack(spacing: 7) {
                        Image(systemName: Icon.tool(ToolSummary.kind(of: name)))
                            .font(.system(size: 9))
                            .frame(width: 12)
                        Text(step.line)
                            .font(.mono(TypeSize.meta))
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                    .foregroundStyle(Palette.t3)
                case .images(let images):
                    ToolImages(images: images, indent: 0)
                }
            }
            if !call.liveThinking.isEmpty {
                SelectableText(key: call.liveThinking) {
                    TextStyling.plain(
                        call.liveThinking, font: ThinkingRow.font, color: TextStyling.secondary)
                }
            }
            if !call.liveText.isEmpty {
                MarkdownText(text: call.liveText, copyable: false)
            }
            if answer, let result = ToolSummary.output(of: call), !result.isEmpty {
                MarkdownText(text: result)
            } else if answer && call.steps.isEmpty && call.liveText.isEmpty {
                Text(call.stopped ? "Stopped before it answered" : "Starting...")
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
            }
        }
        .padding(.leading, 13)
        .overlay(alignment: .leading) {
            Rectangle()
                .fill(Palette.divider)
                .frame(width: 1)
        }
    }
}

@MainActor private func toggle(_ id: String, in shell: Shell) {
    withAnimation(.smooth(duration: 0.2)) {
        if shell.expandedItems.contains(id) {
            shell.expandedItems.remove(id)
        } else {
            shell.expandedItems.insert(id)
        }
    }
}

/// An approval inside the transcript: actionable while pending, a short note after. A
/// pending review never reaches it: it is the bar above the composer (B56).
private struct ApprovalPlaceholder: View {
    let id: String
    let kind: ApprovalKind
    let status: ApprovalStatus
    let rejected: Bool
    let answers: [QuestionAnswer]
    @Environment(Shell.self) private var shell

    var body: some View {
        if status == .pending, let approval = shell.approval(id) {
            ApprovalCard(approval: approval, style: .inline)
        } else if !answers.isEmpty {
            AnsweredQuestions(answers: answers)
        } else if status != .pending {
            SystemLine(text: resolvedText)
                .frame(maxWidth: .infinity)
        }
    }

    private var resolvedText: String {
        if rejected { return RejectConsequence.transcript }
        let what =
            switch kind {
            case .permission, .unknown: "Permission"
            case .question: "Question"
            case .review: "Review"
            case .plan: "Plan"
            case .merge: "Merge"
            }
        switch status {
        case .expired: return "\(what) expired"
        case .superseded: return "\(what) superseded"
        default: return "\(what) resolved"
        }
    }
}

/// An answered question in the transcript (B60): the answer the user gave, an option or
/// their own text, as a message they sent, under the question it answers.
private struct AnsweredQuestions: View {
    let answers: [QuestionAnswer]

    var body: some View {
        VStack(alignment: .trailing, spacing: 10) {
            ForEach(answers, id: \.self) { pair in
                VStack(alignment: .trailing, spacing: 4) {
                    Text(pair.question)
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                        .multilineTextAlignment(.trailing)
                    UserBubble(text: pair.answer, attachments: [], mentions: [], actions: nil)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .trailing)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            answers.map { "\($0.question) You answered: \($0.answer)" }.joined(separator: ". "))
    }
}

/// "+48 -19 3 files"
struct DiffStat: View {
    let additions: Int
    let deletions: Int
    let files: Int

    var body: some View {
        HStack(spacing: 4) {
            Text("+\(additions)").foregroundStyle(StatusTone.review.color)
            Text("-\(deletions)").foregroundStyle(StatusTone.failed.color)
            Text(files == 1 ? "1 file" : "\(files) files")
                .foregroundStyle(Palette.t3)
        }
        .font(.ui(TypeSize.meta))
        .monospacedDigit()
    }
}

struct SystemLine: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.ui(TypeSize.meta))
            .foregroundStyle(Palette.t3)
            .multilineTextAlignment(.center)
            .padding(.horizontal, 10)
            .padding(.vertical, 2)
    }
}

/// Three blinking dots and how long the turn has been running: "Working... 12s". While
/// thinking streams (B59), "Thinking... 4s" previews its latest line and opens to all of
/// it, like the finished "Thought for 8s" block.
private struct WorkingLine: View {
    static let expandID = "live-thinking"

    let since: Date?
    let thinking: Bool
    let thought: String
    @Environment(Shell.self) private var shell

    var body: some View {
        let streams = thinking && !thought.isEmpty
        let expanded = streams && shell.expandedItems.contains(Self.expandID)
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                BlinkingDots()
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    Text(TurnText.working(since: since, at: context.date, thinking: thinking))
                        .font(.ui(TypeSize.meta))
                        .monospacedDigit()
                        .foregroundStyle(Palette.t3)
                }
                if streams {
                    Image(systemName: Icon.chevron)
                        .font(.system(size: 8, weight: .medium))
                        .rotationEffect(.degrees(expanded ? 0 : -90))
                }
            }
            .contentShape(Rectangle())
            .pointerStyle(streams ? .link : nil)
            .onTapGesture {
                if streams {
                    toggle(Self.expandID, in: shell)
                }
            }
            if expanded {
                SelectableText(key: thought) {
                    TextStyling.plain(
                        thought, font: ThinkingRow.font, color: TextStyling.secondary)
                }
                .padding(.leading, 19)
            } else if streams, let line = ThinkingPreview.line(thought) {
                Text(line)
                    .font(.ui(TypeSize.meta))
                    .italic()
                    .lineLimit(1)
                    .truncationMode(.head)
                    .padding(.leading, 19)
            }
        }
        .foregroundStyle(Palette.t3)
    }
}

/// "Worked for 1m 12s" under a finished turn.
private struct TurnEndLine: View {
    let end: TurnEnd

    var body: some View {
        Text(TurnText.ended(end))
            .font(.ui(TypeSize.meta))
            .monospacedDigit()
            .foregroundStyle(Palette.t3)
    }
}

struct BlinkingDots: View {
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 20, paused: reduceMotion)) { context in
            let time = context.date.timeIntervalSinceReferenceDate
            HStack(spacing: 3) {
                ForEach(0..<3) { index in
                    let phase = (time - Double(index) * 0.2) / 1.2 * 2 * .pi
                    Circle()
                        .frame(width: 3.5, height: 3.5)
                        .opacity(reduceMotion ? 0.6 : 0.625 + 0.375 * sin(phase))
                }
            }
        }
        .accessibilityHidden(true)
    }
}

/// The glow behind a message a search hit opened.
private struct Highlight: View {
    let accent: AccentColors

    var body: some View {
        RoundedRectangle.rounded(Radius.card)
            .fill(accent.selection)
            .padding(-6)
            .transition(.opacity)
            .allowsHitTesting(false)
    }
}

/// Loads the transcript's earlier or newer page, around a message a search hit opened.
private struct PageButton: View {
    let title: String
    let load: () async throws -> Void
    @State private var loading = false

    var body: some View {
        Button {
            loading = true
            Task {
                try? await load()
                loading = false
            }
        } label: {
            Label(title, systemImage: "ellipsis")
        }
        .buttonStyle(.nest(.plain))
        .disabled(loading)
        .frame(maxWidth: .infinity)
    }
}

/// Scrolls back to the newest content and resumes following it.
private struct JumpToLatest: View {
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label("Jump to latest", systemImage: "arrow.down")
                .font(.ui(TypeSize.ui))
                .labelStyle(TightLabelStyle())
                .padding(.horizontal, 11)
                .frame(height: 26)
                .sheetSurface(radius: Radius.card)
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .foregroundStyle(Palette.t1)
    }
}

private struct EmptyTranscript: View {
    var body: some View {
        Text("New chat")
            .font(.ui(TypeSize.ui))
            .foregroundStyle(Palette.t3)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 60)
    }
}

/// A `!` command the user ran: the command in mono, its output collapsed as a tool's, and
/// muted notes for a failed exit, a timeout or a cut output (B59).
private struct BashRow: View {
    let id: String
    let command: String
    let output: String
    var notes: [String] = []
    var running = false
    var failure: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 7) {
                Text("!")
                    .font(.mono(TypeSize.meta, .semibold))
                    .foregroundStyle(StatusTone.waiting.color)
                    .frame(width: 12)
                Text(command)
                    .font(.mono(TypeSize.meta))
                    .foregroundStyle(Palette.t1)
                    .lineLimit(1)
                    .truncationMode(.tail)
                    .textSelection(.enabled)
                if running {
                    Spinner()
                }
                ForEach(notes, id: \.self) { note in
                    Text("\u{00B7} \(note)")
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(Palette.t3)
                        .fixedSize()
                }
                Spacer(minLength: 0)
            }
            .frame(minHeight: 21)
            let trimmed = output.trimmingCharacters(in: .newlines)
            if !trimmed.isEmpty {
                ToolOutputView(id: id, output: trimmed)
            }
            if let failure {
                Text(failure)
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(StatusTone.failed.color)
                    .padding(.leading, 19)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Shell command: \(command)")
    }
}

/// A tool result's images as thumbnails, read with the device token; a click opens one
/// full size (B59).
private struct ToolImages: View {
    static let thumbnailWidth: Double = 320

    let images: [ToolImage]
    var indent: Double = 19
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(images) { image in
                Group {
                    if let data = shell.images.data(for: image.attachmentID),
                        let picture = NSImage(data: data)
                    {
                        Button {
                            shell.show(.image(image.attachmentID))
                        } label: {
                            Image(nsImage: picture)
                                .resizable()
                                .aspectRatio(contentMode: .fit)
                                .frame(maxWidth: min(Self.thumbnailWidth, picture.size.width))
                                .clipShape(.rounded(Radius.card))
                        }
                        .buttonStyle(.plain)
                        .pointerStyle(.link)
                        .help("Open full size")
                        .accessibilityLabel("Image from the tool")
                    } else if shell.images.failed(image.attachmentID) {
                        Text("Image not available")
                            .font(.ui(TypeSize.meta))
                            .foregroundStyle(Palette.t3)
                    } else {
                        Spinner()
                    }
                }
                .task(id: image.attachmentID) { await shell.images.load(image.attachmentID) }
            }
        }
        .padding(.leading, indent)
    }
}
