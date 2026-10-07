import AppKit
import HarnessKit
import Observation
import SwiftUI
import UniformTypeIdentifiers

/// A drag in flight inside the window: a chat from the sidebar or a pane by its header.
enum DragItem: Equatable {
    case chat(String)
    case pane(String)

    var chat: String {
        switch self {
        case .chat(let id), .pane(let id): id
        }
    }

    var kind: DropZone.Kind {
        if case .pane = self { .pane } else { .chat }
    }
}

/// Where the current drag would land; `pane` is nil for the empty workspace.
struct DropHighlight: Equatable {
    var pane: String?
    var zone: DropZone
}

struct Toast: Identifiable, Equatable {
    enum Kind {
        case done, failed, info
    }

    let id = UUID()
    let text: String
    let kind: Kind
}

/// The sheet or popover shown over the window; one at a time.
enum Overlay: Equatable {
    case palette
    case usage
    case settings
    case connectors
    /// The diff of a review, by approval id.
    case diff(String)
    /// The approve sheet of a review, by approval id.
    case publish(String)
}

/// The window's model: the daemon's stores plus the transient state of the views, and
/// the actions they call.
@MainActor @Observable
final class Shell {
    static let draftPrefix = "draft-"

    let model: AppModel
    let userName: String
    var overlay: Overlay?
    /// The palette while it is open.
    var palette = CommandPalette(items: [])

    var renaming: String?
    var renameText = ""
    /// The chat whose delete confirmation is showing.
    var deleting: String?
    /// Projects whose Archived group is unfolded.
    var archivedOpen: Set<String> = []
    /// Expanded tool calls and thinking blocks, by transcript item id.
    var expandedItems: Set<String> = []
    var toast: Toast?
    var dragging: DragItem?
    var dropHighlight: DropHighlight?
    let dictation = Dictation()
    /// The live terminals and web views of the tool panes.
    let tools = ToolSessions()
    /// Each chat's last message sent from here, for Up arrow in an empty composer.
    let sentMessages = SentMessages()

    /// The workspace's size, for the layout engine's click-to-open rule.
    @ObservationIgnored var workspaceSize = CGSize(width: 900, height: 700)
    /// Each open pane's size, to place drops within it.
    @ObservationIgnored var paneSizes: [String: CGSize] = [:]
    @ObservationIgnored private var drafts: [String: ComposerDraft] = [:]
    @ObservationIgnored private var draftCount = 0
    @ObservationIgnored private var toastTask: Task<Void, Never>?

    init(model: AppModel, userName: String = NSFullUserName()) {
        self.model = model
        self.userName = userName.isEmpty ? NSUserName() : userName
    }

    var app: AppStore { model.app }
    var sessions: SessionsStore { model.sessions }
    var approvals: ApprovalsStore { model.approvals }
    var activity: ActivityStore { model.activity }
    var settings: SettingsStore { model.settings }
    var claudeChats: ClaudeChatsStore { model.claudeChats }
    var completions: CompletionStore { model.completions }
    var agents: AgentsStore { model.agents }

    /// The Claude account's name, else the Mac user's.
    var accountName: String { agents.accountName(fallback: userName) }

    var project: String? { app.currentProject }
    var projectState: ProjectState { project.map(app.state(of:)) ?? ProjectState() }
    var repo: Repo? { project.flatMap(app.repo) }

    func update(_ change: (inout ProjectState) -> Void) {
        withAnimation(.smooth(duration: 0.22)) {
            app.update(nil, change)
        }
        syncTools()
    }

    #if DEBUG
        /// Snapshots change project states directly, then let go of closed panes.
        func syncToolsForSnapshots() {
            syncTools()
        }
    #endif

    /// Ends the shells and web views of tool panes no project shows any more.
    private func syncTools() {
        tools.keep(Set(app.projects.values.flatMap { $0.tools.keys }))
    }

    // MARK: Session presentation

    func tone(of session: Session) -> StatusTone {
        sessions.tone(of: session)
    }

    /// Idle chats show a hollow dot.
    func isHollow(_ session: Session) -> Bool {
        session.state == .idle && tone(of: session) == .done
    }

    func statusLabel(of session: Session) -> String {
        sessions.statusLabel(of: session)
    }

    /// The live line under a running transcript: the newest busy agent's activity.
    func liveActivity(of session: String) -> String {
        let agents = activity.agents(session: session).filter { $0.status == .running }
        guard let agent = agents.last(where: { !$0.isMain }) ?? agents.first,
            let doing = agent.activity
        else { return "Thinking" }
        return agent.isMain ? doing : "\(agent.name): \(doing)"
    }

    // MARK: Claude Code chats

    /// Claude Code chats being continued in harness, by chat id.
    var adopting: Set<String> = []

    /// The sidebar's groups: the project's sessions with its Claude Code chats in Idle.
    func sidebarGroups(in project: String) -> [SidebarGroup] {
        SidebarGroup.merge(sessions.groups(in: project), chats: claudeChats.chats(in: project))
    }

    /// The Claude Code chat a pane shows, if it is one.
    func claudeChat(inPane pane: String) -> ClaudeChat? {
        ClaudeChat.chatID(ofPane: pane).flatMap(claudeChats.chat)
    }

    func isClaudeChatPane(_ pane: String) -> Bool {
        ClaudeChat.chatID(ofPane: pane) != nil
    }

    /// Adopts the pane's Claude Code chat; the new session takes over the pane and the
    /// composer appears.
    func continueInHarness(_ pane: String) {
        guard let id = ClaudeChat.chatID(ofPane: pane), !adopting.contains(id) else { return }
        adopting.insert(id)
        Task {
            defer { adopting.remove(id) }
            do {
                let session = try await claudeChats.adopt(id)
                sessions.insert(session)
                withAnimation(.smooth(duration: 0.22)) {
                    app.update(session.repo) { $0.replaceChat(pane, with: session.id) }
                }
                model.transcripts.close(pane)
            } catch {
                show(error, doing: "Could not continue in harness")
            }
        }
    }

    func setShowAutomatedChats(_ show: Bool) {
        run("Could not list Claude Code chats") {
            try await self.claudeChats.setShowAutomated(show)
        }
    }

    // MARK: Workspace

    func isDraft(_ id: String) -> Bool { id.hasPrefix(Self.draftPrefix) }

    func openChat(_ id: String) {
        let size = workspaceSize
        update { $0.openChat(id, in: size) }
    }

    /// Opens an empty composer pane; the chat is created with its first message.
    func newChat() {
        draftCount += 1
        let id = "\(Self.draftPrefix)\(draftCount)"
        let draft = draft(for: id)
        let defaults = agents.current
        draft.model = defaults.model
        draft.effort = defaults.effort
        draft.permission = defaults.permissionMode
        draft.mode = defaults.mode
        openChat(id)
    }

    /// Cmd-W: closes the open sheet, else the focused pane, else the window.
    func closeFocused() {
        if overlay != nil {
            close()
        } else if let focused = projectState.layout.focused {
            closePane(focused)
        } else {
            NSApp.keyWindow?.performClose(nil)
        }
    }

    /// Cmd-Return: sends the focused pane's message.
    func sendFocused() {
        if let focused = projectState.layout.focused {
            send(focused)
        }
    }

    func closePane(_ id: String) {
        update { $0.closePane(id) }
        if isDraft(id) {
            drafts[id] = nil
        }
    }

    func toggleMaximize(_ id: String) {
        update { $0.layout.toggleMaximize(id) }
    }

    func focusPane(_ id: String) {
        guard projectState.layout.focused != id || projectState.selectedChat != id else { return }
        app.update { $0.focusPane(id) }
    }

    func perform(_ item: DragItem, onto pane: String?, zone: DropZone) {
        switch zone {
        case .swap:
            if let pane {
                update { $0.layout.swap(item.chat, pane) }
            }
        case .open:
            update { $0.dropChat(item.chat, onto: nil, side: .right) }
        case .replace:
            update { $0.dropChat(item.chat, onto: pane, side: .right) }
        case .split(let side):
            update { $0.dropChat(item.chat, onto: pane, side: side) }
        case .none:
            break
        }
        dragging = nil
        dropHighlight = nil
    }

    // MARK: Composer

    func draft(for id: String) -> ComposerDraft {
        if let draft = drafts[id] {
            return draft
        }
        let draft = ComposerDraft()
        drafts[id] = draft
        return draft
    }

    func send(_ chat: String) {
        let draft = draft(for: chat)
        let text = draft.text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !draft.sending, !draft.isUploading else { return }
        let attachments = draft.uploadedIDs
        draft.sending = true
        dictation.cancel()
        withAnimation { draft.blocked = nil }
        Task {
            defer { draft.sending = false }
            do {
                if isDraft(chat) {
                    let session = try await create(
                        from: chat, draft: draft, prompt: text, attachments: attachments)
                    sentMessages.record(text, chat: session)
                } else {
                    let queued = try await sessions.send(
                        chat, text: text, attachmentIDs: attachments)
                    if let queued {
                        activity.enqueue(queued, session: chat)
                    }
                    sentMessages.record(text, chat: chat)
                }
                draft.clear()
            } catch APIError.openInClaudeCode(let message) {
                withAnimation { draft.blocked = message }
            } catch {
                show(error, doing: "Could not send")
            }
        }
    }

    /// The new session's id.
    private func create(
        from draftID: String, draft: ComposerDraft, prompt: String, attachments: [String]
    ) async throws -> String {
        guard let repo = project else { return draftID }
        let request = CreateSessionRequest(
            repo: repo, prompt: prompt, mode: draft.mode, model: draft.model,
            effort: draft.effort, permissionMode: draft.permission, attachmentIDs: attachments)
        let session = try await sessions.create(request)
        app.update(repo) { $0.replaceChat(draftID, with: session.id) }
        drafts[draftID] = nil
        return session.id
    }

    func interrupt(_ chat: String) {
        run("Could not interrupt") { try await self.sessions.interrupt(chat) }
    }

    /// Stops a stuck chat's turn and asks it to try a different approach.
    func nudge(_ session: Session) {
        run("Could not send the nudge") {
            if let queued = try await self.sessions.nudge(session.id) {
                self.activity.enqueue(queued, session: session.id)
            }
            self.show("Sent a nudge to \(session.title)", kind: .done)
        }
    }

    func setStuckThreshold(_ threshold: StuckThreshold, to value: Int) {
        run("Could not change the stuck settings") {
            try await self.model.stuck.set(threshold, to: value)
        }
    }

    /// Up arrow in an empty composer: the chat's last message, caret at its end.
    func recallLastMessage(_ chat: String) {
        let items = model.transcripts.existing(chat)?.items ?? []
        guard let text = sentMessages.last(chat: chat, transcript: items) else { return }
        draft(for: chat).replaceText(text, caret: text.count)
    }

    /// Puts a picked suggestion into the composer.
    func complete(_ completion: Completion, in chat: String) {
        draft(for: chat).replaceText(completion.text, caret: completion.caret)
    }

    /// Sends /compact, which Claude Code runs as a command; queued while a turn runs.
    func compact(_ chat: String) {
        run("Could not compact") {
            if let queued = try await self.sessions.compact(chat) {
                self.activity.enqueue(queued, session: chat)
            }
            self.show("Compacting the context", kind: .info)
        }
    }

    func cancelQueued(_ message: QueuedMessage, in chat: String) {
        run("Could not cancel the queued message") {
            try await self.activity.cancelQueued(message.id, session: chat)
        }
    }

    /// Runs a command from a chat's transcript in the project's terminal for the chat's
    /// folder, opening one when there is none. It runs without asking: the user clicked
    /// Run in terminal.
    func runInTerminal(command: String, from chat: String?) {
        guard let project, let folder = chat.flatMap(folder(ofPane:)) ?? repo?.path else {
            return
        }
        let size = workspaceSize
        var target: ToolPane?
        withAnimation(.smooth(duration: 0.22)) {
            app.update(project) { target = $0.terminal(for: folder, in: size).pane }
        }
        syncTools()
        if let target {
            tools.terminal(for: target).run(command)
        }
    }

    // MARK: Terminal and browser panes

    /// The folder a pane's chat works in: its worktree, its folder in place, or a Claude
    /// Code chat's folder. Nil for a new chat and tool panes.
    func folder(ofPane pane: String) -> String? {
        if let chat = claudeChat(inPane: pane) {
            return chat.cwd
        }
        guard let session = sessions.session(pane) else { return nil }
        return session.folder ?? app.repo(session.repo)?.path
    }

    /// "Terminal here": the folder's terminal pane, focused, or a new one.
    func openTerminal(in folder: String) {
        let size = workspaceSize
        update { $0.terminal(for: folder, in: size) }
    }

    /// A new terminal pane in the project folder.
    func newTerminal() {
        guard let path = repo?.path else { return }
        let size = workspaceSize
        update { $0.openTool(.terminal(in: path), in: size) }
    }

    func newBrowser(url: String? = nil) {
        guard project != nil else { return }
        let size = workspaceSize
        update { $0.openTool(.browser(url: url), in: size) }
    }

    /// The tool pane with this id in the current project.
    func toolPane(_ id: String) -> ToolPane? {
        projectState.tools[id]
    }

    /// Remembers a browser pane's page, so it reopens there.
    func browserNavigated(_ pane: String, to url: String) {
        guard let project = app.projects.first(where: { $0.value.tools[pane] != nil })?.key,
            app.state(of: project).tools[pane]?.url != url
        else { return }
        app.update(project) { $0.setURL(url, of: pane) }
    }

    func attach(_ urls: [URL], to chat: String) {
        let draft = draft(for: chat)
        for url in urls {
            let pending = PendingAttachment(filename: url.lastPathComponent)
            draft.attachments.append(pending)
            Task {
                do {
                    let data = try Data(contentsOf: url)
                    let type = UTType(filenameExtension: url.pathExtension)?.preferredMIMEType
                    let uploaded = try await model.api.uploadAttachment(
                        filename: url.lastPathComponent,
                        mediaType: type ?? "application/octet-stream", data: data)
                    draft.finish(pending.id, with: uploaded)
                } catch {
                    draft.remove(pending.id)
                    show(error, doing: "Could not attach \(url.lastPathComponent)")
                }
            }
        }
    }

    /// Keeps the chat's effort only as far as the new model supports it.
    func setModel(_ info: ModelInfo, for chat: String) {
        if isDraft(chat) {
            let draft = draft(for: chat)
            draft.model = info.value
            draft.effort = agents.effort(draft.effort, afterSwitchingTo: info.value)
        } else {
            let current = sessions.session(chat)?.effort
            let effort = agents.effort(current, afterSwitchingTo: info.value)
            run("Could not change the model") {
                try await self.sessions.setModel(
                    chat, info.value, effort: effort == current ? nil : effort)
            }
        }
    }

    /// A draft keeps it for its first message; an open chat applies it from the next one.
    func setEffort(_ effort: Effort, for chat: String) {
        if isDraft(chat) {
            draft(for: chat).effort = effort
        } else {
            run("Could not change thinking") { try await self.sessions.setEffort(chat, effort) }
        }
    }

    func setPermission(_ mode: PermissionMode, for chat: String) {
        if isDraft(chat) {
            draft(for: chat).permission = mode
        } else {
            run("Could not change the permission mode") {
                try await self.sessions.setPermissionMode(chat, mode)
            }
        }
    }

    // MARK: Chat actions

    func togglePin(_ id: String) {
        guard let session = sessions.session(id) else { return }
        run("Could not pin") { try await self.sessions.setPinned(id, !session.pinned) }
    }

    func beginRename(_ id: String) {
        guard let session = sessions.session(id) else { return }
        update { $0.leftCollapsed = false }
        renameText = session.title
        renaming = id
    }

    func commitRename(save: Bool) {
        guard let id = renaming else { return }
        renaming = nil
        let title = renameText
        if save {
            run("Could not rename") { try await self.sessions.rename(id, to: title) }
        }
    }

    func setArchived(_ id: String, _ archived: Bool) {
        if archived {
            update { $0.closePane(id) }
        }
        run(archived ? "Could not archive" : "Could not unarchive") {
            if archived {
                try await self.sessions.archive(id)
            } else {
                try await self.sessions.unarchive(id)
            }
        }
    }

    func delete(_ id: String) {
        deleting = nil
        run("Could not delete") {
            try await self.sessions.delete(id)
            self.app.forgetChat(id)
        }
    }

    func continueInClaudeCode(_ id: String) {
        run("Could not open Claude Code") {
            let launch = try await self.sessions.openInClaudeCode(id)
            self.show(
                launch.warning ?? "Opened in Terminal", kind: launch.warning == nil ? .done : .info)
        }
    }

    // MARK: Project actions

    func openProject(in target: RepoApp) {
        guard let name = project else { return }
        run("Could not open the project") { try await self.app.openProject(name, in: target) }
    }

    func copyProjectPath() {
        guard let path = repo?.path else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(path, forType: .string)
        show("Copied \(path)", kind: .done)
    }

    /// Puts a message or output on the clipboard as plain text.
    func copyText(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        show("Copied", kind: .done)
    }

    /// Opens a folder as a project, registering it with the daemon when it is new.
    func addProject(at url: URL) {
        let path = url.standardizedFileURL.path
        if let known = app.repos.first(where: { $0.path == path }) {
            app.openProject(known.name)
            return
        }
        run("Could not add the project") { try await self.app.addProject(path: path) }
    }

    // MARK: Sheets

    func show(_ overlay: Overlay) {
        if overlay == .palette {
            palette = CommandPalette.catalog(app: app, sessions: sessions)
        }
        withAnimation(.smooth(duration: 0.2)) { self.overlay = overlay }
    }

    /// Shows the overlay, or closes it when it is already showing.
    func toggle(_ overlay: Overlay) {
        if self.overlay == overlay {
            close()
        } else {
            show(overlay)
        }
    }

    func close() {
        withAnimation(.smooth(duration: 0.18)) { overlay = nil }
    }

    /// Filters the palette and, after a pause in typing, searches the chats' messages.
    func searchPalette(_ text: String) {
        palette.search(text)
        Task {
            if let results = await model.search.results(for: text) {
                palette.show(results, for: text)
            }
        }
    }

    /// Opens a search hit's chat, scrolled to the hit's message, which glows briefly.
    func openMessage(project: String, pane: String, event: Int?) {
        if let event {
            model.transcripts.transcript(for: pane).requestFocus(event: event)
        }
        reveal(chat: pane, in: project)
    }

    /// Runs the palette's chosen entry.
    func run(_ action: PaletteAction) {
        close()
        switch action {
        case .openChat(let project, let chat):
            app.selectProject(project)
            openChat(chat)
        case .newChat:
            newChat()
        case .newTerminal:
            newTerminal()
        case .newBrowser:
            newBrowser()
        case .showView(let view):
            update { $0.view = view }
        case .toggleSidebar:
            update { $0.leftCollapsed.toggle() }
        case .toggleActivityPanel:
            update { $0.rightCollapsed.toggle() }
        case .showUsage:
            show(.usage)
        case .openInVSCode:
            openProject(in: .vscode)
        case .goToProject(let project):
            app.selectProject(project)
        case .openMessage(let project, let pane, let event):
            openMessage(project: project, pane: pane, event: event)
        }
    }

    /// A notification was clicked: show its chat.
    func reveal(chat: String, in project: String) {
        close()
        let size = workspaceSize
        withAnimation(.smooth(duration: 0.22)) {
            app.reveal(chat: chat, in: project, size: size)
        }
        syncTools()
    }

    // MARK: Approvals

    func approval(_ id: String) -> Approval? {
        approvals.pending.first { $0.id == id }
    }

    func allow(_ approval: Approval, always: Bool = false) {
        run("Could not approve") {
            try await self.approvals.allow(approval, always: always)
            self.show(always ? "Always allowed in this chat" : "Approved", kind: .done)
        }
    }

    func deny(_ approval: Approval) {
        run("Could not reject") {
            try await self.approvals.deny(approval)
            self.show("Rejected. Claude continues without it", kind: .failed)
        }
    }

    func answer(_ approval: Approval) {
        run("Could not send the answer") {
            try await self.approvals.submitAnswers(approval)
            self.show("Answer sent to \(approval.title)", kind: .done)
        }
    }

    func dismiss(_ approval: Approval) {
        run("Could not dismiss") { try await self.approvals.dismiss(approval) }
    }

    func approvePlan(_ approval: Approval) {
        run("Could not approve the plan") {
            try await self.approvals.approvePlan(approval)
            self.show("Plan approved. Claude continues with Accept edits", kind: .done)
        }
    }

    func keepPlanning(_ approval: Approval) {
        run("Could not send the plan back") {
            try await self.approvals.keepPlanning(approval)
            self.show("Claude keeps planning", kind: .info)
        }
    }

    /// Discards the work: the daemon closes the chat and removes its worktree and branch.
    func reject(_ approval: Approval) {
        if overlay == .diff(approval.id) || overlay == .publish(approval.id) {
            close()
        }
        run("Could not reject") {
            try await self.approvals.reject(approval)
            self.show("Rejected \(approval.title). Nothing was merged", kind: .failed)
        }
    }

    func sendFeedback(_ approval: Approval, text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        run("Could not send feedback") {
            try await self.approvals.feedback(approval, text: trimmed)
            self.show("Feedback sent to \(approval.title)", kind: .done)
        }
    }

    func publish(_ approval: Approval, _ form: PublishForm) {
        Task {
            guard let session = try? await approvals.publish(approval, form) else { return }
            if overlay == .publish(approval.id) {
                close()
            }
            let done =
                session.prURL != nil
                ? "Opened a pull request for \(approval.title)"
                : form.push
                    ? "Committed and pushed \(approval.title)" : "Committed \(approval.title)"
            show(done, kind: .done)
        }
    }

    // MARK: Pull requests

    /// Merges a green pull request; the daemon closes the chat and removes its worktree.
    func merge(_ approval: Approval, method: MergeMethod = .squash) {
        run("Could not merge") {
            let session = try await self.approvals.merge(approval, method: method)
            self.sessions.insert(session)
            self.show("Merged \(approval.title)", kind: .done)
        }
    }

    func refreshPR(_ session: String) {
        run("Could not read the pull request") { try await self.sessions.refreshPR(session) }
    }

    /// Sends the failing checks into the chat for the agent to fix.
    func sendChecksFailure(_ session: Session) {
        run("Could not send") {
            if let queued = try await self.sessions.sendChecksFailure(session.id) {
                self.activity.enqueue(queued, session: session.id)
            }
            self.show("Sent the failing checks to \(session.title)", kind: .done)
        }
    }

    func openOnGitHub(_ url: String) {
        if let link = URL(string: url) {
            NSWorkspace.shared.open(link)
        }
    }

    // MARK: Feedback

    func show(_ text: String, kind: Toast.Kind = .info) {
        let toast = Toast(text: text, kind: kind)
        withAnimation(.smooth(duration: 0.25)) { self.toast = toast }
        toastTask?.cancel()
        toastTask = Task {
            try? await Task.sleep(for: .seconds(3))
            guard !Task.isCancelled, self.toast == toast else { return }
            withAnimation(.smooth(duration: 0.25)) { self.toast = nil }
        }
    }

    func show(_ error: any Error, doing action: String) {
        show("\(action): \(Self.describe(error))", kind: .failed)
    }

    static func describe(_ error: any Error) -> String {
        guard let error = error as? APIError else { return error.localizedDescription }
        if case .decoding = error {
            return "the daemon's answer could not be read"
        }
        return error.message
    }

    private func run(_ failure: String, _ action: @escaping @MainActor () async throws -> Void) {
        Task {
            do {
                try await action()
            } catch {
                show(error, doing: failure)
            }
        }
    }
}

struct PendingAttachment: Identifiable, Equatable {
    let id = UUID()
    let filename: String
    var uploaded: Attachment?
}

/// What the user is writing in one pane.
@MainActor @Observable
final class ComposerDraft {
    var text = ""
    /// Dictation still being recognized, shown lighter after the text.
    var volatile = ""
    /// Why the last message was refused, such as the chat being open in Claude Code.
    var blocked: String?
    var attachments: [PendingAttachment] = []
    var sending = false
    /// A short note under the field, such as dictation being unavailable.
    var hint: String?
    /// New chats only: the choices sent with the first message.
    var model: String?
    var effort: Effort?
    var permission = PermissionMode.default
    var mode: SessionMode?
    /// The caret and selection in the field.
    var selection: TextSelection?
    /// The highlighted suggestion, and whether Esc closed the list.
    var completion = CompletionSelection()

    /// The caret as a character offset; the end of the text when unknown.
    var caret: Int {
        guard let selection, case .selection(let range) = selection.indices else {
            return text.count
        }
        let offset = min(max(range.upperBound.utf16Offset(in: text), 0), text.utf16.count)
        return text[..<String.Index(utf16Offset: offset, in: text)].count
    }

    /// Replaces the text and puts the caret at a character offset.
    func replaceText(_ newText: String, caret: Int) {
        text = newText
        let index = newText.index(
            newText.startIndex, offsetBy: min(max(caret, 0), newText.count))
        selection = TextSelection(insertionPoint: index)
    }

    var isUploading: Bool { attachments.contains { $0.uploaded == nil } }
    var uploadedIDs: [String] { attachments.compactMap(\.uploaded?.id) }

    func finish(_ id: UUID, with attachment: Attachment) {
        guard let index = attachments.firstIndex(where: { $0.id == id }) else { return }
        attachments[index].uploaded = attachment
    }

    func remove(_ id: UUID) {
        attachments.removeAll { $0.id == id }
    }

    func clear() {
        text = ""
        selection = nil
        completion = CompletionSelection()
        volatile = ""
        attachments = []
        hint = nil
        blocked = nil
    }
}
