import AppKit
import HarnessKit
import SwiftUI
import UniformTypeIdentifiers

/// The message field of a pane with attach, dictation, the quiet selectors and send. A
/// pixie's composer sends through the pixie and leaves out attachments, selectors and
/// suggestions: its settings live in its details, and it belongs to no project (D057).
struct Composer: View {
    /// The draft's key: the pane's chat, or `Shell.pixieDraft` for a pixie.
    let chat: String
    let pixie: String?
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @FocusState private var focused: Bool
    @State private var dropTargeted = false
    /// Snapshots show the suggestions without focus.
    @Environment(\.revealsHoverControls) private var reveal
    @Environment(\.seeThrough) private var seeThrough
    @Environment(\.glass) private var glass

    init(chat: String) {
        self.chat = chat
        pixie = nil
    }

    init(pixie: String) {
        chat = Shell.pixieDraft(pixie)
        self.pixie = pixie
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
        VStack(spacing: 6) {
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
            field(draft, suggestions: open ? suggestions : nil)
        }
        .padding(.horizontal, 10)
        .padding(.bottom, 10)
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
            text: draft.text, caret: draft.caret, session: session, repo: repo)
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
        let shape = glass.rounded(glass.radius.card)
        let status = shell.dictation.status(for: chat)
        return VStack(alignment: .leading, spacing: 0) {
            if !draft.attachments.isEmpty {
                AttachmentChips(draft: draft)
                    .padding(.top, 6)
            }
            MessageField(draft: draft, focused: $focused) { key in
                handle(key, draft: draft, suggestions: suggestions)
            }
            if let line = status ?? draft.hint {
                HStack(spacing: 6) {
                    if status != nil {
                        ProgressView().controlSize(.mini)
                    }
                    Text(line)
                }
                .font(.ui(TypeSize.label))
                .foregroundStyle(Palette.t3)
                .padding(.horizontal, 2)
                .padding(.bottom, 4)
                .transition(.opacity)
            }
            ControlRow(chat: chat, live: live, pixie: pixie != nil, draft: draft, send: send)
        }
        .padding(EdgeInsets(top: 4, leading: 12, bottom: 6, trailing: 8))
        .background(shape.fill(GlassTint.reading.color(in: glass, seeThrough: seeThrough)))
        .overlay(GlassEdges(shape: shape))
        .overlay {
            if focused || dropTargeted {
                shape.strokeBorder(accent.accent, lineWidth: 2)
            }
        }
        .background(GlassDepth(shape: shape, shadow: glass.style.shadow.panel))
        .onDrop(of: pixie == nil ? [.fileURL] : [], isTargeted: $dropTargeted) { providers in
            loadFiles(providers)
            return true
        }
    }

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

/// A text editor that grows with its text; Return sends and Shift-Return adds a line.
/// `key` gets the keys the composer may handle and says whether it did.
private struct MessageField: View {
    @Bindable var draft: ComposerDraft
    var focused: FocusState<Bool>.Binding
    let key: (ComposerKey) -> Bool

    var body: some View {
        let shown = draft.text + draft.volatile
        Text(shown.isEmpty ? " " : shown + " ")
            .font(.ui(TypeSize.body))
            .lineSpacing(2)
            .padding(.horizontal, 5)
            .padding(.vertical, 6)
            .frame(maxWidth: .infinity, minHeight: 40, maxHeight: 160, alignment: .topLeading)
            .fixedSize(horizontal: false, vertical: true)
            .hidden()
            .overlay(alignment: .topLeading) {
                if shown.isEmpty {
                    Text("Message")
                        .font(.ui(TypeSize.body))
                        .foregroundStyle(Palette.t3)
                        .padding(.horizontal, 5)
                        .padding(.vertical, 6)
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
                    .font(.ui(TypeSize.body))
                    .lineSpacing(2)
                    .scrollContentBackground(.hidden)
                    .scrollIndicators(.never)
                    .foregroundStyle(Palette.t1)
                    .padding(.vertical, 6)
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
            .font(.ui(TypeSize.body))
            .lineSpacing(2)
            .padding(.horizontal, 5)
            .padding(.vertical, 6)
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
    @Environment(\.glass) private var glass

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 7) {
            Image(systemName: Icon.warning)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(StatusTone.waiting.textColor)
            Text(text)
                .font(.ui(TypeSize.small))
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
        .padding(.vertical, 8)
        .background(
            StatusTone.waiting.soft, in: glass.rounded(glass.radius.small)
        )
        .overlay(
            glass.rounded(glass.radius.small)
                .strokeBorder(StatusTone.waiting.textColor.opacity(0.25))
        )
        .accessibilityElement(children: .combine)
    }
}

private struct AttachmentChips: View {
    let draft: ComposerDraft
    @Environment(\.glass) private var glass

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
                            .font(.ui(TypeSize.label))
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
                    .frame(height: 24)
                    .background(
                        Palette.fill, in: glass.rounded(glass.radius.small))
                }
            }
        }
        .scrollIndicators(.never)
    }
}

/// Attach, mic, Model, Thinking, Permission, then Worktree for new chats or the context
/// meter for open ones, and send (Queue or Interrupt while Claude works). A pixie's row
/// has the mic, the context meter and send.
private struct ControlRow: View {
    /// The draft's key.
    let chat: String
    /// The chat that runs, if any.
    let live: String?
    let pixie: Bool
    let draft: ComposerDraft
    let send: () -> Void
    @Environment(Shell.self) private var shell
    @Environment(\.paneFit) private var fit

    var body: some View {
        let session = live.flatMap(shell.sessions.session)
        let isDraft = shell.isDraft(chat)
        let working = session.map { $0.state.isInFlight } ?? false
        let listening = shell.dictation.activeChat == chat
        HStack(spacing: 4) {
            if !pixie {
                Button(action: attach) {
                    Image(systemName: Icon.attach).font(.system(size: 13))
                }
                .buttonStyle(.harness(.ghost, iconOnly: true))
                .help("Attach")
                .accessibilityLabel("Attach")
            }
            MicButton(listening: listening) { toggleDictation() }
            if !pixie {
                ModelMenu(chat: chat, model: isDraft ? draft.model : session?.model)
                EffortMenu(
                    chat: chat, model: isDraft ? draft.model : session?.model,
                    effort: isDraft ? draft.effort : session?.effort, isOpen: !isDraft)
                PermissionMenu(
                    chat: chat, mode: isDraft ? draft.permission : session?.permissionMode)
            }
            if isDraft && shell.repo?.git != false {
                ModeMenu(draft: draft)
            } else if let live, let context = session?.context,
                let label = fit.context.label(context)
            {
                ContextMeter(chat: live, context: context, label: label)
            }
            Spacer(minLength: 4)
            SendButton(
                mode: SendButtonMode.of(
                    working: working,
                    hasText: !draft.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty),
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
            .padding(.leading, 4)
        }
    }

    private func attach() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        panel.prompt = "Attach"
        guard panel.runModal() == .OK else { return }
        shell.attach(panel.urls, to: chat)
    }

    private func toggleDictation() {
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

private struct MicButton: View {
    let listening: Bool
    let action: () -> Void
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        if listening {
            Button(action: action) {
                Image(systemName: "mic.fill")
                    .font(.system(size: 13))
                    .foregroundStyle(StatusTone.failed.textColor)
                    .frame(width: 28, height: 28)
                    .background(StatusTone.failed.soft, in: Circle())
                    .background {
                        if !reduceMotion {
                            PulseRing(color: StatusTone.failed.soft, size: 28)
                        }
                    }
            }
            .buttonStyle(.plain)
            .pointerStyle(.link)
            .help("Stop dictation")
            .accessibilityLabel("Stop dictation")
        } else {
            Button(action: action) {
                Image(systemName: Icon.mic).font(.system(size: 13))
            }
            .buttonStyle(.harness(.ghost, iconOnly: true))
            .help("Dictate")
            .accessibilityLabel("Dictate")
        }
    }
}

/// Send; while Claude works, Queue once text is typed and Interrupt while it is empty.
private struct SendButton: View {
    let mode: SendButtonMode
    let sending: Bool
    let action: (SendButtonMode) -> Void
    @Environment(\.accentColors) private var accent
    @Environment(\.glass) private var glass

    var body: some View {
        Button {
            action(mode)
        } label: {
            switch mode {
            case .interrupt:
                Image(systemName: Icon.stop).font(.system(size: 10))
                    .foregroundStyle(StatusTone.failed.textColor)
                    .frame(width: 28, height: 28)
                    .background(StatusTone.failed.soft, in: glass.control)
            case .queue:
                Text("Queue")
                    .font(.ui(TypeSize.small, .semibold))
                    .foregroundStyle(accent.onAccent)
                    .padding(.horizontal, 12)
                    .frame(height: 28)
                    .background(accent.accent, in: glass.control)
            case .send:
                Group {
                    if sending {
                        ProgressView().controlSize(.small).tint(accent.onAccent)
                    } else {
                        Image(systemName: Icon.send).font(.system(size: 13, weight: .bold))
                    }
                }
                .foregroundStyle(accent.onAccent)
                .frame(width: 28, height: 28)
                .background(accent.accent, in: glass.control)
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

/// "context 41%" beside the selectors, amber above 80%; opens the numbers and Compact.
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
                .font(.ui(TypeSize.label, .medium))
                .monospacedDigit()
                .foregroundStyle(color)
                .lineLimit(1)
                .padding(.horizontal, 6)
                .frame(height: 26)
                .background(
                    hovering ? Palette.fill : .clear,
                    in: RoundedRectangle(cornerRadius: 7, style: .continuous)
                )
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
        context.isHigh ? StatusTone.waiting.textColor : hovering ? Palette.t2 : Palette.t3
    }
}
