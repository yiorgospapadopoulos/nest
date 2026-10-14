import AppKit
import HarnessKit
import SwiftUI
import UniformTypeIdentifiers

/// The message field of a pane: an oval field with send (or stop) inside, and under it a
/// plain row with attach and dictation on the left and the quiet selectors on the right. A
/// pixie's composer sends through the pixie and leaves out attachments, selectors and
/// suggestions: its settings live in its details, and it belongs to no project (D072).
/// The empty workspace's composer (`init(start:)`, B39) is the approved design's: a box with the
/// working copy on top, the field, and attach, model, thinking and permission chips with
/// a square send under it.
struct Composer: View {
    /// The draft's key: the pane's chat, or `Shell.pixieDraft` for a pixie.
    let chat: String
    let pixie: String?
    /// The empty workspace's composer.
    private var start = false
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @FocusState private var focused: Bool
    @State private var dropTargeted = false
    /// Snapshots show the suggestions without focus.
    @Environment(\.revealsHoverControls) private var reveal

    init(chat: String) {
        self.chat = chat
        pixie = nil
    }

    init(pixie: String) {
        chat = Shell.pixieDraft(pixie)
        self.pixie = pixie
    }

    init(start draft: String) {
        chat = draft
        pixie = nil
        start = true
    }

    /// The chat that runs: the pane's, or the pixie's current one (none before its first
    /// message).
    private var live: String? {
        guard let pixie else { return chat }
        return shell.pixies.pixies.first { $0.id == pixie }?.chatSessionID
    }

    var body: some View {
        let draft = shell.draft(for: chat)
        let suggestions = suggestions(draft)
        let open = draft.completion.isOpen(suggestions)
        VStack(spacing: 4) {
            if let blocked = draft.blocked {
                BlockedNote(text: blocked) { withAnimation { draft.blocked = nil } }
                    .transition(.opacity.combined(with: .move(edge: .bottom)))
            }
            if open, let suggestions {
                SuggestionList(list: suggestions, active: draft.completion.active(in: suggestions))
                {
                    shell.complete($0, in: chat)
                }
                .transition(.opacity)
            }
            if start {
                StartBox(
                    chat: chat, draft: draft, focused: $focused, dropTargeted: dropTargeted
                ) {
                    MessageField(draft: draft, focused: $focused, style: .start) { key in
                        handle(key, draft: draft, suggestions: open ? suggestions : nil)
                    }
                } send: {
                    send()
                }
                .onDrop(of: [.fileURL], isTargeted: $dropTargeted) { providers in
                    loadFiles(providers)
                    return true
                }
            } else {
                field(draft, suggestions: open ? suggestions : nil)
                ControlRow(chat: chat, live: live, pixie: pixie != nil, draft: draft)
            }
        }
        .padding(.horizontal, start ? 0 : 12)
        .padding(.bottom, start ? 0 : 6)
        .onChange(of: suggestions?.trigger) { _, trigger in
            draft.completion.update(for: trigger)
        }
        .task(id: draft.wantsFocus) {
            guard draft.wantsFocus else { return }
            // Once the field is in the window, so focus lands in it.
            await Task.yield()
            focused = true
            draft.wantsFocus = false
        }
        .task(id: commandSource(suggestions)) {
            guard suggestions?.trigger.kind == .command, let repo = shell.project else { return }
            await shell.completions.loadCommands(session: session, repo: repo)
        }
        .task(id: mentionedPixies(suggestions)) {
            await shell.pixies.loadSoulLines(mentionedPixies(suggestions))
        }
        .task(id: fileQuery(suggestions)) {
            guard let query = fileQuery(suggestions), let session else { return }
            // Typing pauses this long before the files are asked for.
            try? await Task.sleep(for: .milliseconds(150))
            guard !Task.isCancelled else { return }
            await shell.completions.searchFiles(session: session, query: query)
        }
    }

    /// The chat's session id; nil for a new chat, which completes its project's commands.
    private var session: String? { shell.isDraft(chat) ? nil : chat }

    private func suggestions(_ draft: ComposerDraft) -> CompletionList? {
        guard pixie == nil, focused || reveal, let repo = shell.project else { return nil }
        return shell.completions.suggestions(
            text: draft.text, caret: draft.caret, session: session, repo: repo,
            mentions: shell.pixieMentions(forChat: chat))
    }

    /// The pixies the "@" list offers, whose souls' first lines it shows.
    private func mentionedPixies(_ list: CompletionList?) -> [String] {
        guard list?.trigger.kind == .file else { return [] }
        return list?.items.compactMap { item in
            if case .pixie(let pixie, _) = item.mention { pixie.id } else { nil }
        } ?? []
    }

    private func commandSource(_ list: CompletionList?) -> String? {
        list?.trigger.kind == .command ? "\(session ?? "repo"):\(shell.project ?? "")" : nil
    }

    private func fileQuery(_ list: CompletionList?) -> String? {
        list?.trigger.kind == .file ? list?.trigger.query : nil
    }

    /// Arrows, Tab, Return and Esc: the suggestion list's while it shows, else send,
    /// interrupt and recall.
    private func handle(_ key: ComposerKey, draft: ComposerDraft, suggestions: CompletionList?)
        -> Bool
    {
        let working = live.flatMap(shell.sessions.session)?.state.isInFlight ?? false
        let action = ComposerKeyAction.of(
            key, suggesting: suggestions != nil, isEmpty: draft.text.isEmpty, working: working)
        switch action {
        case .move(let delta):
            if let suggestions {
                draft.completion.move(delta, in: suggestions)
            }
        case .insert:
            if let suggestions, let chosen = draft.completion.chosen(in: suggestions) {
                shell.complete(chosen, in: chat)
            }
        case .close:
            if let suggestions {
                withAnimation(.smooth(duration: 0.15)) { draft.completion.dismiss(suggestions) }
            }
        case .send:
            send()
        case .interrupt:
            if let live {
                shell.interrupt(live)
            }
        case .recall:
            if let live {
                shell.recallLastMessage(live, into: chat)
            }
        case .ignore:
            return false
        }
        return true
    }

    private func send() {
        if let pixie {
            shell.sendToPixie(pixie)
        } else {
            shell.send(chat)
        }
    }

    private func field(_ draft: ComposerDraft, suggestions: CompletionList?) -> some View {
        let shape = RoundedRectangle.rounded(Self.fieldRadius)
        let status = shell.dictation.status(for: chat)
        return HStack(alignment: .bottom, spacing: 6) {
            VStack(alignment: .leading, spacing: 0) {
                if !draft.attachments.isEmpty {
                    AttachmentChips(draft: draft)
                        .padding(.top, 6)
                }
                MessageField(draft: draft, focused: $focused, style: .pane) { key in
                    handle(key, draft: draft, suggestions: suggestions)
                }
                if let line = status ?? draft.hint {
                    HStack(spacing: 6) {
                        if status != nil {
                            ProgressView().controlSize(.mini)
                        }
                        Text(line)
                    }
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                    .padding(.horizontal, 5)
                    .padding(.bottom, 5)
                    .transition(.opacity)
                }
            }
            SendControl(chat: chat, live: live, draft: draft, send: send)
                .padding(.bottom, 5)
        }
        .padding(.leading, 13)
        .padding(.trailing, 5)
        .background(shape.fill(Palette.soft))
        .overlay(
            shape.strokeBorder(
                focused || dropTargeted ? accent.focus : Palette.divider, lineWidth: 1)
        )
        .onDrop(of: pixie == nil ? [.fileURL] : [], isTargeted: $dropTargeted) { providers in
            loadFiles(providers)
            return true
        }
    }

    /// Half the one-line field's height: an oval while it holds one line, a rounded field
    /// as it grows.
    static let fieldRadius = 19.0

    private func loadFiles(_ providers: [NSItemProvider]) {
        for provider in providers {
            // Called on a background queue: nonisolated, then back to the main actor.
            _ = provider.loadObject(ofClass: URL.self) { @Sendable url, _ in
                guard let url else { return }
                Task { @MainActor in shell.attach([url], to: chat) }
            }
        }
    }
}

/// How a message field is set: a pane's, or the empty workspace's (the approved design's 14 point
/// text on 22 point lines).
struct MessageFieldStyle {
    let size: Double
    let lineSpacing: Double
    let verticalPadding: Double
    let minHeight: Double
    let placeholder: String
    let placeholderColor: Color

    static let pane = MessageFieldStyle(
        size: TypeSize.reading, lineSpacing: 2, verticalPadding: 10, minHeight: 38,
        placeholder: "Message", placeholderColor: Palette.t3)
    static let start = MessageFieldStyle(
        size: 14, lineSpacing: 5, verticalPadding: 6, minHeight: 34,
        placeholder: "Ask, build, / for commands, @ for references...",
        placeholderColor: Ink.content(0.4))
}

/// A text editor that grows with its text; Return sends and Shift-Return adds a line.
/// `key` gets the keys the composer may handle and says whether it did.
private struct MessageField: View {
    @Bindable var draft: ComposerDraft
    var focused: FocusState<Bool>.Binding
    let style: MessageFieldStyle
    let key: (ComposerKey) -> Bool

    var body: some View {
        let shown = draft.text + draft.volatile
        Text(shown.isEmpty ? " " : shown + " ")
            .font(.ui(style.size))
            .lineSpacing(style.lineSpacing)
            .padding(.horizontal, 5)
            .padding(.vertical, style.verticalPadding)
            .frame(
                maxWidth: .infinity, minHeight: style.minHeight, maxHeight: 160,
                alignment: .topLeading
            )
            .fixedSize(horizontal: false, vertical: true)
            .hidden()
            .overlay(alignment: .topLeading) {
                if shown.isEmpty {
                    Text(style.placeholder)
                        .font(.ui(style.size))
                        .foregroundStyle(style.placeholderColor)
                        .lineLimit(1)
                        .padding(.horizontal, 5)
                        .padding(.vertical, style.verticalPadding)
                        .allowsHitTesting(false)
                }
            }
            .overlay(alignment: .topLeading) {
                if !draft.volatile.isEmpty {
                    volatileText
                }
            }
            .overlay {
                TextEditor(text: $draft.text, selection: $draft.selection)
                    .font(.ui(style.size))
                    .lineSpacing(style.lineSpacing)
                    .scrollContentBackground(.hidden)
                    .scrollIndicators(.never)
                    .foregroundStyle(Palette.t1)
                    .padding(.vertical, style.verticalPadding)
                    .focused(focused)
                    .accessibilityLabel("Message")
                    .onKeyPress(
                        keys: [.return, .upArrow, .downArrow, .tab, .escape], phases: .down
                    ) { press in
                        guard let pressed = Self.composerKey(press) else { return .ignored }
                        return key(pressed) ? .handled : .ignored
                    }
            }
    }
}

extension MessageField {
    /// Only plain presses (Shift for Return) count; with other modifiers the field or the
    /// menus handle the key.
    fileprivate static func composerKey(_ press: KeyPress) -> ComposerKey? {
        let modifiers = press.modifiers.subtracting(.shift)
        guard modifiers.isEmpty else { return nil }
        switch press.key {
        case .return: return .enter(shift: press.modifiers.contains(.shift))
        case .upArrow: return .up
        case .downArrow: return .down
        case .tab where !press.modifiers.contains(.shift): return .tab
        case .escape: return .escape
        default: return nil
        }
    }

    /// Dictation still being recognized, drawn lighter right after the text: the text
    /// itself is laid out invisibly so the guess lines up with the editor's last line.
    fileprivate var volatileText: some View {
        var typed = AttributedString(draft.text)
        typed.foregroundColor = .clear
        var guess = AttributedString(draft.volatile)
        guess.foregroundColor = Palette.t3
        return Text(typed + guess)
            .font(.ui(style.size))
            .lineSpacing(style.lineSpacing)
            .padding(.horizontal, 5)
            .padding(.vertical, style.verticalPadding)
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .allowsHitTesting(false)
            .accessibilityLabel("Dictating: \(draft.volatile)")
    }
}

/// Why the last message was refused, above the composer, such as the chat being open in
/// Claude Code.
private struct BlockedNote: View {
    let text: String
    let dismiss: () -> Void

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 7) {
            Image(systemName: Icon.warning)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(StatusTone.waiting.color)
            Text(text)
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t1)
                .frame(maxWidth: .infinity, alignment: .leading)
                .fixedSize(horizontal: false, vertical: true)
            Button(action: dismiss) {
                Image(systemName: Icon.close).font(.system(size: 8, weight: .bold))
            }
            .buttonStyle(SmallSquareStyle())
            .help("Dismiss")
            .accessibilityLabel("Dismiss")
        }
        .padding(.horizontal, 11)
        .padding(.vertical, 7)
        .softFill()
        .accessibilityElement(children: .combine)
    }
}

private struct AttachmentChips: View {
    let draft: ComposerDraft

    var body: some View {
        ScrollView(.horizontal) {
            HStack(spacing: 6) {
                ForEach(draft.attachments) { attachment in
                    HStack(spacing: 5) {
                        if attachment.uploaded == nil {
                            ProgressView().controlSize(.mini)
                        } else {
                            Image(systemName: Icon.attach).font(.system(size: 10))
                        }
                        Text(attachment.filename)
                            .font(.ui(TypeSize.meta))
                            .lineLimit(1)
                        Button {
                            draft.remove(attachment.id)
                        } label: {
                            Image(systemName: Icon.close).font(.system(size: 8, weight: .bold))
                        }
                        .buttonStyle(SmallSquareStyle())
                        .accessibilityLabel("Remove \(attachment.filename)")
                    }
                    .foregroundStyle(Palette.t2)
                    .padding(.leading, 8)
                    .padding(.trailing, 3)
                    .frame(height: 22)
                    .background(Palette.selection, in: .rounded(Radius.button))
                }
            }
        }
        .scrollIndicators(.never)
    }
}

/// Under the field: attach and the mic on the left, then Model, Thinking, Permission and
/// Worktree for new chats or the context meter for open ones on the right. A pixie's row
/// has the mic and the context meter.
private struct ControlRow: View {
    /// The draft's key.
    let chat: String
    /// The chat that runs, if any.
    let live: String?
    let pixie: Bool
    let draft: ComposerDraft
    @Environment(Shell.self) private var shell
    @Environment(\.paneFit) private var fit

    var body: some View {
        let session = live.flatMap(shell.sessions.session)
        let isDraft = shell.isDraft(chat)
        let listening = shell.dictation.activeChat == chat
        HStack(spacing: fit.compact ? 0 : 2) {
            if !pixie {
                Button(action: attach) {
                    Image(systemName: Icon.plus)
                        .font(.system(size: 13, weight: .regular))
                        .foregroundStyle(Palette.t3)
                }
                .buttonStyle(.harness(.plain, iconOnly: true))
                .help("Attach")
                .accessibilityLabel("Attach")
            }
            MicButton(listening: listening) { toggleDictation() }
            Spacer(minLength: 4)
            if !pixie {
                ModelMenu(chat: chat, model: isDraft ? draft.model : session?.model)
                EffortMenu(
                    chat: chat, model: isDraft ? draft.model : session?.model,
                    effort: isDraft ? draft.effort : session?.effort, isOpen: !isDraft)
                PermissionMenu(
                    chat: chat, model: isDraft ? draft.model : session?.model,
                    mode: isDraft ? draft.permission : session?.permissionMode)
            }
            if isDraft && shell.repo?.git != false {
                ModeMenu(draft: draft)
            } else if let live, let context = session?.context,
                let label = fit.context.label(context)
            {
                ContextMeter(chat: live, context: context, label: label)
            }
        }
        .padding(.horizontal, 4)
        .frame(height: 30)
    }

    private var actions: ComposerActions {
        ComposerActions(shell: shell, chat: chat, live: live, pixie: pixie, draft: draft)
    }

    private func attach() {
        actions.attach()
    }

    private func toggleDictation() {
        actions.toggleDictation()
    }
}

/// Attach and dictation, shared by the pane's control row and the empty workspace's box.
@MainActor
private struct ComposerActions {
    let shell: Shell
    let chat: String
    let live: String?
    let pixie: Bool
    let draft: ComposerDraft

    func attach() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        panel.prompt = "Attach"
        guard panel.runModal() == .OK else { return }
        shell.attach(panel.urls, to: chat)
    }

    func toggleDictation() {
        let terms = DictationVocabulary.terms(
            repo: pixie ? nil : shell.project, branch: live.flatMap(shell.sessions.session)?.branch,
            items: live.flatMap(shell.model.transcripts.existing)?.items ?? [])
        Task {
            let hint = await shell.dictation.toggle(for: chat, draft: draft, terms: terms)
            withAnimation { draft.hint = hint }
            if hint != nil {
                try? await Task.sleep(for: .seconds(4))
                withAnimation {
                    if draft.hint == hint {
                        draft.hint = nil
                    }
                }
            }
        }
    }
}

/// The empty workspace's composer, the approved design's: a box with a 3 percent fill and an 8 point
/// corner, its border 10 percent (20 while focused); on top the working copy, then the
/// field, then attach, the model, thinking and permission chips, and a square send.
private struct StartBox<Field: View>: View {
    let chat: String
    let draft: ComposerDraft
    var focused: FocusState<Bool>.Binding
    let dropTargeted: Bool
    @ViewBuilder let field: () -> Field
    let send: () -> Void
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        let shape = RoundedRectangle.rounded(8)
        let actions = ComposerActions(
            shell: shell, chat: chat, live: nil, pixie: false, draft: draft)
        let status = shell.dictation.status(for: chat)
        VStack(alignment: .leading, spacing: 0) {
            if shell.repo?.git != false {
                WorkingCopyRow(draft: draft, branch: shell.repo?.defaultBranch)
                    .padding(.horizontal, 12)
                    .padding(.top, 10)
            }
            if !draft.attachments.isEmpty {
                AttachmentChips(draft: draft)
                    .padding(.horizontal, 12)
                    .padding(.top, 8)
            }
            field()
                .padding(.horizontal, 7)
            if let line = status ?? draft.hint {
                HStack(spacing: 6) {
                    if status != nil {
                        ProgressView().controlSize(.mini)
                    }
                    Text(line)
                }
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Ink.content(0.45))
                .padding(.horizontal, 12)
                .padding(.bottom, 4)
                .transition(.opacity)
            }
            HStack(spacing: 4) {
                Button(action: actions.attach) {
                    Image(systemName: Icon.plus).font(.system(size: 13, weight: .light))
                }
                .buttonStyle(StartToolStyle())
                .help("Attach")
                .accessibilityLabel("Attach")
                ModelPill(chat: chat, model: draft.model)
                EffortPill(chat: chat, model: draft.model, effort: draft.effort)
                PermissionPill(chat: chat, model: draft.model, mode: draft.permission)
                Spacer(minLength: 4)
                MicButton(listening: shell.dictation.activeChat == chat) {
                    actions.toggleDictation()
                }
                StartSendButton(draft: draft, send: send)
            }
            .padding(.horizontal, 8)
            .padding(.bottom, 8)
        }
        .background {
            if scheme == .dark {
                shape.fill(Ink.content(0.03))
                    .background(.ultraThinMaterial, in: shape)
            } else {
                shape.fill(Palette.windowOpaque)
                    .shadow(color: Ink.content(0.09), radius: 12, y: 6)
                    .shadow(color: Ink.content(0.06), radius: 3, y: 2)
            }
        }
        .overlay(
            shape.strokeBorder(
                dropTargeted
                    ? accent.focus : Ink.content(focused.wrappedValue ? 0.2 : 0.1),
                lineWidth: 1)
        )
    }
}

/// The working copy over the field: where the chat works (a new worktree or the current
/// checkout, the approved design's words for harness's Worktree and In place) and its branch.
private struct WorkingCopyRow: View {
    @Bindable var draft: ComposerDraft
    let branch: String?

    var body: some View {
        let worktree = draft.mode != .inPlace
        HStack(spacing: 10) {
            Menu {
                Section("Workspace") {
                    OptionItem(
                        title: "Current checkout", detail: "The project folder itself",
                        checked: !worktree
                    ) { draft.mode = .inPlace }
                    OptionItem(
                        title: "New worktree", detail: "A separate checkout on its own branch",
                        checked: worktree
                    ) { draft.mode = .worktree }
                }
            } label: {
                GitTrigger(
                    icon: worktree ? "folder.badge.plus" : Icon.folder,
                    label: worktree ? "New worktree" : "Current checkout", interactive: true)
            }
            .menuStyle(.button)
            .buttonStyle(.plain)
            .menuIndicator(.hidden)
            .fixedSize()
            .help("Workspace: \(worktree ? "New worktree" : "Current checkout")")
            .accessibilityLabel("Workspace \(worktree ? "New worktree" : "Current checkout")")
            if let branch {
                let label = worktree ? "From \(branch)" : branch
                GitTrigger(icon: Icon.branch, label: label, interactive: false)
                    .help(worktree ? "Created from \(branch)" : "Branch \(branch)")
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel(worktree ? "Created from \(branch)" : "Branch \(branch)")
            }
            Spacer(minLength: 0)
        }
        .padding(.leading, -6)
    }
}

/// the approved design's git trigger: 24 points tall, 12 point text at 55 percent, a 14 point icon,
/// an 8 percent fill while hovered.
private struct GitTrigger: View {
    let icon: String
    let label: String
    let interactive: Bool
    @State private var hovering = false

    var body: some View {
        let lit = interactive && hovering
        HStack(spacing: 6) {
            Image(systemName: icon).font(.system(size: 11))
            Text(label).lineLimit(1).truncationMode(.tail)
        }
        .font(.ui(12))
        .foregroundStyle(Ink.content(lit ? 1 : 0.55))
        .padding(.horizontal, 6)
        .frame(height: 24)
        .fixedSize()
        .background(lit ? Ink.content(0.08) : .clear, in: .rounded(6))
        .contentShape(Rectangle())
        .onHover { hovering = $0 }
        .pointerStyle(interactive ? .link : nil)
    }
}

/// The square send: white with a black arrow in dark (content and base in light), at 30
/// percent until there is something to send.
private struct StartSendButton: View {
    let draft: ComposerDraft
    let send: () -> Void
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        let ready = !draft.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        let dark = scheme == .dark
        let fill = dark ? Color.white : Ink.content(1)
        let mark = dark ? Color.black : Palette.windowOpaque
        Button(action: send) {
            Group {
                if draft.sending {
                    ProgressView().controlSize(.mini).tint(mark)
                } else {
                    Image(systemName: Icon.send).font(.system(size: 12, weight: .bold))
                }
            }
            .foregroundStyle(mark.opacity(ready || draft.sending ? 1 : 0.4))
            .frame(width: 26, height: 26)
            .background(fill.opacity(ready || draft.sending ? 1 : 0.3), in: .rounded(6))
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .disabled(!ready || draft.sending)
        .help("Send")
        .accessibilityLabel("Send")
    }
}

/// The + under the field: a 26 point square on a 10 percent fill, its icon at 50 percent.
private struct StartToolStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        HoverReader { hovering in
            configuration.label
                .foregroundStyle(Ink.content(0.5))
                .frame(width: 26, height: 26)
                .background(
                    Ink.content(hovering || configuration.isPressed ? 0.15 : 0.1),
                    in: .rounded(6)
                )
                .contentShape(Rectangle())
                .pointerStyle(.link)
        }
    }
}

private struct MicButton: View {
    let listening: Bool
    let action: () -> Void
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        if listening {
            Button(action: action) {
                Image(systemName: "mic.fill")
                    .font(.system(size: 11))
                    .foregroundStyle(StatusTone.failed.color)
                    .frame(width: 22, height: 22)
                    .background(StatusTone.failed.soft, in: Circle())
                    .background {
                        if !reduceMotion {
                            PulseRing(color: StatusTone.failed.soft, size: 22)
                        }
                    }
            }
            .buttonStyle(.plain)
            .pointerStyle(.link)
            .help("Stop dictation")
            .accessibilityLabel("Stop dictation")
        } else {
            Button(action: action) {
                Image(systemName: Icon.mic)
                    .font(.system(size: 12))
                    .foregroundStyle(Palette.t3)
            }
            .buttonStyle(.harness(.plain, iconOnly: true))
            .help("Dictate")
            .accessibilityLabel("Dictate")
        }
    }
}

/// The send button for the composer's state: Send, or while Claude works Queue once text
/// is typed and Interrupt (stop) while it is empty.
private struct SendControl: View {
    let chat: String
    let live: String?
    let draft: ComposerDraft
    let send: () -> Void
    @Environment(Shell.self) private var shell

    var body: some View {
        let working = live.flatMap(shell.sessions.session)?.state.isInFlight ?? false
        let hasText = !draft.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        SendButton(
            mode: SendButtonMode.of(working: working, hasText: hasText), hasText: hasText,
            sending: draft.sending
        ) { mode in
            if mode == .interrupt {
                if let live {
                    shell.interrupt(live)
                }
            } else {
                send()
            }
        }
    }
}

/// A round button inside the field: the accent's fill once there is something to send,
/// a quiet fill while empty; a round stop while Claude works; Queue as a small oval.
private struct SendButton: View {
    let mode: SendButtonMode
    let hasText: Bool
    let sending: Bool
    let action: (SendButtonMode) -> Void
    @Environment(\.accentColors) private var accent

    var body: some View {
        Button {
            action(mode)
        } label: {
            switch mode {
            case .interrupt:
                Image(systemName: Icon.stop).font(.system(size: 8))
                    .foregroundStyle(Palette.t1)
                    .frame(width: 28, height: 28)
                    .background(Palette.selection, in: Circle())
            case .queue:
                Text("Queue")
                    .font(.ui(TypeSize.button, .medium))
                    .foregroundStyle(accent.onAccent)
                    .padding(.horizontal, 11)
                    .frame(height: 28)
                    .background(accent.accent, in: Capsule())
            case .send:
                let ready = hasText || sending
                Group {
                    if sending {
                        ProgressView().controlSize(.small).tint(accent.onAccent)
                    } else {
                        Image(systemName: Icon.send).font(.system(size: 12, weight: .semibold))
                    }
                }
                .foregroundStyle(ready ? accent.onAccent : Palette.t2)
                .frame(width: 28, height: 28)
                .background(ready ? accent.accent : Palette.selection, in: Circle())
            }
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .help(help)
        .accessibilityLabel(label)
    }

    private var label: String {
        switch mode {
        case .send: "Send"
        case .queue: "Queue"
        case .interrupt: "Interrupt"
        }
    }

    private var help: String {
        switch mode {
        case .send: "Send"
        case .queue: "Queue: sent when Claude finishes this turn"
        case .interrupt: "Interrupt (Esc)"
        }
    }
}

/// "context 41%" at the end of the row in quiet grey, amber above 80%; opens the numbers
/// and Compact.
private struct ContextMeter: View {
    let chat: String
    let context: SessionContext
    /// "context 41%", or "41%" in a narrow pane.
    let label: String
    @Environment(Shell.self) private var shell
    @State private var hovering = false

    var body: some View {
        Menu {
            Section(context.detail) {
                Button("Compact") { shell.compact(chat) }
            }
        } label: {
            Text(label)
                .font(.ui(TypeSize.meta))
                .monospacedDigit()
                .foregroundStyle(color)
                .lineLimit(1)
                .padding(.horizontal, 5)
                .frame(height: Metrics.buttonHeight)
                .background(hovering ? Palette.soft : .clear, in: .rounded(Radius.button))
                .contentShape(Rectangle())
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .menuIndicator(.hidden)
        .fixedSize()
        .onHover { hovering = $0 }
        .help("Context window: \(context.detail)")
        .accessibilityLabel("Context \(Int(context.percent.rounded())) percent")
    }

    private var color: Color {
        context.isHigh ? StatusTone.waiting.color : hovering ? Palette.t2 : Palette.t3
    }
}
