import AppKit
import NestKit
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
    static let nestChat = UTType(exportedAs: "local.nest.app.chat", conformingTo: .data)
}

extension NSItemProvider {
    /// A sidebar chat's drag; only this app's own panes read it (`shell.dragging` says
    /// which chat).
    static func chat(_ id: String) -> NSItemProvider {
        let provider = NSItemProvider()
        provider.registerDataRepresentation(for: .nestChat, visibility: .ownProcess) {
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
    /// The diff of a review, by approval id.
    case diff(String)
    /// The approve sheet of a review, by approval id.
    case publish(String)
    /// Rewinding to before a message, or editing one (`Shell.rewinding`).
    case rewind
    /// A habit run's transcript, read-only, by session id (B42).
    case habitRun(String)
    /// A tool result's image full size, by attachment id (B59).
    case image(String)
    /// A subagent's, pixie's or team's work in a chat, read-only (`ChatPixiesStore.work`,
    /// B46).
    case work
}

/// What the Pixies tab's right-hand panel shows for the focused pixie: the details, or a
/// page opened from them.
enum PixiePanel: Equatable {
    case details
    case soul
    case memory
    /// What the pixie did with its Nest tools (B41).
    case activity
    /// A note of the memory page, by name.
    case note(String)
    /// Its habits (B42).
    case habits
    /// New habit (nil) or Edit, by habit id.
    case habit(String?)
    /// A habit's latest runs, by habit id.
    case habitHistory(String)
}

/// The window's model: the daemon's stores plus the transient state of the views, and
/// the actions they call.
@MainActor @Observable
final class Shell {
    static let draftPrefix = "draft-"

    let model: AppModel
    let userName: String
    var overlay: Overlay?
    /// The rewind the rewind sheet shows.
    var rewinding: RewindFlow?
    /// The palette while it is open.
    var palette = CommandPalette(items: [])

    var renaming: String?
    var renameText = ""
    /// The chat whose delete confirmation is showing.
    var deleting: String?
    /// Projects whose Archived group is unfolded.
    var archivedOpen: Set<String> = []
    /// Right panel rows opened or closed by the user, by row key; the rest keep their
    /// default (B77).
    var foldedRows: [String: Bool] = [:]
    /// The Settings window's page, search text and tabs (B81).
    var settingsPage = SettingsPage.general
    var settingsQuery = ""
    var projectTab = ProjectSettingsTab.general
    /// Settings > Configuration's open folds, such as "claude:plugins" (B97).
    var configurationFolds: Set<String> = ["claude:plugins"]
    /// The Add server, Edit server or New skill form over Settings (B97).
    var configurationForm: ConfigurationForm?
    /// Opens a window scene by id; the main window sets it once it shows.
    @ObservationIgnored var openWindow: ((String) -> Void)?
    /// The Connections list's unfolded groups; all are folded at first.
    var connectorGroupsOpen: Set<ConnectorSectionKind> = []
    /// Expanded tool calls and thinking blocks, by transcript item id.
    var expandedItems: Set<String> = []
    /// The turn end of the transcript row under the pointer: its "Worked for" line shows
    /// (B71). Set through `setHoveredTurnEnd`.
    private(set) var hoveredTurnEnd: String?
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
    /// The start screen's question, the next one each time it appears again (B90); the
    /// screen keeps the one it took while it stays.
    @ObservationIgnored var startQuestions = StartQuestionRotation()
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
    var bash: BashStore { model.bash }
    var images: AttachmentImages { model.images }
    var agents: AgentsStore { model.agents }
    /// The engines chats run on (B91).
    var providers: ProvidersStore { model.providers }
    var pixies: PixiesStore { model.pixies }
    var reports: PixieReportsStore { model.reports }
    var habits: HabitsStore { model.habits }
    var chatPixies: ChatPixiesStore { model.chatPixies }
    var shortcuts: ShortcutsStore { model.shortcuts }
    var artifacts: ArtifactsStore { model.artifacts }

    /// The Claude account's name, else the Mac user's.
    var accountName: String { agents.accountName(fallback: userName) }

    /// The Pixies tab is showing in place of a project.
    var pixiesOpen = false
    /// The details panel on the right of the Pixies tab, for the focused pixie pane.
    var pixieDetailsOpen = false
    /// The list shows hidden pixies too, so they can be opened and shown again.
    var showsHiddenPixies = false
    var pixiePanel = PixiePanel.details
    /// The Pixies list's open question, with the text typed into it.
    var pixiePrompt: PixiePrompt?
    var pixiePromptText = ""

    var project: String? { app.currentProject }
    var projectState: ProjectState { project.map(app.state(of:)) ?? ProjectState() }
    var repo: Repo? { project.flatMap(app.repo) }

    /// The workspace on screen: the Pixies tab's (its panes are pixies) or the current
    /// project's. The pane views and their actions work on this one.
    var workspaceState: ProjectState { pixiesOpen ? app.pixieState : projectState }

    /// Writes only a change: every turn end line reads it, and rows pass under the pointer
    /// on each scroll.
    func setHoveredTurnEnd(_ end: String?) {
        if hoveredTurnEnd != end {
            hoveredTurnEnd = end
        }
    }

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

    /// The pixie's own chat is starting or running a turn: its sprite hops (B48).
    func isWorking(_ pixie: Pixie) -> Bool {
        pixie.chatSessionID.flatMap(sessions.session)?.state.isWorking ?? false
    }

    /// A pixie clicked in the list: opens its pane in the Pixies tab, or focuses it.
    func openPixie(_ id: String) {
        pixiesOpen = true
        let focused = app.pixieState.layout.focused
        let size = workspaceSize
        withAnimation(.smooth(duration: 0.22)) { app.openPixie(id, in: size) }
        if app.pixieState.layout.focused != focused {
            pixiePanel = .details
        }
        syncTools()
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
        // The click came from a project's view, which the Pixies tab replaces in this
        // same update: open it again once the tab is on screen, which only focuses it
        // when it stayed open.
        Task { @MainActor in self.openPixie(id) }
    }

    /// New pixie and the starters open the new pixie's pane; New pixie also opens its
    /// details to set it up.
    func createPixie(_ request: CreatePixieRequest, details: Bool) {
        run("Could not create the pixie") {
            // The daemon fills in the rest from Settings > Pixies (B81).
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
                let catalog = self.providers.catalog(for: saved.engine, claude: self.agents.catalog)
                let model = saved.model.map { catalog.label(for: $0) } ?? "The default model"
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

    /// Move Up (-1) and Move Down (1) among the listed pixies of its section.
    func movePixie(_ id: String, by offset: Int) {
        let listed = pixieSections.neighbors(of: id)
        run("Could not reorder the pixies") {
            try await self.pixies.move(id, by: offset, among: listed)
        }
    }

    // MARK: Teams and the pixie menus (B40)

    /// The Pixies list: teams with their listed members, then pixies with no team.
    var pixieSections: PixieListSections {
        PixieListLayout.sections(listedPixies, teams: pixies.teams)
    }

    /// Asks the question in the Pixies list; a rename starts from the current text.
    func ask(_ prompt: PixiePrompt) {
        pixiePromptText = prompt.startText(teams: pixies.teams)
        pixiePrompt = prompt
    }

    /// The answer to the question: Create, Rename, Save or Delete.
    func answerPixiePrompt() {
        guard let prompt = pixiePrompt else { return }
        pixiePrompt = nil
        let text = pixiePromptText.trimmingCharacters(in: .whitespacesAndNewlines)
        switch prompt {
        case .newTeam where !text.isEmpty:
            run("Could not create the team") { try await self.pixies.createTeam(name: text) }
        case .renameTeam(let id) where !text.isEmpty:
            updateTeam(id, UpdatePixieTeamRequest(name: text))
        case .teamHandle(let id) where !text.isEmpty:
            updateTeam(id, UpdatePixieTeamRequest(handle: text))
        case .deletePixie(let id):
            deletePixie(id)
        case .deleteTeam(let id):
            run("Could not delete the team") { try await self.pixies.deleteTeam(id) }
        default:
            break
        }
    }

    func updateTeam(_ id: String, _ request: UpdatePixieTeamRequest) {
        run("Could not save the team") { try await self.pixies.updateTeam(id, request) }
    }

    func toggleTeamFold(_ id: String) {
        withAnimation(.smooth(duration: 0.2)) { app.toggleTeamFold(id) }
    }

    /// Move to team: a team's id, or nil for No team.
    func setPixieTeam(_ id: String, _ team: String?) {
        run("Could not move the pixie") { try await self.pixies.setTeam(id, to: team) }
    }

    /// A pixie dropped on another one joins its section, at its place.
    func placePixie(_ id: String, onto target: String) {
        run("Could not move the pixie") { try await self.pixies.place(id, onto: target) }
    }

    func duplicatePixie(_ id: String) {
        run("Could not duplicate the pixie") {
            let copy = try await self.pixies.duplicate(id)
            self.show("Duplicated as \(copy.name)", kind: .done)
        }
    }

    func showPixieDetails(_ id: String) {
        openPixie(id)
        withAnimation(.smooth(duration: 0.22)) { pixieDetailsOpen = true }
    }

    /// The pixies and teams a chat's `@` list offers: those its project may call; nil in a
    /// pixie's chat, which calls none yet. Souls are read the first time they are needed.
    func pixieMentions(forChat chat: String) -> [PixieMention]? {
        guard let repo = sessions.session(chat)?.repo ?? project, Pixie.id(ofRepo: repo) == nil,
            supports(.pixies, chat: chat)
        else { return nil }
        return PixieMentions.available(
            pixies: pixies.pixies, teams: pixies.teams, souls: pixies.soulLines)
    }

    // MARK: Each chat's pixies and subagents (B46)

    /// Opens a subagent's transcript, or a pixie's, team's or member's calls in a chat,
    /// read-only; follow-ups go in the chat itself.
    func openWork(_ target: WorkTarget) {
        show(.work)
        Task { await chatPixies.open(target) }
    }

    /// The pixie, or the team with its members, leaves the chat's Pixies group; calling it
    /// again starts it fresh.
    func sendAway(_ entry: ChatPixieEntry, from chat: String, name: String) {
        run("Could not send \(name) away") {
            try await self.chatPixies.sendAway(entry, session: chat)
            self.show("Sent \(name) away", kind: .done)
        }
    }

    /// The slugs a chat's messages leave plain: pixies called only through their team.
    func plainMentions(forChat chat: String) -> Set<String> {
        Set(PixieMentions.members(pixieMentions(forChat: chat) ?? []).keys)
    }

    /// Why the slug was refused (taken or not allowed), else nil.
    func setPixieSlug(_ id: String, _ slug: String) async -> String? {
        do {
            try await pixies.update(id, UpdatePixieRequest(slug: slug))
        } catch APIError.invalidInput(let message), APIError.conflict(let message) {
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
        if case .memory(let memory) = composerInput(for: Self.pixieDraft(id), text: draft.text) {
            if !memory.isEmpty {
                draft.memory = memory
            }
            return
        }
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

    /// A choice tapped on a pixie's choices card: its text, sent as the user's reply.
    func sendChoice(_ text: String, to pixie: String) {
        Task {
            do {
                let sent = try await pixies.send(pixie, text: text)
                sessions.insert(sent.session)
                if let queued = sent.queuedMessage {
                    activity.enqueue(queued, session: sent.session.id)
                }
            } catch {
                show(error, doing: "Could not send")
            }
        }
    }

    // MARK: Habits and reports (B42)

    /// Saves a new habit or the changes to one; true once the daemon took it.
    func saveHabit(_ draft: HabitDraft, editing habit: PixieHabit?, of pixie: String) async
        -> Bool
    {
        do {
            if let habit {
                try await habits.update(habit.id, in: pixie, draft.update(from: habit))
            } else {
                try await habits.create(in: pixie, draft.create)
            }
            return true
        } catch {
            show(error, doing: "Could not save the habit")
            return false
        }
    }

    func setHabit(_ habit: PixieHabit, enabled: Bool) {
        run(enabled ? "Could not resume the habit" : "Could not pause the habit") {
            try await self.habits.setEnabled(habit.id, in: habit.pixieID, enabled)
        }
    }

    func runHabitNow(_ habit: PixieHabit) {
        run("Could not run the habit") {
            try await self.habits.runNow(habit.id, in: habit.pixieID)
            self.show("\(habit.name) is queued to run", kind: .done)
        }
    }

    func deleteHabit(_ habit: PixieHabit) {
        run("Could not delete the habit") {
            try await self.habits.delete(habit.id, in: habit.pixieID)
            if self.pixiePanel != .habits {
                self.pixiePanel = .habits
            }
        }
    }

    /// Start on a suggested habit: creates it, enabled.
    func startSuggestedHabit(_ suggestion: HabitSuggestion, for pixie: String) async -> Bool {
        do {
            try await habits.create(in: pixie, HabitDraft(suggestion: suggestion).create)
            return true
        } catch {
            show(error, doing: "Could not start the habit")
            return false
        }
    }

    /// Opens a habit run's transcript, read-only.
    func openHabitRun(_ session: String) {
        withAnimation(.smooth(duration: 0.18)) { overlay = .habitRun(session) }
    }

    /// An inbox entry's Open: the pixie, with its reports read.
    func openReport(_ report: PixieReport) {
        revealPixie(report.pixieID)
        markReportsRead(of: report.pixieID)
    }

    func dismissReport(_ report: PixieReport) {
        run("Could not dismiss the report") { try await self.reports.markRead(report.id) }
    }

    func markReportsRead(of pixie: String) {
        run("Could not mark the reports read") { try await self.reports.markPixieRead(pixie) }
    }

    // MARK: Artifacts (B79)

    /// What the Artifacts view lists: in the Pixies tab the focused pixie's, with a switch
    /// to every pixie's; in a project the focused chat's, with a switch to the whole
    /// project, or the whole project while no chat is focused.
    var artifactScope: ArtifactScope? {
        if pixiesOpen {
            return ArtifactScope(narrow: shownPixie.map { .pixie($0.id) }, wide: .pixies)
        }
        guard let project else { return nil }
        let chat = projectState.layout.focused.flatMap(sessions.session)?.id
        return ArtifactScope(narrow: chat.map(ArtifactQuery.chat), wide: .project(project))
    }

    /// The status bar's switch, the View menu and the palette: a view of the tab on screen;
    /// the Board leaves the Pixies tab, which has none.
    func showView(_ view: ProjectView) {
        if pixiesOpen && !ProjectView.choices(pixies: true).contains(view) {
            pixiesOpen = false
        }
        updateWorkspace { $0.view = view }
    }

    /// A transcript card's Open, or a row of a pixie's page: the Artifacts view of the tab
    /// on screen, with that version, or the latest, in the reader.
    func openArtifact(_ id: String, version: Int?, from chat: String?) {
        updateWorkspace { state in
            if let chat, state.layout.contains(chat) {
                state.focusPane(chat)
            }
            state.view = .artifacts
        }
        if let scope = artifactScope {
            artifacts.show(scope)
        }
        run("Could not open the artifact") {
            try await self.artifacts.select(id, version: version)
        }
    }

    /// Writes the version as a file where the user picks; HTML without the injected
    /// policy, as it was saved, or a multi-file page as its built, self-contained page.
    func saveArtifact(_ content: ArtifactContent) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = ArtifactFile.name(title: content.title, kind: content.kind)
        panel.allowedContentTypes = [
            UTType(filenameExtension: ArtifactFile.fileExtension(content.kind)) ?? .plainText
        ]
        panel.begin { response in
            guard response == .OK, let url = panel.url else { return }
            do {
                try Data(ArtifactFile.savedText(content).utf8).write(to: url, options: .atomic)
                self.show("Saved \(url.lastPathComponent)", kind: .done)
            } catch {
                self.show(error, doing: "Could not save the file")
            }
        }
    }

    /// Delete in the reader, after its confirmation.
    func deleteArtifact(_ id: String) {
        run("Could not delete the artifact") { try await self.artifacts.delete(id) }
    }

    // MARK: Session presentation

    func tone(of session: Session) -> StatusTone {
        sessions.tone(of: session)
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

    /// Claude Code chats being continued in Nest, by chat id.
    var adopting: Set<String> = []

    /// The sidebar's groups: pinned chats, then the project's sessions and Claude Code
    /// chats by latest activity, then Archived (B77).
    func sidebarGroups(in project: String) -> [SidebarGroup] {
        SidebarGroup.list(
            sessions: sessions.sessions(in: project), chats: claudeChats.chats(in: project))
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
    func continueInNest(_ pane: String) {
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
                show(error, doing: "Could not continue in Nest")
            }
        }
    }

    /// Archives a Claude Code chat or brings it back; archiving closes its pane, as it
    /// does for a Nest chat.
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

    /// The defaults' engine, model, thinking and mode, all concrete (B94).
    private func takeDefaults(_ draft: ComposerDraft) {
        let defaults = agents.current
        let choices = NewChatChoices.from(
            defaults, catalog: providers.catalog(for: defaults.provider, claude: agents.catalog))
        draft.provider = choices.provider
        draft.model = choices.model
        draft.effort = choices.effort
        draft.permission = choices.permission
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
        switch composerInput(for: chat, text: draft.text) {
        case .bash(let command):
            runShell(command, in: chat, draft: draft)
            return
        case .memory(let memory):
            if !memory.isEmpty {
                draft.memory = memory
            }
            return
        case .message:
            break
        }
        if let command = LocalCommand(text) {
            draft.replaceText("", caret: 0)
            runLocal(command, in: chat)
            return
        }
        // A pixie of a team is called only through its team (B46); the daemon refuses it too.
        if let refusal = PixieMentions.memberCall(
            in: text, mentions: pixieMentions(forChat: chat) ?? [])
        {
            withAnimation { draft.blocked = refusal }
            return
        }
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
                    // The `!` commands run since the last message go first, for Claude.
                    let outgoing = bash.outgoing(text, chat: chat)
                    let queued = try await sessions.send(
                        chat, text: outgoing.text, attachmentIDs: attachments)
                    bash.sent(outgoing.rows, chat: chat)
                    if let queued {
                        activity.enqueue(queued, session: chat)
                    }
                    sentMessages.record(text, chat: chat)
                }
                // Text typed and files attached while it was sending stay.
                draft.clearSent(text: typed, attachments: attachments)
            } catch APIError.openInClaudeCode(let message), APIError.pixieInTeam(let message) {
                withAnimation { draft.blocked = message }
            } catch APIError.notSignedIn(let message) {
                withAnimation { draft.blocked = message }
                Task { await providers.load(refresh: true) }
            } catch {
                show(error, doing: "Could not send")
            }
        }
    }

    // MARK: `!` and `#` (B59)

    /// What the composer's text is in this chat: `!` runs in the user's own chats once
    /// they exist, `#` saves a memory in any chat that exists (a pixie's: `pixieDraft`).
    func composerInput(for draftKey: String, text: String) -> ComposerInput {
        guard let session = memorySession(for: draftKey) else { return .message }
        let bash =
            Pixie.id(ofRepo: draftKey) == nil
            && ComposerInput.canRunShell(in: sessions.session(session))
        // `#` saves to CLAUDE.md, which only Claude Code reads (B91).
        return ComposerInput.of(text, bash: bash, memory: supports(.memory, chat: draftKey))
    }

    /// The chat a composer's `#` and `!` act on; nil before the chat exists.
    func memorySession(for draftKey: String) -> String? {
        if let id = Pixie.id(ofRepo: draftKey) {
            return pixies.pixies.first { $0.id == id }?.chatSessionID
        }
        return isDraft(draftKey) ? nil : draftKey
    }

    /// Runs a `!` command in the chat's folder; its row shows below the transcript.
    private func runShell(_ command: String, in chat: String, draft: ComposerDraft) {
        guard !command.isEmpty else { return }
        draft.replaceText("", caret: 0)
        Task { await bash.run(command, chat: chat) }
    }

    /// Saves the composer's `#` memory where the user chose; the text stays on failure.
    func saveMemory(_ text: String, scope: MemoryScope, from draftKey: String) {
        let draft = draft(for: draftKey)
        draft.memory = nil
        guard let session = memorySession(for: draftKey) else { return }
        let typed = draft.text
        Task {
            do {
                let saved = try await model.api.saveMemory(session, text: text, scope: scope)
                if draft.text == typed {
                    draft.replaceText("", caret: 0)
                }
                show("\(saved.confirmation): \(Self.abbreviate(saved.path))", kind: .done)
            } catch {
                show(error, doing: "Could not save the memory")
            }
        }
    }

    private static func abbreviate(_ path: String) -> String {
        (path as NSString).abbreviatingWithTildeInPath
    }

    /// The new session's id.
    private func create(
        from draftID: String, draft: ComposerDraft, prompt: String, attachments: [String]
    ) async throws -> String {
        guard let repo = project else { return draftID }
        let place = NewChatPlace(mode: draft.mode, typed: draft.branchName, repo: app.repo(repo))
        let request = CreateSessionRequest(
            repo: repo, prompt: prompt, mode: place.mode, model: draft.model,
            effort: draft.effort, permissionMode: draft.permission, attachmentIDs: attachments,
            // The engine is always named: the daemon's own default may be another (B94).
            base: place.base, branch: place.branch,
            provider: draft.provider ?? ProviderInfo.claude)
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

    /// Resume now on a chat paused at the usage limit (B78).
    func resumeAfterLimit(_ chat: String) {
        run("Could not resume the chat") { try await self.sessions.resumeAfterLimit(chat) }
    }

    /// Stops one background task or subagent of the chat; its turn goes on (B59).
    func stopTask(_ task: String, in chat: String) {
        run("Could not stop it") { try await self.activity.stop(task: task, session: chat) }
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

    /// Puts a picked suggestion into the composer; a command Nest runs itself runs at
    /// once, as Claude Code's do.
    func complete(_ completion: Completion, in chat: String) {
        if completion.mention == nil, completion.label == "/\(completion.id)",
            let command = LocalCommand(named: completion.id)
        {
            draft(for: chat).replaceText("", caret: 0)
            runLocal(command, in: chat)
            return
        }
        draft(for: chat).replaceText(completion.text, caret: completion.caret)
    }

    /// Opens what Claude Code shows for a command the SDK cannot run (B59).
    func runLocal(_ command: LocalCommand, in chat: String) {
        let draft = draft(for: chat)
        switch command {
        case .model(nil):
            withAnimation(.smooth(duration: 0.15)) { draft.picker = .model }
        case .model(let name?):
            if let info = LocalCommand.model(named: name, in: catalog(forChat: chat).models) {
                setModel(info, for: chat)
                show("Model set to \(info.displayName)", kind: .done)
            } else {
                show("No model named \(name)", kind: .failed)
            }
        case .permissions:
            withAnimation(.smooth(duration: 0.15)) { draft.picker = .permissions }
        case .mcp:
            openConnectors()
        case .resume(let search):
            show(.palette)
            if let search {
                searchPalette(search)
            }
        }
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

    // MARK: Pending messages (B59)

    /// Removes a message Claude has not read yet; when it already has, the row says so.
    func removePending(_ message: QueuedMessage, in chat: String) {
        run("Could not remove the message") {
            try await self.activity.remove(message.id, session: chat)
        }
    }

    /// Stops the turn and sends the pending message right after it.
    func sendPendingNow(_ message: QueuedMessage, in chat: String) {
        run("Could not send the message now") {
            try await self.activity.sendNow(message.id, session: chat)
        }
    }

    /// Takes the pending message back into the composer (`draftKey`, the pane's); one
    /// Claude already read stays where it is.
    func editPending(_ message: QueuedMessage, in chat: String, draftKey: String) {
        run("Could not edit the message") {
            guard try await self.activity.remove(message.id, session: chat) else { return }
            self.restore(
                RestoredMessage(text: message.text, attachments: message.attachments),
                into: draftKey)
        }
    }

    /// Puts a message taken back (pending, rewound or forked) into a composer: at once
    /// into an empty one, otherwise after asking (`ComposerDraft.offered`).
    func restore(_ message: RestoredMessage, into draftKey: String) {
        let draft = draft(for: draftKey)
        if message.needsAsking(draft: draft.text) {
            draft.offered = message
        } else {
            draft.fill(message, keepingDraft: false)
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

    /// A connector's Sign in (B59): a server's runs Claude Code's `/mcp` in this
    /// project's terminal for the focused chat's folder, a claude.ai connector's opens its
    /// settings page.
    func signIn(_ connector: Connector) {
        switch connector.signIn {
        case .browser(let url):
            NSWorkspace.shared.open(url)
        case .terminal(let command):
            guard project != nil else {
                show("Open a project to sign in to \(connector.displayName)", kind: .info)
                return
            }
            close()
            runInTerminal(command: command, from: projectState.layout.focused)
        case nil:
            break
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

    /// The bottom bar's Terminal button (B60): the terminal pane in the focused chat's
    /// folder, or a new one there; without a focused chat, the project's terminal pane, or
    /// a new one in the project folder. Nothing opens for a chat whose folder is gone.
    func openProjectTerminal() {
        let target = model.terminalButtonTarget(
            focusedPane: projectState.layout.focused, project: project)
        let size = workspaceSize
        switch target {
        case .chat(let folder): update { $0.terminal(for: folder, in: size) }
        case .project(let folder): update { $0.projectTerminal(folder: folder, in: size) }
        case .gone: show(TerminalFolder.goneMessage, kind: .failed)
        case nil: break
        }
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
        for url in urls {
            attach(url.lastPathComponent, to: chat) { try await AttachmentFile.prepare(url) }
        }
    }

    /// Attaches pasted or dropped image data of a pasteboard type (B59).
    func attach(data: Data, type: String, to chat: String) {
        let filename = ImagePaste.filename(type: type)
        attach(filename, to: chat) {
            try await AttachmentFile.prepare(data: data, filename: filename)
        }
    }

    /// Shows the file at once, then prepares it (an image converted and scaled, with its
    /// thumbnail) and uploads it.
    private func attach(
        _ filename: String, to chat: String,
        prepare: @escaping @Sendable () async throws -> PreparedAttachment
    ) {
        let draft = draft(for: chat)
        let pending = PendingAttachment(filename: filename)
        draft.attachments.append(pending)
        Task {
            do {
                let prepared = try await prepare()
                draft.prepared(pending.id, as: prepared)
                let uploaded = try await AttachmentFile.upload(prepared, with: model.api)
                draft.finish(pending.id, with: uploaded)
            } catch {
                draft.remove(pending.id)
                show(error, doing: "Could not attach \(filename)")
            }
        }
    }

    /// Keeps the chat's effort only as far as the new model supports it. A new chat takes
    /// the engine of the model chosen (`provider`, nil: the chat's own; B91): its thinking
    /// and mode follow (`NewChatChoices`), and the engine's login is asked again, so the
    /// composer says when it is signed out. A chat that exists keeps its engine.
    func setModel(_ info: ModelInfo, on provider: String? = nil, for chat: String) {
        if isDraft(chat) {
            let draft = draft(for: chat)
            let engine = provider ?? draft.provider
            let current = NewChatChoices(
                provider: draft.provider, model: draft.model, effort: draft.effort,
                permission: draft.permission)
            let next = current.choosing(
                info.value, on: engine,
                catalog: providers.catalog(for: engine, claude: agents.catalog),
                defaults: agents.current)
            let switched = next.provider != draft.provider
            draft.provider = next.provider
            draft.model = next.model
            draft.effort = next.effort
            draft.permission = next.permission
            if switched {
                draft.blocked = nil
                Task { await providers.load(refresh: true) }
            }
        } else {
            let catalog = catalog(forChat: chat)
            let current = sessions.session(chat)?.effort
            let effort = catalog.effort(current, afterSwitchingTo: info.value)
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

    // MARK: Engines (B91)

    /// The chat's engine: a new chat's choice, else the session's; nil is Claude.
    func provider(forChat chat: String) -> String? {
        isDraft(chat) ? draft(for: chat).provider : sessions.session(chat)?.provider
    }

    /// The models the chat's menus offer: its engine's.
    func catalog(forChat chat: String) -> ModelCatalog {
        providers.catalog(for: provider(forChat: chat), claude: agents.catalog)
    }

    /// The chat's running agent in its words, such as "Codex keeps planning".
    func agentName(forChat chat: String) -> String {
        providers.displayName(provider(forChat: chat))
    }

    /// Whether the chat's engine can do it; the views hide what it cannot.
    func supports(_ feature: ProviderFeature, chat: String) -> Bool {
        providers.supports(feature, on: provider(forChat: chat))
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

    // MARK: Settings window (B81)

    /// Shows the Settings window on a page; a project's page opens on its General tab.
    func openSettings(_ page: SettingsPage = .general) {
        if page != settingsPage, case .project = page {
            projectTab = .general
        }
        settingsPage = page
        openWindow?(SettingsWindow.id)
    }

    /// Settings > Configuration with Claude's section and its connectors open (B97).
    func openConnectors() {
        model.configuration.openEngine("claude")
        configurationFolds.insert("claude:connectors")
        openSettings(.configuration)
    }

    /// Brings the main window forward, such as after Open on a pixie in Settings.
    func showMainWindow() {
        openWindow?(NestApp.mainWindowID)
    }

    /// Settings' project page: that project's tab in the main window, on the Artifacts view
    /// (B79), which lists the focused chat's artifacts with a switch to the whole project.
    func openArtifacts(project: String) {
        selectProject(project)
        showView(.artifacts)
        showMainWindow()
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
        if overlay == .work {
            chatPixies.closeWork()
        }
        // The usage popover opens on its chart again.
        if overlay == .usage {
            model.usage.hideDetails()
        }
        withAnimation(.smooth(duration: 0.18)) { overlay = nil }
    }

    /// Filters the palette and, after a pause in typing, searches the chats' messages.
    func searchPalette(_ text: String) {
        palette.search(text)
        Task {
            if let results = await model.search.results(for: text) {
                palette.show(results, for: text) {
                    self.providers.agentName(in: self.sessions.session($0))
                }
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
            showView(view)
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
            let agent = self.agentName(forChat: approval.sessionID)
            self.show("Rejected. \(agent) continues without it", kind: .failed)
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
            let agent = self.agentName(forChat: approval.sessionID)
            self.show("Plan approved. \(agent) continues with \(mode.label)", kind: .done)
        }
    }

    func keepPlanning(_ approval: Approval) {
        run("Could not send the plan back") {
            try await self.approvals.keepPlanning(approval)
            self.show("\(self.agentName(forChat: approval.sessionID)) keeps planning", kind: .info)
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
            guard (try? await sessions.publish(approval, form)) != nil else { return }
            if overlay == .publish(approval.id) {
                close()
            }
            show(form.done(approval.title), kind: .done)
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

    // MARK: Rewind, edit and fork (B59)

    /// Rewind on a user message: restore the conversation, the code or both, with
    /// previews.
    func startRewind(_ chat: String, message: Int) {
        let flow = RewindFlow(session: chat, message: message, api: model.api)
        rewinding = flow
        show(.rewind)
        Task { await flow.load() }
    }

    /// Esc Esc in an idle chat: Rewind on its latest message of the user.
    func rewindLast(_ chat: String) {
        guard RewindFlow.isAvailable(for: sessions.session(chat)), supports(.rewind, chat: chat),
            let message = model.transcripts.existing(chat)?.lastUserMessage
        else { return }
        startRewind(chat, message: message)
    }

    /// Edit on a user message: the conversation goes back to before it and the message
    /// into the composer; when files changed since, the sheet asks whether they go back
    /// too.
    func startEdit(_ chat: String, message: Int) {
        let flow = RewindFlow(session: chat, message: message, purpose: .edit, api: model.api)
        Task {
            await flow.load()
            if let reason = flow.reason(.conversation) {
                show("Could not edit the message: \(reason)", kind: .failed)
            } else if flow.needsChoice {
                rewinding = flow
                show(.rewind)
            } else {
                await finishRewind(flow, in: chat)
            }
        }
    }

    func confirmRewind() {
        guard let flow = rewinding else { return }
        Task { await finishRewind(flow, in: flow.session) }
    }

    private func finishRewind(_ flow: RewindFlow, in chat: String) async {
        guard let reply = await flow.confirm() else {
            if overlay != .rewind, let failure = flow.failure {
                show("Could not rewind: \(failure)", kind: .failed)
            }
            return
        }
        if overlay == .rewind {
            close()
        }
        if let message = reply.restoredMessage {
            restore(message, into: chat)
            draft(for: chat).wantsFocus = true
        } else {
            show("Restored the files to before that message", kind: .done)
        }
    }

    /// Fork from here: a new chat continuing the conversation as it was before the
    /// message, opened with the message in its composer.
    func fork(_ chat: String, message: Int) {
        run("Could not fork the chat") {
            let fork = try await self.sessions.fork(chat, message: message)
            self.openChat(fork.session.id)
            self.restore(fork.message, into: fork.session.id)
            self.draft(for: fork.session.id).wantsFocus = true
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

    /// Removes a project from Nest, deleting its chats; the folder stays.
    func removeProject(_ name: String) {
        let chats = sessions.sessions(in: name).count
        if settingsPage == .project(name) {
            settingsPage = .general
        }
        run("Could not remove \(name)") {
            try await self.app.removeProject(name, purgeChats: chats > 0)
            self.show("Removed \(name) from Nest", kind: .done)
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
        // The engines' lists were out of date; the next read hides the control.
        if case APIError.unsupportedFeature = error {
            Task { await providers.load() }
        }
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
    var filename: String
    /// An image's small PNG, once prepared.
    var thumbnail: Data?
    var uploaded: Attachment?
}

/// What a composer's picker chooses.
enum ComposerPicker: Equatable {
    case model, permissions
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
    /// New chats only: the choices sent with the first message. A nil engine is Claude.
    var provider: String?
    var model: String?
    var effort: Effort?
    var permission = PermissionMode.default
    var mode: SessionMode?
    /// A new worktree's branch name; blank lets the daemon name it.
    var branchName = ""
    /// The caret and selection in the field.
    var selection: TextSelection?
    /// Focus the field when its pane appears, as for Init's prefilled chat.
    var wantsFocus = false
    /// The highlighted suggestion, and whether Esc closed the list.
    var completion = CompletionSelection()
    /// The picker `/model` or `/permissions` opened above the field (B59).
    var picker: ComposerPicker?
    /// A message taken back while the field had text: the composer asks what to keep.
    var offered: RestoredMessage?
    /// A `#` memory waiting for the user to choose where it goes (B59).
    var memory: String?

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

    /// The name and thumbnail the prepared file goes with, such as a HEIC sent as JPEG.
    func prepared(_ id: UUID, as file: PreparedAttachment) {
        guard let index = attachments.firstIndex(where: { $0.id == id }) else { return }
        attachments[index].filename = file.filename
        attachments[index].thumbnail = file.thumbnail
    }

    func finish(_ id: UUID, with attachment: Attachment) {
        guard let index = attachments.firstIndex(where: { $0.id == id }) else { return }
        attachments[index].uploaded = attachment
    }

    func remove(_ id: UUID) {
        attachments.removeAll { $0.id == id }
    }

    /// Puts a message taken back into the field, before the draft when it stays, with
    /// its attachments (already uploaded to the chat).
    func fill(_ message: RestoredMessage, keepingDraft: Bool) {
        let newText = keepingDraft ? message.combined(with: text) : message.text
        replaceText(newText, caret: message.text.count)
        let files = message.attachments.map { attachment in
            var pending = PendingAttachment(filename: attachment.filename)
            pending.uploaded = attachment
            return pending
        }
        attachments = keepingDraft ? files + attachments : files
        offered = nil
        wantsFocus = true
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
