import AppKit
import NestKit
import SwiftUI
import UniformTypeIdentifiers

/// The message field of a pane: an oval field with send (or stop) inside, and under it a
/// plain row with attach and dictation on the left and the quiet selectors on the right. A
/// pixie's composer sends through the pixie and leaves out attachments, selectors and
/// suggestions: its settings live in its details, and it belongs to no project (D072).
/// The empty workspace's composer (`init(start:)`, B90) is the pane's, with where the new
/// chat works in the row under the field.
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
    /// Esc Esc opens Rewind, as in Claude Code (B59).
    @State private var escapes = EscapeRepeat()
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
            if let live, !start {
                PendingMessages(chat: live, draftKey: chat)
            }
            if let blocked = draft.blocked {
                BlockedNote(text: blocked) { withAnimation { draft.blocked = nil } }
                    .transition(.opacity.combined(with: .move(edge: .bottom)))
            } else if shell.isDraft(chat),
                let hint = shell.providers.signInHint(for: draft.provider)
            {
                // The engine chosen for the new chat said it is not signed in (B91).
                SignInNote(text: hint)
                    .transition(.opacity)
            }
            if let picker = draft.picker, pixie == nil {
                CommandPicker(chat: chat, picker: picker, draft: draft)
                    .transition(.opacity)
            } else if open, let suggestions {
                SuggestionList(list: suggestions, active: draft.completion.active(in: suggestions))
                {
                    shell.complete($0, in: chat)
                }
                .transition(.opacity)
            }
            if pixie == nil && !start && shell.isDraft(chat) && shell.repo?.git != false {
                // The same choice as the empty workspace's, before the first message; once
                // the chat exists its header says where it works (B55).
                WorkingCopyRow(draft: draft, repo: shell.repo)
                    .padding(.horizontal, 4)
            }
            field(draft, suggestions: open ? suggestions : nil)
            ControlRow(chat: chat, live: live, pixie: pixie != nil, start: start, draft: draft)
        }
        .padding(.horizontal, start ? 0 : 12)
        .padding(.bottom, start ? 0 : 6)
        .background {
            ImagePasteCatcher(isActive: focused && pixie == nil) { urls in
                shell.attach(urls, to: chat)
            } attachData: { data, type in
                shell.attach(data: data, type: type, to: chat)
            }
        }
        .alert(
            "Replace your draft?",
            isPresented: Binding(
                get: { draft.offered != nil }, set: { if !$0 { draft.offered = nil } }),
            presenting: draft.offered
        ) { message in
            Button("Replace") { draft.fill(message, keepingDraft: false) }
            Button("Keep both", role: .cancel) { draft.fill(message, keepingDraft: true) }
        } message: { _ in
            Text(
                "The message you took back goes into the composer. Keep both puts it before your draft."
            )
        }
        .confirmationDialog(
            "Save to memory",
            isPresented: Binding(
                get: { draft.memory != nil }, set: { if !$0 { draft.memory = nil } }),
            presenting: draft.memory
        ) { memory in
            ForEach(MemoryScope.choices(pixie: pixie != nil), id: \.self) { scope in
                Button(scope.label) { shell.saveMemory(memory, scope: scope, from: chat) }
            }
            Button("Cancel", role: .cancel) { draft.memory = nil }
        } message: { memory in
            Text(
                "\u{201C}\(memory)\u{201D} goes into CLAUDE.md: the project's, or yours for all projects."
            )
        }
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
            guard suggestions?.trigger.kind == .command, let repo = shell.project,
                shell.supports(.slashCommands, chat: chat)
            else { return }
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

    /// The chat's session id: the pixie's chat for a pixie, nil for a new chat, which
    /// completes its project's commands.
    private var session: String? {
        if pixie != nil {
            return live
        }
        return shell.isDraft(chat) ? nil : chat
    }

    /// A pixie's composer suggests the files of its folder, not commands (B59).
    private func suggestions(_ draft: ComposerDraft) -> CompletionList? {
        guard focused || reveal else { return nil }
        if pixie != nil {
            guard let session else { return nil }
            return shell.completions.suggestions(
                text: draft.text, caret: draft.caret, session: session,
                repo: shell.sessions.session(session)?.repo ?? "", filesOnly: true)
        }
        guard let repo = shell.project else { return nil }
        return shell.completions.suggestions(
            text: draft.text, caret: draft.caret, session: session, repo: repo,
            mentions: shell.pixieMentions(forChat: chat), localCommands: true,
            commands: shell.supports(.slashCommands, chat: chat))
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
        let repeated =
            key == .escape && suggestions == nil && !working && escapes.press(at: Date())
        let action = ComposerKeyAction.of(
            key, suggesting: suggestions != nil, isEmpty: draft.text.isEmpty, working: working,
            repeated: repeated)
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
        case .rewind:
            if let live {
                shell.rewindLast(live)
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
        let input = shell.composerInput(for: chat, text: draft.text)
        let bashMode = if case .bash = input { true } else { false }
        return HStack(alignment: .bottom, spacing: 6) {
            VStack(alignment: .leading, spacing: 0) {
                if input != .message {
                    InputModeLabel(bash: bashMode)
                        .padding(.top, 6)
                }
                if !draft.attachments.isEmpty {
                    AttachmentChips(draft: draft)
                        .padding(.top, 6)
                }
                MessageField(draft: draft, focused: $focused, style: fieldStyle) {
                    key in
                    handle(key, draft: draft, suggestions: suggestions)
                }
                if let line = status ?? draft.hint {
                    HStack(spacing: 6) {
                        if status != nil {
                            Fireflies(height: 9)
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
        .background {
            // Over the chat background, the start field keeps its own ground.
            // A click anywhere in the field, not only on the text line, puts the cursor in it.
            shape.fill(Palette.soft)
                .background(start ? Palette.windowOpaque.opacity(0.85) : .clear, in: shape)
                .contentShape(shape)
                .pointerStyle(.horizontalText)
                .onTapGesture { focused = true }
        }
        .overlay(
            shape.strokeBorder(
                bashMode
                    ? StatusTone.waiting.color
                    : focused || dropTargeted ? accent.focus : Palette.divider, lineWidth: 1)
        )
        .onDrop(of: pixie == nil ? Self.dropTypes : [], isTargeted: $dropTargeted) { providers in
            loadFiles(providers)
            return true
        }
    }

    /// The start screen's names `/` only where the engine has slash commands (B91).
    private var fieldStyle: MessageFieldStyle {
        guard start else { return .pane }
        return shell.supports(.slashCommands, chat: chat) ? .start : .startWithoutCommands
    }

    /// Half the one-line field's height: an oval while it holds one line, a rounded field
    /// as it grows.
    static let fieldRadius = 19.0

    /// Files, and image data dragged from a browser or an app without a file (B59).
    static let dropTypes: [UTType] = [.fileURL, .image]

    private func loadFiles(_ providers: [NSItemProvider]) {
        for provider in providers {
            // Called on a background queue: nonisolated, then back to the main actor.
            if provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
                _ = provider.loadObject(ofClass: URL.self) { @Sendable url, _ in
                    guard let url else { return }
                    Task { @MainActor in shell.attach([url], to: chat) }
                }
            } else if let type = provider.registeredTypeIdentifiers.first(where: {
                UTType($0)?.conforms(to: .image) == true
            }) {
                _ = provider.loadDataRepresentation(forTypeIdentifier: type) { @Sendable data, _ in
                    guard let data else { return }
                    Task { @MainActor in shell.attach(data: data, type: type, to: chat) }
                }
            }
        }
    }
}

/// How a message field is set: a pane's, or the empty workspace's, which names what it
/// takes.
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
        size: TypeSize.reading, lineSpacing: 2, verticalPadding: 10, minHeight: 38,
        placeholder: "Ask, build, / for commands, @ for references...",
        placeholderColor: Palette.t3)
    static let startWithoutCommands = MessageFieldStyle(
        size: TypeSize.reading, lineSpacing: 2, verticalPadding: 10, minHeight: 38,
        placeholder: "Ask, build, @ for references...", placeholderColor: Palette.t3)
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

/// The new chat's engine is not signed in (B91): its hint, such as to run `codex login`,
/// in quiet grey above the field, with the code in mono; it goes once the engine says it
/// is signed in.
private struct SignInNote: View {
    let text: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 7) {
            Image(systemName: Icon.warning)
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(StatusTone.waiting.color)
            Text(styled)
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t2)
                .frame(maxWidth: .infinity, alignment: .leading)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 2)
        .accessibilityElement(children: .combine)
    }

    /// Code in mono at the text's size; its spaces stay in the text's font.
    private var styled: AttributedString {
        InlineCode.parts(text).reduce(into: AttributedString()) { result, part in
            var run = AttributedString(part.text)
            if part.isCode {
                run.font = .mono(TypeSize.meta)
            }
            result += run
        }
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
                    if let thumbnail = attachment.thumbnail.flatMap(NSImage.init(data:)) {
                        ImageChip(attachment: attachment, image: thumbnail) {
                            draft.remove(attachment.id)
                        }
                    } else {
                        chip(attachment)
                    }
                }
            }
        }
        .scrollIndicators(.never)
    }

    private func chip(_ attachment: PendingAttachment) -> some View {
        HStack(spacing: 5) {
            if attachment.uploaded == nil {
                Fireflies(height: 9)
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

/// An image's thumbnail with its remove button in the corner, like Claude's apps; a
/// spinner over it while it uploads.
private struct ImageChip: View {
    static let size = 44.0

    let attachment: PendingAttachment
    let image: NSImage
    let remove: () -> Void

    var body: some View {
        Image(nsImage: image)
            .resizable()
            .scaledToFill()
            .frame(width: Self.size, height: Self.size)
            .clipShape(.rounded(Radius.button))
            .overlay {
                RoundedRectangle.rounded(Radius.button).strokeBorder(Palette.divider)
            }
            .overlay {
                if attachment.uploaded == nil {
                    Fireflies()
                }
            }
            .overlay(alignment: .topTrailing) {
                Button(action: remove) {
                    Image(systemName: Icon.close).font(.system(size: 8, weight: .bold))
                }
                .buttonStyle(SmallSquareStyle())
                .background(Palette.soft, in: .rounded(Radius.button))
                .padding(2)
                .accessibilityLabel("Remove \(attachment.filename)")
            }
            .padding(.vertical, 2)
            .help(attachment.filename)
            .accessibilityElement(children: .contain)
            .accessibilityLabel(attachment.filename)
    }
}

/// Under the field: attach, the mic and where an open chat works (B71), or where the
/// empty workspace's new chat will (B90), on the left, then Model, Thinking and
/// Permission, and the context meter for open chats, on the right. A pixie's row has the
/// mic and the context meter.
private struct ControlRow: View {
    /// The draft's key.
    let chat: String
    /// The chat that runs, if any.
    let live: String?
    let pixie: Bool
    /// The empty workspace's composer.
    let start: Bool
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
                .buttonStyle(.nest(.plain, iconOnly: true))
                .help("Attach")
                .accessibilityLabel("Attach")
            }
            MicButton(listening: listening) { toggleDictation() }
            if start && shell.repo?.git != false {
                StartPlace(draft: draft, repo: shell.repo)
                    .padding(.leading, 4)
            }
            if !pixie && !isDraft,
                let place = session.flatMap({ ChatPlace.of($0, repo: shell.repo) })
            {
                PlaceLabel(place: place, showsName: fit.showsPlaceName)
                    .frame(maxWidth: 140, alignment: .leading)
                    .padding(.leading, 4)
            }
            Spacer(minLength: 4)
            if !pixie {
                ModelMenu(chat: chat, model: isDraft ? draft.model : session?.model)
                EffortMenu(
                    chat: chat, model: isDraft ? draft.model : session?.model,
                    effort: isDraft ? draft.effort : session?.effort, isOpen: !isDraft)
                PermissionMenu(
                    chat: chat, model: isDraft ? draft.model : session?.model,
                    mode: isDraft ? draft.permission : session?.permissionMode,
                    warnsOnBypass: start)
            }
            if !isDraft, let live, let context = session?.context,
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

/// Where an open chat works, beside the composer's mic (B71, in the header since B55): the
/// branch icon and the worktree's name, or the project folder's current branch, shortened
/// in the middle; the icon alone in a narrower pane. The tooltip names the folder.
private struct PlaceLabel: View {
    let place: ChatPlace
    let showsName: Bool

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: Icon.branch)
                .font(.system(size: 10, weight: .medium))
            if showsName {
                Text(place.name)
                    .font(.mono(TypeSize.meta))
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
        }
        .foregroundStyle(Palette.t3)
        .fixedSize(horizontal: !showsName, vertical: false)
        .help(place.help)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(place.help)
    }
}

/// Attach and dictation, for the control row.
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

/// Where a new chat works, over its field (B55): a capsule selector with the branch icon,
/// "Work on <branch>" (the project folder's current branch) or "New worktree", which
/// always starts from that branch; a new worktree also takes an optional branch name.
struct WorkingCopyRow: View {
    @Bindable var draft: ComposerDraft
    let repo: Repo?
    @Environment(Shell.self) private var shell

    var body: some View {
        // No mode chosen works in place, the default (D038).
        let worktree = draft.mode == .worktree
        let inPlace = NewChatPlace.inPlaceTitle(repo)
        HStack(spacing: 8) {
            PlaceSelector(title: worktree ? NewChatPlace.worktreeTitle : inPlace) {
                PlaceItems(draft: draft, repo: repo)
            }
            if worktree {
                BranchNameField(text: $draft.branchName)
            }
            Spacer(minLength: 0)
        }
        .reloadsBranch(of: repo, shell: shell)
    }
}

/// The empty workspace's place, in the row under its field (B90): "Work on <branch>" or
/// "New worktree" as quiet text with its menu, and a new worktree's optional branch name.
private struct StartPlace: View {
    @Bindable var draft: ComposerDraft
    let repo: Repo?
    @Environment(Shell.self) private var shell

    var body: some View {
        let worktree = draft.mode == .worktree
        HStack(spacing: 6) {
            QuietMenu(
                title: worktree ? NewChatPlace.worktreeTitle : NewChatPlace.inPlaceTitle(repo),
                help: "Where the chat works", chevron: true
            ) {
                PlaceItems(draft: draft, repo: repo)
            }
            if worktree {
                BranchNameField(text: $draft.branchName)
            }
        }
        .reloadsBranch(of: repo, shell: shell)
    }
}

/// Work in the project folder (no mode chosen, the default, D038) or in a new worktree.
private struct PlaceItems: View {
    let draft: ComposerDraft
    let repo: Repo?

    var body: some View {
        let worktree = draft.mode == .worktree
        OptionItem(
            title: NewChatPlace.inPlaceTitle(repo), detail: NewChatPlace.inPlaceDetail(repo),
            checked: !worktree
        ) { draft.mode = .inPlace }
        OptionItem(
            title: NewChatPlace.worktreeTitle, detail: NewChatPlace.worktreeDetail,
            checked: worktree
        ) { draft.mode = .worktree }
    }
}

extension View {
    /// The folder's branch may have changed in a terminal since the list was read.
    fileprivate func reloadsBranch(of repo: Repo?, shell: Shell) -> some View {
        task(id: repo?.name) {
            if repo != nil {
                shell.app.reloadRepos()
            }
        }
    }
}

/// The new chat's place selector: a capsule with a 4 percent fill (8 while hovered), a
/// hairline border, the branch icon, the choice and a small chevron.
private struct PlaceSelector<Items: View>: View {
    let title: String
    @ViewBuilder let items: () -> Items
    @State private var hovering = false

    var body: some View {
        Menu {
            items()
        } label: {
            HStack(spacing: 5) {
                Image(systemName: Icon.branch).font(.system(size: 10, weight: .medium))
                Text(title)
                    .font(.ui(TypeSize.button))
                    .lineLimit(1)
                    .truncationMode(.middle)
                Image(systemName: Icon.chevron)
                    .font(.system(size: 8, weight: .semibold))
                    .foregroundStyle(Ink.content(0.5))
            }
            .foregroundStyle(Ink.content(hovering ? 1 : 0.75))
            .padding(.horizontal, 10)
            .frame(height: 24)
            .background(Ink.content(hovering ? 0.08 : 0.04), in: Capsule())
            .overlay(Capsule().strokeBorder(Ink.content(0.1), lineWidth: 1))
            .contentShape(Capsule())
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .menuIndicator(.hidden)
        .fixedSize()
        .onHover { hovering = $0 }
        .help("Where the chat works")
        .accessibilityLabel("Where the chat works: \(title)")
    }
}

/// A new worktree's optional branch name: a quiet mono capsule the size of the selector.
private struct BranchNameField: View {
    @Binding var text: String
    @FocusState private var focused: Bool

    var body: some View {
        TextField("", text: $text)
            .textFieldStyle(.plain)
            .font(.mono(TypeSize.meta))
            // AppKit draws a placeholder at full strength here, so this one is drawn.
            .background(alignment: .leading) {
                if text.isEmpty {
                    Text("Branch name (optional)")
                        .font(.mono(TypeSize.meta))
                        .foregroundStyle(Ink.content(0.4))
                        .lineLimit(1)
                        .allowsHitTesting(false)
                }
            }
            .focused($focused)
            .padding(.horizontal, 10)
            .frame(minWidth: 90, maxWidth: 200)
            .frame(height: 24)
            .background(Ink.content(focused ? 0.08 : 0.04), in: Capsule())
            .help("A name for the worktree's branch; left empty, Nest names it")
            .accessibilityLabel("Branch name, optional")
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
            .buttonStyle(.nest(.plain, iconOnly: true))
            .help("Dictate")
            .accessibilityLabel("Dictate")
        }
    }
}

/// The send button for the composer's state: Send, or Interrupt (stop) while Claude works
/// and the field is empty. Text sent while Claude works goes into the running turn.
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
/// a quiet fill while empty; a round stop while Claude works.
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
            case .send:
                let ready = hasText || sending
                Group {
                    if sending {
                        Fireflies(height: 10, color: accent.onAccent)
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
        case .interrupt: "Interrupt"
        }
    }

    private var help: String {
        switch mode {
        case .send: "Send"
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

/// "! bash mode" or "# memory" over the field while the text starts with `!` or `#`, as in
/// Claude Code (B59).
private struct InputModeLabel: View {
    let bash: Bool

    var body: some View {
        Text(bash ? "! bash mode: runs in the chat's folder" : "# memory: saved to CLAUDE.md")
            .font(.ui(TypeSize.meta, .medium))
            .foregroundStyle(bash ? StatusTone.waiting.color : Palette.t3)
            .padding(.horizontal, 5)
    }
}
