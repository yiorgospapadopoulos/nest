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

extension UTType {
    /// A chat dragged from the sidebar. Not text, so the composer or another app cannot
    /// take the drop and insert the chat's id.
    static let harnessChat = UTType(exportedAs: "local.harness.app.chat", conformingTo: .data)
}

extension NSItemProvider {
    /// A sidebar chat's drag; only this app's own panes read it (`shell.dragging` says
    /// which chat).
    static func chat(_ id: String) -> NSItemProvider {
        let provider = NSItemProvider()
        provider.registerDataRepresentation(for: .harnessChat, visibility: .ownProcess) {
            load in
            load(Data(id.utf8), nil)
            return nil
        }
        return provider
    }
}

/// Where the current drag would land; `pane` is nil for the empty workspace.
struct DropHighlight: Equatable {
    var pane: String?
    var zone: DropZone
}

/// A pane dragged by its header. It is followed inside the window rather than handed to
/// a system drag, so every release (or Escape) ends it.
struct PaneDrag: Equatable {
    let pane: String
    let title: String
    let tone: StatusTone
    /// The pointer, in the workspace's coordinates.
    var location: CGPoint
}

/// An inline field being edited, such as a pixie detail's Add field: a click outside its
/// frame ends the edit, keeping the text, and Escape cancels it.
struct InlineEdit {
    let id: UUID
    /// In the window's content coordinates, top-left origin.
    var frame: CGRect
    /// Ends the edit; false cancels it.
    let end: (_ keep: Bool) -> Void
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
    /// A project's settings, by repo name.
    case project(String)
    /// Restoring files to before a message (`Shell.rewinding`).
    case rewind
}

/// What the Pixies tab's right-hand panel shows for the focused pixie: the details, or a
/// page opened from them.
enum PixiePanel: Equatable {
    case details
    case soul
    case memory
    /// A note of the memory page, by name.
    case note(String)
}

/// The window's model: the daemon's stores plus the transient state of the views, and
/// the actions they call.
@MainActor @Observable
final class Shell {
    static let draftPrefix = "draft-"

    let model: AppModel
    let userName: String
    var overlay: Overlay?
    /// The restore the rewind sheet shows.
    var rewinding: RewindFlow?
    /// The palette while it is open.
    var palette = CommandPalette(items: [])

    var renaming: String?
    var renameText = ""
    /// The chat whose delete confirmation is showing.
    var deleting: String?
    /// Projects whose Archived group is unfolded.
    var archivedOpen: Set<String> = []
    /// The Connectors sheet's unfolded groups; all are folded at first.
    var connectorGroupsOpen: Set<ConnectorSectionKind> = []
    /// Expanded tool calls and thinking blocks, by transcript item id.
    var expandedItems: Set<String> = []
    var toast: Toast?
    var dragging: DragItem?
    var dropHighlight: DropHighlight?
    var paneDrag: PaneDrag?
    let dictation = Dictation()
    /// The live terminals and web views of the tool panes.
    let tools = ToolSessions()
    /// Each chat's last message sent from here, for Up arrow in an empty composer.
    let sentMessages = SentMessages()

    /// The workspace's size, for the layout engine's click-to-open rule.
    @ObservationIgnored var workspaceSize = CGSize(width: 900, height: 700)
    /// Where the workspace on screen places its panes, in the window's content coordinates
    /// (top-left origin), so a click anywhere in a pane focuses it.
    @ObservationIgnored var workspaceFrame: CGRect?
    /// The inline field being edited, if any.
    @ObservationIgnored var inlineEdit: InlineEdit?
    /// Each open pane's size, to place drops within it.
    @ObservationIgnored var paneSizes: [String: CGSize] = [:]
    @ObservationIgnored private let drafts = DraftBook { ComposerDraft() }
    @ObservationIgnored private var draftCount = 0
    @ObservationIgnored private var toastTask: Task<Void, Never>?
    /// Escape ended the pane drag in progress; its later moves are ignored until release.
    @ObservationIgnored private var paneDragCancelled = false
    @ObservationIgnored private var dragMonitor: Any?

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
    var pixies: PixiesStore { model.pixies }

    /// The Claude account's name, else the Mac user's.
    var accountName: String { agents.accountName(fallback: userName) }

    /// The Pixies tab is showing in place of a project.
    var pixiesOpen = false
    /// The details panel on the right of the Pixies tab, for the focused pixie pane.
    var pixieDetailsOpen = false
    /// The list shows hidden pixies too, so they can be opened and shown again.
    var showsHiddenPixies = false
    var pixiePanel = PixiePanel.details

    var project: String? { app.currentProject }
    var projectState: ProjectState { project.map(app.state(of:)) ?? ProjectState() }
    var repo: Repo? { project.flatMap(app.repo) }

    /// The workspace on screen: the Pixies tab's (its panes are pixies) or the current
    /// project's. The pane views and their actions work on this one.
    var workspaceState: ProjectState { pixiesOpen ? app.pixieState : projectState }

    func update(_ change: (inout ProjectState) -> Void) {
        withAnimation(.smooth(duration: 0.22)) {
            app.update(nil, change)
        }
        syncTools()
    }

    /// Changes the workspace on screen, animated.
    func updateWorkspace(_ change: (inout ProjectState) -> Void) {
        withAnimation(.smooth(duration: 0.22)) {
            changeWorkspace(change)
        }
        syncTools()
    }

    /// Changes the workspace on screen. Focusing another pixie brings back its details.
    private func changeWorkspace(_ change: (inout ProjectState) -> Void) {
        guard pixiesOpen else {
            app.update(nil, change)
            return
        }
        let focused = app.pixieState.layout.focused
        app.updatePixies(change)
        if app.pixieState.layout.focused != focused {
            pixiePanel = .details
        }
    }

    /// Ends the shells and web views of tool panes no project shows any more, such as a
    /// removed project's, and releases the transcripts of closed panes and pixie panes;
    /// a closed tab keeps its panes.
    func syncTools() {
        tools.keep(Set(app.projects.values.flatMap { $0.tools.keys }))
        model.transcripts.keep(app.openPanes.union(app.openPixieChats(pixies.pixies)))
    }

    // MARK: Tabs

    /// A project tab: leaves the Pixies tab.
    func selectProject(_ name: String) {
        pixiesOpen = false
        app.selectProject(name)
    }

    /// A project opened from the + menu becomes the current tab, leaving the Pixies tab.
    func openProject(_ name: String) {
        pixiesOpen = false
        app.openProject(name)
    }

    /// Cmd-1 to Cmd-9.
    func selectProject(at index: Int) {
        pixiesOpen = false
        app.selectProject(at: index)
    }

    /// Previous and Next Project; from the Pixies tab they go to the current project.
    func selectProject(offset: Int) {
        if pixiesOpen {
            pixiesOpen = false
        } else {
            app.selectProject(offset: offset)
        }
    }

    // MARK: Pixies

    /// Cmd-0: the Pixies tab, with the pixie panes it had.
    func openPixies() {
        close()
        pixiesOpen = true
    }

    /// The pixies the list shows: the visible ones, or all while hidden ones are shown.
    var listedPixies: [Pixie] {
        showsHiddenPixies ? pixies.pixies : pixies.visible
    }

    /// The pixie of the focused pane in the Pixies tab, whose details the right panel shows.
    var shownPixie: Pixie? {
        app.pixieState.layout.focused.flatMap(pixie)
    }

    func pixie(_ id: String) -> Pixie? {
        pixies.pixies.first { $0.id == id }
    }

    /// A pixie clicked in the list: opens its pane in the Pixies tab, or focuses it.
    func openPixie(_ id: String) {
        pixiesOpen = true
        let size = workspaceSize
        updateWorkspace { $0.openChat(id, in: size) }
    }

    /// A pixie pane's Details button: shows that pixie's details, or hides them when they
    /// show already.
    func togglePixieDetails(_ id: String) {
        let showing = pixieDetailsOpen && app.pixieState.layout.focused == id
        focusPane(id)
        withAnimation(.smooth(duration: 0.22)) { pixieDetailsOpen = !showing }
    }

    /// Closes the panes of pixies that were deleted, here or on another device.
    func keepPixiePanes() {
        app.keepPixies(Set(pixies.pixies.map(\.id)))
        syncTools()
    }

    /// A notification or approval of a pixie's chat: the Pixies tab, on the pixie's pane.
    func revealPixie(_ id: String) {
        close()
        openPixie(id)
    }

    /// New pixie and the starters open the new pixie's pane; New pixie also opens its
    /// details to set it up.
    func createPixie(_ request: CreatePixieRequest, details: Bool) {
        run("Could not create the pixie") {
            let created = try await self.pixies.create(request)
            self.openPixie(created.id)
            withAnimation(.smooth(duration: 0.22)) { self.pixieDetailsOpen = details }
        }
    }

    /// Saves one change at once; there is no form to submit (D072). A pixie in Auto moved
    /// to a model without it drops to Ask, as the daemon does for any chat; a toast says so.
    func updatePixie(_ id: String, _ request: UpdatePixieRequest) {
        let before = pixies.pixies.first { $0.id == id }
        run("Could not save the pixie") {
            // The daemon's answer to this very save, not what later saves show meanwhile.
            let saved = try await self.pixies.update(id, request)
            if before?.droppedAuto(by: request, saved: saved) == true {
                let model = saved.model.map { self.agents.label(for: $0) } ?? "The default model"
                self.show(
                    "\(model) does not support Auto mode: permissions are now \(saved.permissionMode.label)"
                )
            }
        }
    }

    /// Drag and drop in the Pixies list: the pixie takes the other one's place.
    func movePixie(_ id: String, onto target: String) {
        run("Could not reorder the pixies") { try await self.pixies.move(id, onto: target) }
    }

    /// Move Up (-1) and Move Down (1) among the listed pixies.
    func movePixie(_ id: String, by offset: Int) {
        let listed = listedPixies.map(\.id)
        run("Could not reorder the pixies") {
            try await self.pixies.move(id, by: offset, among: listed)
        }
    }

    /// Why the slug was refused (taken or not allowed), else nil.
    func setPixieSlug(_ id: String, _ slug: String) async -> String? {
        do {
            try await pixies.update(id, UpdatePixieRequest(slug: slug))
        } catch APIError.invalidInput(let message), APIError.conflict(let message, _) {
            return message
        } catch {
            show(error, doing: "Could not save the pixie")
        }
        return nil
    }

    func resetPixie(_ id: String) {
        run("Could not reset the conversation") {
            try await self.pixies.reset(id)
            self.show("Started a fresh conversation", kind: .done)
        }
    }

    func deletePixie(_ id: String) {
        run("Could not delete the pixie") {
            let name = self.pixies.pixies.first { $0.id == id }?.name ?? "The pixie"
            try await self.pixies.delete(id)
            self.keepPixiePanes()
            self.show("Deleted \(name)", kind: .done)
        }
    }

    /// The composer's key for a pixie's message, whichever chat it has.
    static func pixieDraft(_ id: String) -> String { "\(Pixie.repoPrefix)\(id)" }

    /// Sends through the pixie, which opens a fresh run when its chat needs one.
    func sendToPixie(_ id: String) {
        let draft = draft(for: Self.pixieDraft(id))
        let text = draft.text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !draft.sending else { return }
        let typed = draft.text
        draft.sending = true
        dictation.cancel()
        Task {
            defer { draft.sending = false }
            do {
                let sent = try await pixies.send(id, text: text)
                sessions.insert(sent.session)
                // Sent while the chat works: it shows as queued, as in any chat.
                if let queued = sent.queuedMessage {
                    activity.enqueue(queued, session: sent.session.id)
                }
                sentMessages.record(text, chat: sent.session.id)
                draft.clearSent(text: typed, attachments: [])
            } catch {
                show(error, doing: "Could not send")
            }
        }
    }

    // MARK: Session presentation

    func tone(of session: Session) -> StatusTone {
        sessions.tone(of: session)
    }

    /// Idle chats show a hollow dot.
    func isHollow(_ session: Session) -> Bool {
        sessions.isHollow(session)
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

    /// Archives a Claude Code chat or brings it back; archiving closes its pane, as it
    /// does for a harness chat.
    func setArchived(_ chat: ClaudeChat, _ archived: Bool) {
        if archived {
            update { $0.closePane(chat.paneID) }
        }
        run(archived ? "Could not archive" : "Could not unarchive") {
            try await self.claudeChats.setArchived(chat.id, archived)
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
    @discardableResult
    func newChat() -> ComposerDraft {
        pixiesOpen = false
        draftCount += 1
        let id = "\(Self.draftPrefix)\(draftCount)"
        let draft = draft(for: id)
        takeDefaults(draft)
        openChat(id)
        return draft
    }

    /// The empty workspace's composer (B39): a new chat's draft for the current project,
    /// with the new-chat defaults; its first message opens the chat in a pane.
    var startDraftID: String { "\(Self.draftPrefix)start-\(project ?? "")" }

    func startDraft() -> ComposerDraft {
        drafts.draft(for: startDraftID) { takeDefaults($0) }
    }

    /// The saved defaults arrived after the start draft was made from the standard ones.
    func startDefaultsLoaded() {
        takeDefaults(startDraft())
    }

    private func takeDefaults(_ draft: ComposerDraft) {
        let defaults = agents.current
        draft.model = defaults.model
        draft.effort = defaults.effort
        draft.permission = defaults.permissionMode
        draft.mode = repo.map { $0.mode(for: defaults.mode) } ?? defaults.mode
    }

    /// A plain folder's Init: a new chat with the git setup request written, not sent.
    func setUpGit() {
        let draft = newChat()
        draft.text = GitInit.prompt
        draft.selection = TextSelection(insertionPoint: draft.text.endIndex)
        draft.wantsFocus = true
    }

    /// Cmd-W: closes the open sheet, else the focused pane (a chat's or a pixie's), else
    /// the window.
    func closeFocused() {
        if overlay != nil {
            close()
        } else if let focused = workspaceState.layout.focused {
            closePane(focused)
        } else {
            NSApp.keyWindow?.performClose(nil)
        }
    }

    /// Cmd-Return: sends the focused pane's message.
    func sendFocused() {
        if pixiesOpen {
            if let pixie = shownPixie {
                sendToPixie(pixie.id)
            }
        } else if let focused = projectState.layout.focused {
            send(focused)
        }
    }

    func closePane(_ id: String) {
        updateWorkspace { $0.closePane(id) }
        if isDraft(id) {
            drafts.remove(id)
        }
    }

    func toggleMaximize(_ id: String) {
        updateWorkspace { $0.layout.toggleMaximize(id) }
    }

    func focusPane(_ id: String) {
        let state = workspaceState
        guard state.layout.focused != id || state.selectedChat != id else { return }
        changeWorkspace { $0.focusPane(id) }
    }

    /// A gutter dragged between two panes of the workspace on screen.
    func resize(split: Int, ratio: Double) {
        let size = workspaceSize
        changeWorkspace { $0.layout.resize(split: split, ratio: ratio, in: size) }
    }

    func perform(_ item: DragItem, onto pane: String?, zone: DropZone) {
        switch zone {
        case .swap:
            if let pane {
                updateWorkspace { $0.layout.swap(item.chat, pane) }
            }
        case .open:
            updateWorkspace { $0.dropChat(item.chat, onto: nil, side: .right) }
        case .replace:
            updateWorkspace { $0.dropChat(item.chat, onto: pane, side: .right) }
        case .split(let side):
            updateWorkspace { $0.dropChat(item.chat, onto: pane, side: side) }
        case .none:
            break
        }
        dragging = nil
        dropHighlight = nil
    }

    // MARK: Pane drags

    /// The pointer moved while `pane` is dragged by its header: shows where it would land.
    func movePaneDrag(_ pane: String, title: String, tone: StatusTone, to location: CGPoint) {
        guard !paneDragCancelled else { return }
        dragging = .pane(pane)
        paneDrag = PaneDrag(pane: pane, title: title, tone: tone, location: location)
        let highlight = paneDropHit(pane, at: location).map {
            DropHighlight(pane: $0.pane, zone: $0.zone)
        }
        if dropHighlight != highlight {
            withAnimation(.easeOut(duration: 0.14)) { dropHighlight = highlight }
        }
    }

    /// The header was released: swaps with the pane under the pointer, if any, and always
    /// ends the drag.
    func endPaneDrag(_ pane: String, at location: CGPoint) {
        if !paneDragCancelled, let hit = paneDropHit(pane, at: location) {
            perform(.pane(pane), onto: hit.pane, zone: hit.zone)
        }
        paneDragCancelled = false
        clearDrag()
    }

    /// Hit-tested against the visible panes; a maximized pane has nothing to swap with.
    private func paneDropHit(_ pane: String, at location: CGPoint) -> DropHit? {
        let layout = workspaceState.layout
        guard layout.maximized == nil else { return nil }
        return DropZone.hit(
            at: location, placements: layout.placements(in: workspaceSize), dragged: pane,
            kind: .pane)
    }

    private func clearDrag() {
        if dragging != nil || dropHighlight != nil || paneDrag != nil {
            dragging = nil
            dropHighlight = nil
            paneDrag = nil
        }
    }

    /// Watches the window's events while it shows. Escape cancels a pane drag. A chat
    /// dragged from the sidebar is a system drag, which reports no end when it is
    /// cancelled or refused; local monitors see no events while one runs, so a click, or
    /// a move with no button down, means any drag still recorded is over.
    func startWatchingDrags() {
        guard dragMonitor == nil else { return }
        dragMonitor = NSEvent.addLocalMonitorForEvents(matching: [
            .keyDown, .leftMouseDown, .mouseMoved, .mouseEntered, .mouseExited,
        ]) { [weak self] event in
            let passes = MainActor.assumeIsolated { self?.watch(event) ?? true }
            return passes ? event : nil
        }
    }

    func stopWatchingDrags() {
        if let dragMonitor {
            NSEvent.removeMonitor(dragMonitor)
        }
        dragMonitor = nil
    }

    /// Whether the event goes on to the window.
    private func watch(_ event: NSEvent) -> Bool {
        switch event.type {
        case .keyDown:
            // Escape (key code 53) is swallowed only when it cancels a pane drag or an
            // inline edit.
            guard event.keyCode == 53 else { return true }
            if let edit = inlineEdit {
                inlineEdit = nil
                edit.end(false)
                return false
            }
            guard paneDrag != nil else { return true }
            paneDragCancelled = true
            clearDrag()
            return false
        case .leftMouseDown:
            paneDragCancelled = false
            clearDrag()
            if let point = Self.contentPoint(of: event) {
                endInlineEdit(outside: point)
                focusPane(at: point)
            }
        default:
            if NSEvent.pressedMouseButtons == 0 {
                clearDrag()
            }
        }
        return true
    }

    /// Where a click landed in its window's content, top-left origin; nil for a click in
    /// a menu, popover or other window that is not a main window.
    private static func contentPoint(of event: NSEvent) -> CGPoint? {
        guard let window = event.window, window.canBecomeMain, let view = window.contentView
        else { return nil }
        let point = view.convert(event.locationInWindow, from: nil)
        return view.isFlipped ? point : CGPoint(x: point.x, y: view.bounds.height - point.y)
    }

    /// A click outside the inline field being edited ends the edit, as leaving it does.
    private func endInlineEdit(outside point: CGPoint) {
        guard let edit = inlineEdit, !edit.frame.contains(point) else { return }
        inlineEdit = nil
        edit.end(true)
    }

    /// A click anywhere in a pane of the workspace on screen focuses it, whatever view
    /// inside takes the click (text views and terminals keep theirs from SwiftUI).
    private func focusPane(at point: CGPoint) {
        let showsWorkspace =
            pixiesOpen ? !pixies.pixies.isEmpty : project != nil && projectState.view == .workspace
        guard overlay == nil, showsWorkspace, let frame = workspaceFrame else { return }
        let local = CGPoint(x: point.x - frame.minX, y: point.y - frame.minY)
        if let pane = workspaceState.layout.pane(at: local, in: frame.size) {
            focusPane(pane)
        }
    }

    // MARK: Composer

    func draft(for id: String) -> ComposerDraft {
        drafts.draft(for: id)
    }

    func send(_ chat: String) {
        let draft = draft(for: chat)
        let text = draft.text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !draft.sending, !draft.isUploading else { return }
        let typed = draft.text
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
                // Text typed and files attached while it was sending stay.
                draft.clearSent(text: typed, attachments: attachments)
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
        let mode = app.repo(repo).map { $0.mode(for: draft.mode) } ?? draft.mode
        let request = CreateSessionRequest(
            repo: repo, prompt: prompt, mode: mode, model: draft.model,
            effort: draft.effort, permissionMode: draft.permission, attachmentIDs: attachments)
        let session = try await sessions.create(request)
        // What was typed or attached meanwhile stays in the chat's composer.
        drafts.move(draftID, to: session.id)
        let size = workspaceSize
        withAnimation(.smooth(duration: 0.22)) {
            app.update(repo) { $0.startChat(fromDraft: draftID, as: session.id, in: size) }
        }
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

    /// Up arrow in an empty composer: the chat's last message, caret at its end. A pixie's
    /// composer names its draft apart from its chat.
    func recallLastMessage(_ chat: String, into draftKey: String? = nil) {
        let items = model.transcripts.existing(chat)?.items ?? []
        guard let text = sentMessages.last(chat: chat, transcript: items) else { return }
        draft(for: draftKey ?? chat).replaceText(text, caret: text.count)
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
    /// Run in terminal. A command of several lines is not run (`TerminalInput`), nor one
    /// whose folder is gone.
    func runInTerminal(command: String, from chat: String?) {
        guard let project, let line = TerminalInput.line(for: command),
            let place = model.terminalFolder(forPane: chat, project: project)
        else {
            return
        }
        guard case .ready(let folder) = place else {
            show(TerminalFolder.goneMessage, kind: .failed)
            return
        }
        let size = workspaceSize
        var target: ToolPane?
        withAnimation(.smooth(duration: 0.22)) {
            app.update(project) { target = $0.terminal(for: folder, in: size).pane }
        }
        syncTools()
        if let target, !tools.terminal(for: target).run(line: line) {
            show(TerminalFolder.goneMessage, kind: .failed)
        }
    }

    // MARK: Terminal and browser panes

    /// The folder a pane's chat works in (`AppModel.folder(ofPane:)`).
    func folder(ofPane pane: String) -> String? {
        model.folder(ofPane: pane)
    }

    /// "Terminal here": the folder's terminal pane, focused, or a new one; nothing opens
    /// for a folder that is gone.
    func openTerminal(in folder: String) {
        guard TerminalFolder.exists(folder) else {
            show(TerminalFolder.goneMessage, kind: .failed)
            return
        }
        let size = workspaceSize
        update { $0.terminal(for: folder, in: size) }
    }

    /// A new terminal pane in the project folder.
    func newTerminal() {
        guard let path = repo?.path else { return }
        pixiesOpen = false
        let size = workspaceSize
        update { $0.openTool(.terminal(in: path), in: size) }
    }

    /// The bottom bar's Terminal button: the project's terminal pane, or a new one in the
    /// project folder.
    func openProjectTerminal() {
        guard let path = repo?.path else { return }
        let size = workspaceSize
        update { $0.projectTerminal(folder: path, in: size) }
    }

    func newBrowser(url: String? = nil) {
        guard project != nil else { return }
        pixiesOpen = false
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
                    let uploaded = try await AttachmentFile.upload(url, with: model.api)
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
            draft.permission = agents.newChatPermission(
                draft.permission, afterSwitchingTo: info.value)
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

    /// Menus offer only named modes; a nil is ignored.
    func setPermission(_ mode: PermissionMode?, for chat: String) {
        guard let mode else { return }
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
            openProject(known.name)
            return
        }
        run("Could not add the project") {
            try await self.app.addProject(path: path)
            self.pixiesOpen = false
        }
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
            reveal(chat: chat, in: project)
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
            selectProject(project)
        case .openMessage(let project, let pane, let event):
            openMessage(project: project, pane: pane, event: event)
        }
    }

    /// A notification was clicked: show its chat.
    func reveal(chat: String, in project: String) {
        if let pixie = Pixie.id(ofRepo: project) {
            revealPixie(pixie)
            return
        }
        pixiesOpen = false
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
            let rule = approval.permission?.suggestedRule
            let done =
                !always
                ? "Approved"
                : rule.map { "Always allowing \($0)" } ?? "Always allowed in this chat"
            self.show(done, kind: .done)
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
            let mode = try await self.approvals.approvePlan(approval)
            self.show("Plan approved. Claude continues with \(mode.label)", kind: .done)
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

    /// Approves again, pushing to the address origin pushes to now (I-008).
    func pushThere(_ approval: Approval, _ form: PublishForm, url: String) {
        var confirmed = form
        confirmed.confirmRemoteURL = url
        publish(approval, confirmed)
    }

    func publish(_ approval: Approval, _ form: PublishForm) {
        Task {
            // A refusal reads the chat and its diff again; the sheet shows why.
            guard let session = try? await sessions.publish(approval, form) else { return }
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

    /// Has the daemon send the failing checks and their logs into the chat.
    func sendChecksFailure(_ session: Session) {
        run("Could not send the checks") {
            if try await self.sessions.sendChecksFailure(session.id) {
                self.show("Sent the failing checks to \(session.title)", kind: .done)
            }
        }
    }

    // MARK: Restoring files

    /// Asks to restore the chat's files to before one of its messages, with a preview.
    func startRewind(_ chat: String, message: Int) {
        let flow = RewindFlow(session: chat, message: message, api: model.api)
        rewinding = flow
        show(.rewind)
        Task { await flow.load() }
    }

    func confirmRewind() {
        guard let flow = rewinding else { return }
        Task {
            guard await flow.restore() else { return }
            if overlay == .rewind {
                close()
            }
            show("Restored the files to before that message", kind: .done)
        }
    }

    // MARK: Project settings

    /// Changes a project's worktree default, links or setup commands; saves run in turn.
    func changeSettings(
        of project: String, _ change: @escaping @Sendable (inout WorktreeConfig) -> Void
    ) {
        run("Could not save the project settings") {
            try await self.app.changeSettings(of: project, change)
        }
    }

    /// Removes a project from harness, deleting its chats; the folder stays.
    func removeProject(_ name: String) {
        let chats = sessions.sessions(in: name).count
        if overlay == .project(name) {
            close()
        }
        run("Could not remove \(name)") {
            try await self.app.removeProject(name, purgeChats: chats > 0)
            self.show("Removed \(name) from harness", kind: .done)
        }
    }

    /// Opens a pull request or check page; only web links open (`SafeLink`).
    func openOnGitHub(_ url: String) {
        if let link = SafeLink.url(url) {
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
    /// Nil leaves it to Claude Code's own setting.
    var permission: PermissionMode?
    var mode: SessionMode?
    /// The caret and selection in the field.
    var selection: TextSelection?
    /// Focus the field when its pane appears, as for Init's prefilled chat.
    var wantsFocus = false
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

    /// After a send: removes the text and files that went, keeping what was typed or
    /// attached meanwhile.
    func clearSent(text sent: String, attachments sentIDs: [String]) {
        let rest = SentDraft.remainder(of: text, after: sent)
        if rest != text {
            replaceText(rest, caret: rest.count)
        }
        if rest.isEmpty {
            selection = nil
        }
        completion = CompletionSelection()
        volatile = ""
        attachments.removeAll { $0.uploaded.map { sentIDs.contains($0.id) } ?? false }
        hint = nil
        blocked = nil
    }
}
