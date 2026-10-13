#if DEBUG
    import AppKit
    import HarnessKit
    import SwiftTerm
    import SwiftUI
    import WebKit

    /// Renders the window offscreen to PNG files for visual review, without showing any
    /// window: `HarnessApp --render-snapshots <folder>` uses sample data, and
    /// `HarnessApp --render-live <folder>` the local daemon, read-only (debug builds only).
    @MainActor
    enum Snapshots {
        static let size = CGSize(width: 1440, height: 900)

        static func runIfRequested() {
            let arguments = CommandLine.arguments
            guard
                let index = arguments.firstIndex(where: {
                    $0 == "--render-snapshots" || $0 == "--render-live"
                }), index + 1 < arguments.count
            else { return }
            let live = arguments[index] == "--render-live"
            let folder = URL(fileURLWithPath: arguments[index + 1], isDirectory: true)
            // An optional section name renders only that section, such as "b24".
            let only = index + 2 < arguments.count ? arguments[index + 2] : nil
            NSApplication.shared.setActivationPolicy(.prohibited)
            let finished = Flag()
            Task {
                do {
                    if live {
                        try await renderLive(to: folder)
                    } else {
                        try await render(to: folder, only: only)
                    }
                } catch {
                    print("snapshot failed: \(error)")
                }
                finished.value = true
            }
            while !finished.value {
                RunLoop.main.run(mode: .default, before: Date(timeIntervalSinceNow: 0.05))
            }
            exit(0)
        }

        private final class Flag {
            var value = false
        }

        /// launchctl that never finds the service, with no plist: the install note.
        private struct MissingService: CommandRunner {
            func run(_ executable: String, _ arguments: [String]) async -> CommandOutput {
                CommandOutput(status: 113, output: "Could not find service")
            }
        }

        private static func sampleService() -> ServiceStarter {
            ServiceStarter(
                runner: MissingService(), uid: 501,
                home: URL(fileURLWithPath: "/Users/sam"),
                repoPath: "/Users/sam/Projects/harness", fileExists: { _ in false })
        }

        private struct SilentEvents: EventSource {
            func updates() -> AsyncThrowingStream<EventStreamUpdate, any Error> {
                AsyncThrowingStream { _ in }
            }
        }

        static func render(to folder: URL, only: String? = nil) async throws {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let suite = "local.harness.snapshots"
            let defaults = UserDefaults(suiteName: suite)!
            defaults.removePersistentDomain(forName: suite)
            let model = AppModel(
                api: SampleAPI(), events: SilentEvents(),
                preferences: UserDefaultsStore(defaults: defaults))
            model.app.connection = .connected
            await model.live.refresh()
            model.app.openProject("weather-forecast")
            model.app.openProject("map-viewer")
            model.app.moveProject("weather-forecast", to: 0)
            model.app.selectProject("todo-ui")
            for id in ["c1", "c2", "c3", "c4"] {
                try await model.transcripts.transcript(for: id).load()
                try await model.activity.load(session: id)
            }
            let shell = Shell(model: model, userName: "Sam Rivera")
            let controller = AppController(shell: shell, service: sampleService())
            let workspace = CGSize(width: 828, height: 790)
            if only == "b24" {
                try await renderConveniences(model, shell, controller, folder)
                return
            }
            if only == "b25" {
                try await renderToolsAndPullRequests(model, shell, controller, folder)
                return
            }
            if only == "b13" {
                try await renderSearchAndStuck(model, shell, controller, folder)
                return
            }
            if only == "b26" {
                try await renderModelsGlassAndPanes(model, shell, controller, folder)
                return
            }
            if only == "b27" {
                try await renderGlassThemes(model, shell, controller, folder)
                return
            }
            if only == "b28" {
                try await renderArchiveConnectorsAndPlainFolders(model, shell, controller, folder)
                return
            }
            if only == "b29" {
                try await renderTurnActivity(model, shell, controller, folder)
                return
            }
            if only == "b34" {
                try await renderPixies(model, shell, controller, folder)
                return
            }

            model.app.update("todo-ui") { state in
                state.openChat("c1", in: workspace)
                state.dropChat("c2", onto: "c1", side: .right)
                state.focusPane("c1")
                state.expandedGoals = ["c2"]
                state.expandedAgents = ["c2/toolu_explore"]
            }
            try await snap(controller, "workspace-light", .aqua, folder)
            try await snap(controller, "workspace-dark", .darkAqua, folder)

            model.app.update("todo-ui") { state in
                state.leftCollapsed = true
                state.rightCollapsed = true
            }
            try await snap(controller, "rails-light", .aqua, folder)

            // Selectable transcript text: a selection across paragraphs, open tool output
            // and the Copy buttons that otherwise show on hover.
            model.app.update("todo-ui") { state in
                state.leftCollapsed = false
                state.rightCollapsed = false
                state.layout = WorkspaceLayout()
                state.openChat("c2", in: workspace)
            }
            shell.expandedItems = ["t5"]
            for appearance in [("light", NSAppearance.Name.aqua), ("dark", .darkAqua)] {
                try await snap(
                    controller, "transcript-selection-\(appearance.0)", appearance.1, folder,
                    revealsHoverControls: true
                ) { host in
                    selectAcrossParagraphs(in: host, from: "DOIs link", to: "doi: string")
                }
            }
            shell.expandedItems = []

            // Scrolled up while a message arrives: the view holds still and offers Jump to
            // latest.
            let c2 = model.transcripts.transcript(for: "c2")
            c2.receive(
                sampleMessage(
                    10_000,
                    (1...12).map { "Paragraph \($0) of a long answer that runs past the pane." }
                        .joined(separator: "\n\n")))
            shell.expandedItems = ["t4", "t5"]
            try await snap(controller, "transcript-jump-light", .aqua, folder) { host in
                await scrollUpThenReceive(in: host, transcript: c2)
            }
            try await snap(controller, "transcript-jump-dark", .darkAqua, folder) { host in
                await scrollUpThenReceive(in: host, transcript: c2)
            }
            shell.expandedItems = []

            model.app.update("todo-ui") { state in
                state.leftCollapsed = false
                state.rightCollapsed = false
                state.dropChat("c3", onto: "c1", side: .bottom)
                state.dropChat("c4", onto: "c2", side: .bottom)
                state.openCards = [.agents, .goals]
            }
            try await snap(controller, "four-panes-light", .aqua, folder)
            try await snap(controller, "four-panes-dark", .darkAqua, folder)

            model.app.update("todo-ui") { $0.view = .board }
            try await snap(controller, "board-light", .aqua, folder)
            try await snap(controller, "board-dark", .darkAqua, folder)

            model.app.update("todo-ui") { state in
                state.view = .workspace
                state.layout = WorkspaceLayout()
                state.openCards = Set(RightCard.allCases)
            }
            try await snap(controller, "empty-light", .aqua, folder)

            // B09: approvals, diff review, palette, usage, settings, connectors, pairing.
            try await model.devices.load()
            try await model.approvals.loadDiff(session: "c3")
            model.app.update("todo-ui") { state in
                state.openChat("c1", in: workspace)
                state.openChat("c4", in: workspace)
                state.focusPane("c4")
                state.openCards = [.needsYou]
            }
            try await pair(controller, "needs-you", folder)
            model.app.update("todo-ui") { $0.openCards = Set(RightCard.allCases) }
            let review = model.approvals.pending.first { $0.kind == .review }!
            shell.show(.diff(review.id))
            try await pair(controller, "diff-sheet", folder)
            shell.show(.publish(review.id))
            try await pair(controller, "publish-sheet", folder)
            let form = model.approvals.publishForm(for: review, session: nil)
            _ = try? await model.approvals.publish(review, form)
            try await pair(controller, "publish-failed", folder)
            shell.show(.palette)
            try await pair(controller, "palette", folder)
            shell.palette.search("dark")
            try await snap(controller, "palette-search-light", .aqua, folder)
            shell.show(.usage)
            try await pair(controller, "usage", folder)
            shell.show(.settings)
            try await pair(controller, "settings", folder)
            shell.show(.connectors)
            try await pair(controller, "connectors", folder)
            try await model.devices.createPairingCode()
            shell.show(.settings)
            try await pair(controller, "pairing", folder)

            try await renderClaudeChats(model, shell, controller, folder)
            try await renderBackground(model, shell, controller, folder)
            try await renderUsage(model, shell, controller, folder)
            try await renderConveniences(model, shell, controller, folder)
            try await renderToolsAndPullRequests(model, shell, controller, folder)
            try await renderSearchAndStuck(model, shell, controller, folder)
            try await renderGlassThemes(model, shell, controller, folder)
            try await renderArchiveConnectorsAndPlainFolders(model, shell, controller, folder)
            try await renderTurnActivity(model, shell, controller, folder)
            try await renderExchangeBar(model, shell, controller, folder)
        }

        /// B34: the Pixies tab empty and with every pixie hidden, then Reviewer's chat, its
        /// details, and the Soul and Memory pages.
        private static func renderPixies(
            _ model: AppModel, _ shell: Shell, _ controller: AppController, _ folder: URL
        ) async throws {
            shell.close()
            // The empty tab: the sample pixies are removed for this shot only.
            for pixie in model.pixies.pixies {
                try await model.pixies.delete(pixie.id)
            }
            shell.openPixies()
            try await pair(controller, "pixies-empty", folder)

            (model.api as? SampleAPI)?.restorePixies()
            try await model.pixies.load()
            // Every pixie hidden: the tab offers to show them.
            for pixie in model.pixies.pixies {
                try await model.pixies.update(pixie.id, UpdatePixieRequest(hidden: true))
            }
            shell.selectPixie(nil)
            try await pair(controller, "pixies-all-hidden", folder)
            shell.showsHiddenPixies = true
            try await pair(controller, "pixies-hidden-shown", folder)
            shell.showsHiddenPixies = false
            (model.api as? SampleAPI)?.restorePixies()
            try await model.pixies.load()
            // Watcher's chat runs; live events would have brought it.
            try await model.sessions.fetch("p2")
            shell.selectPixie("reviewer")
            shell.pixieDetailsOpen = false
            try await pair(controller, "pixie-chat", folder)
            shell.pixieDetailsOpen = true
            try await pair(controller, "pixie-details", folder)
            shell.pixiePanel = .soul
            try await pair(controller, "pixie-details-soul", folder)
            shell.pixiePanel = .memory
            try await pair(controller, "pixie-details-memory", folder)
        }

        /// B29: a running turn with its timer, thinking, a running agents group and a
        /// running group of commands beside a finished turn that says how long it worked;
        /// then the thinking and the commands group open.
        private static func renderTurnActivity(
            _ model: AppModel, _ shell: Shell, _ controller: AppController, _ folder: URL
        ) async throws {
            shell.close()
            let workspace = CGSize(width: 828, height: 790)
            let start = Date().addingTimeInterval(-74)
            var id = 20_000
            func receive(_ session: String, _ type: String, _ payload: [String: Any], at: Date) {
                id += 1
                let event: Event = try! SampleData.decode([
                    "id": id, "type": type, "ts": SampleData.iso(at), "session_id": session,
                    "payload": payload,
                ])
                model.transcripts.receive(event)
            }
            func blocks(_ list: [[String: Any]]) -> [String: Any] {
                ["blocks": list, "parent_tool_use_id": NSNull()]
            }
            func use(_ tool: String, _ name: String, _ input: [String: Any]) -> [String: Any] {
                ["type": "tool_use", "id": tool, "name": name, "input": input]
            }
            func result(_ tool: String, _ content: String) -> [String: Any] {
                ["type": "tool_result", "tool_use_id": tool, "content": content]
            }

            // c2 runs: its first turn ends, then a new one thinks, starts three agents
            // and runs a few commands.
            let ended: [String: Any] = [
                "is_error": false, "subtype": "success", "duration_ms": 95_000, "num_turns": 6,
                "cost_usd": NSNull(), "errors": [],
            ]
            receive("c2", "session.result", ended, at: start - 5)
            receive(
                "c2", "session.user_message", ["text": "Add DOI links", "attachments": []],
                at: start)
            let thinking =
                "The DOI field is missing on a few entries. Check which ones first, then add the links and rerun the snapshot test."
            receive(
                "c2", "session.message",
                blocks([["type": "thinking", "text": thinking, "duration_ms": 8_400]]),
                at: start + 9)
            receive(
                "c2", "session.message",
                blocks([["type": "text", "text": "Checking the entries in parallel."]]),
                at: start + 10)
            for (index, year) in ["2026", "2025", "2024"].enumerated() {
                receive(
                    "c2", "session.message",
                    blocks([
                        use(
                            "ag\(index)", "Agent",
                            ["subagent_type": "Explore", "description": "DOIs of \(year)"])
                    ]),
                    at: start + 11)
            }
            receive(
                "c2", "session.message",
                blocks([result("ag0", "6 DOIs"), result("ag1", "5 DOIs")]), at: start + 30)
            receive(
                "c2", "session.message",
                blocks([
                    ["type": "text", "text": "Two years are done. Wiring the links meanwhile."]
                ]),
                at: start + 31)
            receive(
                "c2", "session.message",
                blocks([use("b1", "Read", ["file_path": "lib/bibtex.ts"])]),
                at: start + 32)
            receive(
                "c2", "session.message", blocks([result("b1", "export function parseBib() {}")]),
                at: start + 33)
            receive(
                "c2", "session.message", blocks([use("b2", "Bash", ["command": "npm run lint"])]),
                at: start + 34)
            receive("c2", "session.message", blocks([result("b2", "no problems")]), at: start + 40)
            receive(
                "c2", "session.message",
                blocks([use("b3", "Bash", ["command": "npm test -- publications"])]),
                at: start + 41)

            // c3 finished: its turn says how long it worked.
            receive(
                "c3", "session.result",
                [
                    "is_error": false, "subtype": "success", "duration_ms": 72_400, "num_turns": 4,
                    "cost_usd": NSNull(), "errors": [],
                ], at: Date())

            // The plain-folder snapshots before this left recipes in front.
            model.app.selectProject("todo-ui")
            model.app.update("todo-ui") { state in
                state.layout = WorkspaceLayout()
                state.leftCollapsed = false
                state.rightCollapsed = true
                state.expandedBackground = []
                state.openChat("c2", in: workspace)
                state.openChat("c3", in: workspace)
                state.focusPane("c2")
            }
            try await pair(controller, "b29-turn-activity", folder)

            shell.expandedItems.formUnion(["e20003-0", "tools-b1", "tools-ag0"])
            try await pair(controller, "b29-turn-activity-open", folder)
            shell.expandedItems.subtract(["e20003-0", "tools-b1", "tools-ag0"])
        }

        /// B29: the background bar counts the current exchange only. c3's earlier turn
        /// finished four tasks; the user's next message started three agents and one is
        /// done, so the bar reads "2 running · 1 completed".
        private static func renderExchangeBar(
            _ model: AppModel, _ shell: Shell, _ controller: AppController, _ folder: URL
        ) async throws {
            shell.close()
            let workspace = CGSize(width: 828, height: 790)
            let now = Date()
            var id = 21_000
            func event(_ type: String, _ payload: [String: Any], at: Date) -> Event {
                id += 1
                return try! SampleData.decode([
                    "id": id, "type": type, "ts": SampleData.iso(at), "session_id": "c3",
                    "payload": payload,
                ])
            }
            func item(
                _ tool: String, _ kind: String, _ name: String, _ description: String,
                started: Double, finished: Double? = nil
            ) -> [String: Any] {
                [
                    "id": tool, "kind": kind, "name": name, "description": description,
                    "status": finished == nil ? "running" : "done",
                    "started_at": SampleData.iso(now.addingTimeInterval(-started)),
                    "finished_at": finished.map { SampleData.iso(now.addingTimeInterval(-$0)) }
                        ?? NSNull(),
                ]
            }
            let years = ["2026", "2025", "2024"]
            let calls: [[String: Any]] = years.enumerated().map { index, year in
                [
                    "type": "tool_use", "id": "cx\(index)", "name": "Agent",
                    "input": [
                        "subagent_type": "Explore", "description": "Contrast on \(year) pages",
                    ],
                ]
            }
            let background: [[String: Any]] = [
                item(
                    "toolu_find", "agent", "Explore", "Find theme toggles", started: 560,
                    finished: 540),
                item(
                    "toolu_css", "agent", "general-purpose", "Audit CSS variables", started: 550,
                    finished: 500),
                item(
                    "toolu_lint", "bash", "npm run lint", "Lint the styles", started: 480,
                    finished: 470),
                item(
                    "toolu_tests", "bash", "npm test -- theme", "Theme tests", started: 460,
                    finished: 430),
                item(
                    "cx0", "agent", "Explore", "Contrast on 2026 pages", started: 80, finished: 30),
                item("cx1", "agent", "Explore", "Contrast on 2025 pages", started: 80),
                item("cx2", "agent", "Explore", "Contrast on 2024 pages", started: 80),
            ]
            let events = [
                event(
                    "session.user_message",
                    ["text": "Now check the contrast on every page", "attachments": []],
                    at: now - 90),
                event(
                    "session.state", ["state": "running", "error": NSNull(), "turn_start": true],
                    at: now - 89),
                event(
                    "session.message", ["blocks": calls, "parent_tool_use_id": NSNull()],
                    at: now - 80),
                event(
                    "session.message",
                    [
                        "blocks": [
                            ["type": "tool_result", "tool_use_id": "cx0", "content": "All pass"]
                        ],
                        "parent_tool_use_id": NSNull(),
                    ], at: now - 30),
            ]
            events.forEach(model.transcripts.receive)
            let agents = event(
                "session.agents",
                [
                    "agents": [],
                    "background": ["running": 2, "completed": 5, "items": background],
                ], at: now - 30)
            // Opening the pane loads the sample detail again; the live snapshot follows it.
            let follow: (NSView) async -> Void = { _ in
                model.activity.apply(agents)
                try? await Task.sleep(for: .milliseconds(200))
            }

            model.app.selectProject("todo-ui")
            model.app.update("todo-ui") { state in
                state.layout = WorkspaceLayout()
                state.leftCollapsed = false
                state.rightCollapsed = true
                state.expandedBackground = []
                state.openChat("c3", in: workspace)
                state.focusPane("c3")
            }
            try await pair(controller, "b29-exchange-bar", folder, prepare: follow)
            model.app.update("todo-ui") { $0.expandedBackground = ["c3"] }
            try await pair(controller, "b29-exchange-bar-expanded", folder, prepare: follow)
            model.app.update("todo-ui") { $0.expandedBackground = [] }
        }

        /// B28: an archived Claude Code chat in the open Archived group, the Claude Code
        /// row's menu, the Connectors sheet folded and with a group open, and a plain
        /// folder's toolbar with Init and the chat it prefills.
        private static func renderArchiveConnectorsAndPlainFolders(
            _ model: AppModel, _ shell: Shell, _ controller: AppController, _ folder: URL
        ) async throws {
            shell.close()
            let workspace = CGSize(width: 828, height: 790)
            model.app.selectProject("todo-ui")
            model.app.update("todo-ui") { state in
                state.view = .workspace
                state.leftCollapsed = false
                state.layout = WorkspaceLayout()
                state.openChat("c1", in: workspace)
            }
            try await model.claudeChats.setArchived("cc-next", true)
            shell.archivedOpen.insert("todo-ui")
            try await pair(controller, "b28-sidebar-archived", folder)
            try await pair(controller, "b28-claude-row-menu", folder, revealsHoverControls: true)
            for chat in ["cc-pipeline", "cc-next"] {
                let archived = model.claudeChats.chat(chat)?.archived ?? false
                try await pairView(
                    MenuPreview(
                        title: model.claudeChats.chat(chat)?.title ?? chat,
                        rows: [
                            MenuPreview.Row(title: "Open"),
                            MenuPreview.Row(title: "Continue in harness"),
                            MenuPreview.Row(title: archived ? "Unarchive" : "Archive"),
                        ]
                    ).frame(width: 260), "b28-claude-menu-\(archived ? "archived" : "idle")",
                    folder)
            }
            shell.archivedOpen.remove("todo-ui")

            shell.connectorGroupsOpen = []
            shell.show(.connectors)
            try await pair(controller, "b28-connectors-folded", folder)
            shell.connectorGroupsOpen = [.claudeCode]
            try await pair(controller, "b28-connectors-open", folder)
            shell.close()

            model.app.openProject("recipes")
            try await pair(controller, "b28-plain-folder", folder)
            shell.setUpGit()
            try await pair(controller, "b28-init-chat", folder)
        }

        /// B27: every glass theme in light and dark over the sample desktop, two chats side
        /// by side with the ocean accent, and the Settings sheet with its Glass row.
        private static func renderGlassThemes(
            _ model: AppModel, _ shell: Shell, _ controller: AppController, _ folder: URL
        ) async throws {
            shell.close()
            let workspace = CGSize(width: 828, height: 790)
            for id in ["c1", "c2"] {
                try await model.transcripts.transcript(for: id).load()
            }
            model.app.update("todo-ui") { state in
                state.view = .workspace
                state.layout = WorkspaceLayout()
                state.leftCollapsed = false
                state.rightCollapsed = false
                state.openCards = [.needsYou]
                state.openChat("c1", in: workspace)
                state.openChat("c2", in: workspace)
                state.focusPane("c1")
            }
            let accent = shell.settings.accent
            shell.settings.accent = .ocean
            for style in DesignTokens.GlassTheme.all {
                shell.settings.glass = style
                try await pair(controller, "b27-glass-\(style.name)", folder)
            }
            shell.settings.accent = accent
            for style in [DesignTokens.GlassTheme.clear, DesignTokens.GlassTheme.smoke] {
                shell.settings.glass = style
                shell.show(.settings)
                try await pair(controller, "b27-settings-\(style.name)", folder)
                shell.close()
            }
            shell.settings.glass = DesignTokens.GlassTheme.default
            try await renderPaneWidths(model, shell, controller, folder)
        }

        /// Panes at the widths a 1440 by 900 window with both side panels gives them: two
        /// side by side, three, four (one a browser), and one at the 280 point minimum,
        /// in Clear light and Smoke dark. Nothing may spill out of its pane.
        private static func renderPaneWidths(
            _ model: AppModel, _ shell: Shell, _ controller: AppController, _ folder: URL
        ) async throws {
            let workspace = CGSize(width: 828, height: 790)
            for id in ["c1", "c2", "c3", "c4"] {
                try await model.transcripts.transcript(for: id).load()
            }
            BrowserSession.sampleHTML = samplePage
            let browser = ToolPane.browser(url: "http://localhost:3000/")
            let layouts: [(String, (inout ProjectState) -> Void)] = [
                (
                    "two",
                    { state in
                        state.openChat("c1", in: workspace)
                        state.openChat("c2", in: workspace)
                    }
                ),
                (
                    "three",
                    { state in
                        for id in ["c1", "c2", "c3"] {
                            state.openChat(id, in: workspace)
                        }
                    }
                ),
                (
                    "four",
                    { state in
                        for id in ["c1", "c2", "c3"] {
                            state.openChat(id, in: workspace)
                        }
                        state.openTool(browser, in: workspace)
                    }
                ),
                (
                    "narrow",
                    { state in
                        state.openChat("c1", in: workspace)
                        state.openChat("c2", in: workspace)
                        if let gutter = state.layout.gutterFrames(in: workspace).first {
                            state.layout.resize(split: gutter.split, ratio: 0, in: workspace)
                        }
                    }
                ),
            ]
            for (name, arrange) in layouts {
                model.app.update("todo-ui") { state in
                    state.view = .workspace
                    state.layout = WorkspaceLayout()
                    state.leftCollapsed = false
                    state.rightCollapsed = false
                    state.openCards = [.needsYou]
                    arrange(&state)
                    state.focusPane("c1")
                }
                shell.syncTools()
                if name == "four" {
                    let page = shell.tools.browser(for: browser) { _ in }
                    await waitUntil { page.url != nil && !page.isLoading }
                }
                let frames = shell.projectState.layout.paneFrames(in: workspace)
                print("\(name): \(frames.map { "\($0.chat) \(Int($0.frame.width))" })")
                for (style, suffix, appearance) in [
                    (DesignTokens.GlassTheme.clear, "clear-light", NSAppearance.Name.aqua),
                    (DesignTokens.GlassTheme.smoke, "smoke-dark", .darkAqua),
                ] {
                    shell.settings.glass = style
                    try await snap(controller, "b27-panes-\(name)-\(suffix)", appearance, folder)
                }
            }
            shell.settings.glass = DesignTokens.GlassTheme.default
        }

        /// B26: the model list and thinking levels as the menus show them, Settings' agent
        /// defaults and account, the account row, a new chat starting from the defaults,
        /// the see-through window over a sample desktop, and a
        /// browser pane beside two chats with a check that it stays inside its slot.
        private static func renderModelsGlassAndPanes(
            _ model: AppModel, _ shell: Shell, _ controller: AppController, _ folder: URL
        ) async throws {
            shell.close()
            let agents = model.agents
            print("models: \(agents.models.map(\.value)), defaults: \(agents.current)")
            try await pairView(
                MenuPreview(
                    title: "Model",
                    rows: agents.models.map { info in
                        MenuPreview.Row(
                            title: info.displayName, detail: info.description,
                            checked: agents.isSelected(info, current: "opus"))
                    }
                ).frame(width: 340), "b26-model-menu", folder)
            for (value, name) in [("opus", "opus"), ("haiku", "haiku")] {
                let levels = agents.thinkingLevels(for: value)
                let rows =
                    levels.isEmpty
                    ? [MenuPreview.Row(title: "Not available for this model", disabled: true)]
                    : levels.map { MenuPreview.Row(title: $0.label, checked: $0 == .high) }
                try await pairView(
                    MenuPreview(title: "Thinking", rows: rows).frame(width: 240),
                    "b26-thinking-\(name)", folder)
            }
            try await pairView(
                VStack(alignment: .leading, spacing: 0) {
                    AgentDefaultsSection()
                    AccountSection()
                }
                .padding(.horizontal, 22)
                .padding(.bottom, 12)
                .frame(width: 580)
                .environment(shell), "b26-settings-agents", folder)
            try await pairView(
                AccountRow().frame(width: 248).padding(10).environment(shell),
                "b26-account-row", folder)

            // A new chat: the composer starts from the shared defaults.
            let workspace = CGSize(width: 828, height: 790)
            model.app.update("todo-ui") { state in
                state.view = .workspace
                state.layout = WorkspaceLayout()
                state.leftCollapsed = false
                state.rightCollapsed = false
                state.openCards = [.needsYou]
            }
            shell.newChat()
            try await pair(controller, "b26-new-chat-desktop", folder)

            // The see-through window over a busy desktop.
            for id in ["c1", "c2"] {
                try await model.transcripts.transcript(for: id).load()
            }
            model.app.update("todo-ui") { state in
                state.layout = WorkspaceLayout()
                state.openChat("c1", in: workspace)
                state.openChat("c2", in: workspace)
                state.focusPane("c1")
            }
            try await pair(controller, "b26-glass-desktop", folder)
            shell.show(.settings)
            try await pair(controller, "b26-settings-sheet", folder)
            shell.close()

            // A browser pane beside two chats stays in its slot (regression).
            BrowserSession.sampleHTML = samplePage
            let browser = ToolPane.browser(url: "http://localhost:3000/")
            model.app.update("todo-ui") { state in
                state.layout = WorkspaceLayout()
                state.openChat("c1", in: workspace)
                state.openChat("c2", in: workspace)
                state.openTool(browser, in: workspace)
                state.focusPane("c1")
            }
            shell.syncTools()
            let page = shell.tools.browser(for: browser) { _ in }
            await waitUntil { page.url != nil && !page.isLoading }
            for appearance in [("light", NSAppearance.Name.aqua), ("dark", .darkAqua)] {
                try await snap(
                    controller, "b26-browser-beside-chats-\(appearance.0)", appearance.1, folder
                ) { host in
                    checkPlatformViewsStayInPanes(in: host)
                }
            }
            // Another pane maximized: the browser must neither show nor take clicks.
            model.app.update("todo-ui") { $0.layout.toggleMaximize("c1") }
            try await snap(controller, "b26-browser-under-maximized-light", .aqua, folder) { host in
                checkPlatformViewsStayInPanes(in: host)
            }
            model.app.update("todo-ui") { $0.layout.toggleMaximize("c1") }
        }

        /// Prints whether each web view and terminal lies inside its pane's container and
        /// clear of every chat transcript.
        private static func checkPlatformViewsStayInPanes(in host: NSView) {
            let chats = textViews(in: host).compactMap { $0.enclosingScrollView }
                .map { $0.convert($0.bounds, to: host) }
            let platform: [NSView] = webViews(in: host) + terminalViews(in: host)
            var failures: [String] = []
            for view in platform {
                // Only a hidden view is out of the way: a transparent one still takes
                // clicks.
                if view.isHiddenOrHasHiddenAncestor {
                    continue
                }
                let rect = view.convert(view.bounds, to: host)
                guard let container = view.superview as? PaneContentView else {
                    failures.append("\(type(of: view)) outside a pane container")
                    continue
                }
                let slot = container.convert(container.bounds, to: host)
                if !slot.insetBy(dx: -0.5, dy: -0.5).contains(rect) {
                    failures.append("\(type(of: view)) \(rect) leaves its slot \(slot)")
                }
                if !container.clipsToBounds {
                    failures.append("pane container does not clip")
                }
                for chat in chats where chat.intersects(rect) {
                    failures.append("\(type(of: view)) \(rect) covers a chat at \(chat)")
                }
            }
            print(
                "pane bounds check: \(platform.count) platform views, \(chats.count) chat transcripts, "
                    + (failures.isEmpty ? "ok" : "FAILED \(failures)"))
        }

        /// B13 and B14: message hits in the palette (and while the history is indexed), a
        /// long transcript opened at a hit with its page loaded and the message glowing, a
        /// stuck chat's badges and Needs you card, and Settings' Stuck chats section.
        private static func renderSearchAndStuck(
            _ model: AppModel, _ shell: Shell, _ controller: AppController, _ folder: URL
        ) async throws {
            shell.close()
            let workspace = CGSize(width: 828, height: 790)
            let sample = model.api as? SampleAPI
            model.app.openProject("map-viewer")
            model.app.update("map-viewer") { state in
                state.view = .workspace
                state.layout = WorkspaceLayout()
                state.leftCollapsed = false
                state.rightCollapsed = false
                state.openCards = [.needsYou]
            }
            shell.show(.palette)
            shell.searchPalette("retry")
            await waitUntil { !shell.palette.messages.isEmpty }
            try await pair(controller, "b13-palette-messages", folder)
            sample?.setSearchIndexing(true)
            shell.searchPalette("backoff")
            await waitUntil { shell.palette.indexing }
            try await snap(controller, "b13-palette-indexing-light", .aqua, folder)
            sample?.setSearchIndexing(false)

            // The hit in the middle of h2's 240 events: the page around it loads.
            let hit = try await model.api.search(query: "429", repo: nil, limit: 5).hits
                .first { $0.sessionID == "h2" }!
            shell.run(.openMessage(project: hit.repo, pane: hit.pane, event: hit.eventID))
            for appearance in [("light", NSAppearance.Name.aqua), ("dark", .darkAqua)] {
                model.transcripts.transcript(for: "h2").requestFocus(event: hit.eventID!)
                try await snap(
                    controller, "b13-transcript-hit-\(appearance.0)", appearance.1, folder)
            }
            let h2 = model.transcripts.transcript(for: "h2")
            print("h2 page: \(h2.items.count) items, older \(h2.hasOlder), newer \(h2.hasNewer)")

            try await model.transcripts.transcript(for: "h1").load()
            try await model.activity.load(session: "h1")
            model.app.update("map-viewer") { state in
                state.layout = WorkspaceLayout()
                state.openChat("h1", in: workspace)
                state.openCards = [.needsYou]
            }
            try await pair(controller, "b14-stuck", folder)
            try await model.stuck.load()
            try await pairView(
                VStack(alignment: .leading, spacing: 0) {
                    StuckSection()
                    NotificationsSection()
                }
                .padding(.horizontal, 22)
                .padding(.bottom, 12)
                .frame(width: 580)
                .environment(shell), "b14-settings", folder)
            model.app.selectProject("todo-ui")
        }

        /// B25 and B12: a terminal with a sample session, a browser on a local page and an
        /// empty one listing local servers, four panes mixing chats, a terminal and a
        /// browser, the pull request chip and its details, the merge and checks failed
        /// cards, and the Board's chips.
        private static func renderToolsAndPullRequests(
            _ model: AppModel, _ shell: Shell, _ controller: AppController, _ folder: URL
        ) async throws {
            shell.close()
            TerminalSession.startsShells = false
            BrowserSession.sampleHTML = samplePage
            BrowserSession.scan = {
                [
                    LocalServer(port: 3000, process: "node"),
                    LocalServer(port: 5173, process: "node"),
                    LocalServer(port: 8000, process: "Python"),
                ]
            }
            let workspace = CGSize(width: 828, height: 790)
            let path = "/Users/me/Projects/todo-ui"
            for id in ["c1", "c6", "c9"] {
                try await model.transcripts.transcript(for: id).load()
                try await model.activity.load(session: id)
            }
            let terminal = ToolPane.terminal(in: path)
            let browser = ToolPane.browser(url: "http://localhost:3000/")
            model.app.update("todo-ui") { state in
                state.view = .workspace
                state.layout = WorkspaceLayout()
                state.leftCollapsed = false
                state.rightCollapsed = false
                state.openCards = [.needsYou]
                state.openChat("c6", in: workspace)
                state.openTool(terminal, in: workspace)
            }
            shell.syncTools()
            let session = shell.tools.terminal(for: terminal)
            try await pair(controller, "b25-terminal", folder) { _ in
                session.view.feed(text: sampleTerminal)
                try? await Task.sleep(for: .milliseconds(300))
            }

            model.app.update("todo-ui") { state in
                state.closePane(terminal.id)
                state.openTool(browser, in: workspace)
            }
            shell.syncTools()
            let page = shell.tools.browser(for: browser) { _ in }
            await waitUntil { page.url != nil && !page.isLoading }
            try await pair(controller, "b25-browser", folder)

            let empty = ToolPane.browser()
            model.app.update("todo-ui") { state in
                state.closePane(browser.id)
                state.openTool(empty, in: workspace)
            }
            try await pair(controller, "b25-browser-empty", folder)

            // Four panes: two chats, a terminal and a browser.
            let terminal2 = ToolPane.terminal(in: path)
            let browser2 = ToolPane.browser(url: "http://localhost:3000/")
            model.app.update("todo-ui") { state in
                state.layout = WorkspaceLayout()
                state.openChat("c6", in: workspace)
                state.openTool(browser2, in: workspace)
                state.openChat("c9", in: workspace)
                state.openTool(terminal2, in: workspace)
                state.focusPane("c6")
                state.openCards = [.needsYou]
            }
            shell.syncTools()
            let session2 = shell.tools.terminal(for: terminal2)
            let page2 = shell.tools.browser(for: browser2) { _ in }
            await waitUntil { page2.url != nil && !page2.isLoading }
            try await pair(controller, "b25-four-panes", folder) { _ in
                session2.view.feed(text: sampleTerminal)

                try? await Task.sleep(for: .milliseconds(300))
            }

            let c6 = try await model.api.session("c6")
            try await pairView(
                PRDetails(session: "c6", pr: c6.pr!).environment(shell), "b25-pr-popover",
                folder)
            try await pairView(
                LocalServerList(session: page2) {}.frame(width: 260).padding(8)
                    .environment(shell), "b25-local-servers", folder)

            // Needs you with the merge card and the checks failed card only.
            for approval in model.approvals.pending where approval.kind != .merge {
                var resolved = approval
                resolved.status = .resolved
                model.approvals.apply(.approvalResolved(resolved))
            }
            model.app.update("todo-ui") { state in
                state.layout = WorkspaceLayout()
                state.openChat("c9", in: workspace)
                state.openChat("c6", in: workspace)
                state.focusPane("c6")
                state.openCards = [.needsYou]
            }
            try await pair(controller, "b25-merge-and-checks", folder)
            model.app.update("todo-ui") { $0.view = .board }
            try await pair(controller, "b25-board", folder)
            model.app.update("todo-ui") { $0.view = .workspace }
        }

        /// A menu's content drawn as a list, since snapshots cannot capture open menus.
        private struct MenuPreview: View {
            struct Row {
                var title: String
                var detail = ""
                var checked = false
                var disabled = false
            }

            let title: String
            let rows: [Row]

            var body: some View {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 4)
                    ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                            Image(systemName: "checkmark")
                                .font(.system(size: 11, weight: .semibold))
                                .opacity(row.checked ? 1 : 0)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(row.title).font(.system(size: 13))
                                if !row.detail.isEmpty {
                                    Text(row.detail)
                                        .font(.system(size: 11))
                                        .foregroundStyle(.secondary)
                                }
                            }
                            Spacer(minLength: 0)
                        }
                        .foregroundStyle(row.disabled ? .tertiary : .primary)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 3)
                    }
                }
                .padding(.vertical, 6)
            }
        }

        /// A full reset first, so the dark snapshot does not repeat the light one's output.
        private static let sampleTerminal =
            "\u{1B}c"
            + [
                "Last login: Tue Oct  7 09:12:03 on ttys004",
                "\u{1B}[1;32mme@air\u{1B}[0m \u{1B}[1;34mtodo-ui\u{1B}[0m % npm run dev",
                "",
                "> todo-ui@1.4.0 dev",
                "> next dev",
                "",
                "   \u{1B}[1mNext.js 16.0.1\u{1B}[0m",
                "   - Local:        \u{1B}[36mhttp://localhost:3000\u{1B}[0m",
                "",
                " \u{1B}[32m✓\u{1B}[0m Ready in 1.2s",
                "\u{1B}[1;32mme@air\u{1B}[0m \u{1B}[1;34mtodo-ui\u{1B}[0m % git status --short",
                " \u{1B}[31mM\u{1B}[0m app/about/page.tsx",
                " \u{1B}[31mM\u{1B}[0m content/about.md",
                "\u{1B}[1;32mme@air\u{1B}[0m \u{1B}[1;34mtodo-ui\u{1B}[0m % ",
            ].joined(separator: "\r\n")

        private static let samplePage = """
            <!doctype html><html><head><meta charset="utf-8"><style>
            body { font: 15px -apple-system, sans-serif; margin: 0; color: #1d1d1f; background: #fafaf8; }
            header { padding: 28px 36px; background: #20242c; color: #fff; }
            header h1 { margin: 0 0 4px; font-size: 26px; } header p { margin: 0; opacity: .7; }
            nav { display: flex; gap: 18px; padding: 12px 36px; border-bottom: 1px solid #e5e5e0; }
            nav a { color: #3a5a8c; text-decoration: none; font-weight: 600; }
            main { padding: 20px 36px; max-width: 640px; line-height: 1.55; }
            .card { background: #fff; border: 1px solid #e5e5e0; border-radius: 12px; padding: 14px 16px; margin: 12px 0; }
            </style></head><body>
            <header><h1>Sam Rivera</h1><p>Engineer</p></header>
            <nav><a>About</a><a>Publications</a><a>Projects</a><a>Contact</a></nav>
            <main><h2>About</h2><p>I build tools for language models and the people who use them.
            Lately: agent orchestration, evaluation, and small, careful interfaces.</p>
            <div class="card"><b>Latest paper</b><br>Measuring tool use in long-running agents (2026)</div>
            <div class="card"><b>Now</b><br>Writing a personal agent manager for my own repos.</div>
            </main></body></html>
            """

        /// B24: slash command and file suggestions above the composer, the plan card inline
        /// and in Needs you, the context meter (amber above 80%), queued messages with the
        /// Queue and Interrupt buttons, and Copy and Run in terminal on shell commands.
        private static func renderConveniences(
            _ model: AppModel, _ shell: Shell, _ controller: AppController, _ folder: URL
        ) async throws {
            shell.close()
            let workspace = CGSize(width: 828, height: 790)
            for id in ["c1", "c2", "c3", "c8"] {
                try await model.transcripts.transcript(for: id).load()
                try await model.activity.load(session: id)
            }
            model.app.update("todo-ui") { state in
                state.view = .workspace
                state.layout = WorkspaceLayout()
                state.leftCollapsed = false
                state.rightCollapsed = false
                state.openCards = [.needsYou]
                state.expandedBackground = []
                state.openChat("c1", in: workspace)
                state.openChat("c2", in: workspace)
                state.focusPane("c1")
            }
            let c1 = shell.draft(for: "c1")
            c1.replaceText("/co", caret: 3)
            try await pair(controller, "b24-commands", folder, revealsHoverControls: true)
            c1.replaceText("Check @comp", caret: 11)
            try await pair(controller, "b24-files", folder, revealsHoverControls: true)
            c1.clear()

            model.app.update("todo-ui") { state in
                state.layout = WorkspaceLayout()
                state.openCards = [.needsYou]
                state.openChat("c3", in: workspace)
                state.focusPane("c3")
            }
            try await pair(controller, "b24-code-blocks", folder)

            // c2 runs with two messages queued; typing turns its send button into Queue.
            shell.draft(for: "c2").text = "Also link the PDFs"
            model.app.update("todo-ui") { state in
                state.layout = WorkspaceLayout()
                state.openChat("c8", in: workspace)
                state.openChat("c2", in: workspace)
                state.focusPane("c8")
            }
            // Only the plan left in Needs you, so the panel shows its card too.
            for approval in model.approvals.pending where approval.kind != .plan {
                var resolved = approval
                resolved.status = .resolved
                model.approvals.apply(.approvalResolved(resolved))
            }
            try await pair(controller, "b24-plan-queued", folder)
            shell.draft(for: "c2").clear()

        }

        /// B23: the usage button and popover with numbers 25 minutes old (dimmed), after a
        /// Refresh (fresh), a second Refresh refused as too soon, and Settings' Usage section.
        private static func renderUsage(
            _ model: AppModel, _ shell: Shell, _ controller: AppController, _ folder: URL
        ) async throws {
            shell.close()
            try await model.usage.load()
            shell.show(.usage)
            try await pair(controller, "usage-stale", folder)
            await model.usage.refresh()
            try await pair(controller, "usage-fresh", folder)
            // Each snapshot takes seconds; refuse a refresh right before each one.
            for appearance in [("light", NSAppearance.Name.aqua), ("dark", .darkAqua)] {
                await model.usage.refresh()
                try await snap(controller, "usage-retry-\(appearance.0)", appearance.1, folder)
            }
            model.devices.clearPairingCode()
            shell.show(.settings)
            try await pair(controller, "settings-usage", folder)
            shell.close()
        }

        /// B22 and I-003: the background bar above the composer, collapsed and open, an
        /// idle chat with a running command in the Agents card, and the banner offering to
        /// start the daemon's service, then showing how to install it.
        private static func renderBackground(
            _ model: AppModel, _ shell: Shell, _ controller: AppController, _ folder: URL
        ) async throws {
            shell.close()
            let workspace = CGSize(width: 828, height: 790)
            model.app.update("todo-ui") { state in
                state.layout = WorkspaceLayout()
                state.leftCollapsed = false
                state.rightCollapsed = false
                state.openCards = [.agents, .goals]
                state.expandedAgents = []
                state.openChat("c2", in: workspace)
                state.openChat("c3", in: workspace)
                state.focusPane("c2")
            }
            try await pair(controller, "background-bar", folder)
            model.app.update("todo-ui") { $0.expandedBackground = ["c2", "c3"] }
            try await pair(controller, "background-bar-expanded", folder)
            model.app.update("todo-ui") { $0.expandedBackground = [] }

            model.app.connection = .reconnecting(attempt: 3, delay: 8)
            try await pair(controller, "service-offer", folder)
            await controller.service.start()
            try await pair(controller, "service-install", folder)
            model.app.connection = .connected
        }

        /// B21: Claude Code chats in the sidebar, a read-only history with Continue in
        /// harness, a send refused while Claude Code has the chat open, and dictation's
        /// volatile text in a composer.
        private static func renderClaudeChats(
            _ model: AppModel, _ shell: Shell, _ controller: AppController, _ folder: URL
        ) async throws {
            shell.close()
            let workspace = CGSize(width: 828, height: 790)
            let hero = try await model.api.claudeChat("cc-hero").paneID
            try await model.transcripts.transcript(for: hero).load()
            model.app.update("todo-ui") { state in
                state.layout = WorkspaceLayout()
                state.openCards = Set(RightCard.allCases)
                state.openChat("c1", in: workspace)
                state.openChat(hero, in: workspace)
            }
            try await pair(controller, "claude-chat-pane", folder)

            try await model.claudeChats.setShowAutomated(true)
            shell.show(.settings)
            try await snap(controller, "claude-chats-automated-light", .aqua, folder)
            shell.close()

            model.app.update("todo-ui") { $0.leftCollapsed = true }
            try await snap(controller, "claude-chats-rail-light", .aqua, folder)
            model.app.update("todo-ui") { $0.leftCollapsed = false }
            try await model.claudeChats.setShowAutomated(false)

            shell.continueInHarness(hero)
            let adopted = "adopted-cc-hero"
            await waitUntil { model.app.state(of: "todo-ui").layout.contains(adopted) }
            try await model.transcripts.transcript(for: adopted).load()
            let draft = shell.draft(for: adopted)
            draft.text = "Also check the About page portrait"
            shell.send(adopted)
            await waitUntil { draft.blocked != nil }
            try await pair(controller, "blocked-send", folder)

            let dictating = shell.draft(for: "c1")
            dictating.text = "Use the shared zod schema in"
            dictating.volatile = " the contact route and show inline err"
            try await pair(controller, "dictation-volatile", folder)
        }

        private static func waitUntil(_ condition: () -> Bool) async {
            for _ in 0..<200 where !condition() {
                try? await Task.sleep(for: .milliseconds(10))
            }
            if !condition() {
                print("snapshot state did not settle")
            }
        }

        /// The real daemon's data in the B09 sheets; only reads.
        static func renderLive(to folder: URL) async throws {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            guard let model = try AppModel.local() else {
                print("no device token")
                return
            }
            model.app.connection = .connected
            await model.live.refresh()
            try await model.devices.load()
            print("repos: \(model.app.repos.map(\.name)), open: \(model.app.openProjects)")
            print(
                "sessions: \(model.sessions.sessions.count), pending: \(model.approvals.pending.count)"
            )
            print(
                "connectors: \(model.connectors.connectors.count), devices: \(model.devices.devices.map(\.name))"
            )
            print(
                "limits: \(String(describing: model.usage.limits)), month tokens: \(model.usage.totalTokens)"
            )
            let shell = Shell(model: model)
            let controller = AppController(shell: shell, service: sampleService())
            try await snap(controller, "live-workspace", .aqua, folder)
            shell.show(.palette)
            print("palette entries: \(shell.palette.items.count)")
            try await snap(controller, "live-palette", .aqua, folder)
            shell.show(.usage)
            try await snap(controller, "live-usage", .darkAqua, folder)
            shell.show(.settings)
            try await snap(controller, "live-settings", .aqua, folder)
            shell.show(.connectors)
            try await snap(controller, "live-connectors", .darkAqua, folder)
        }

        /// The same state in light and dark.
        private static func pair(
            _ controller: AppController, _ name: String, _ folder: URL,
            revealsHoverControls: Bool = false, prepare: (NSView) async -> Void = { _ in }
        ) async throws {
            try await snap(
                controller, "\(name)-light", .aqua, folder,
                revealsHoverControls: revealsHoverControls, prepare: prepare)
            try await snap(
                controller, "\(name)-dark", .darkAqua, folder,
                revealsHoverControls: revealsHoverControls, prepare: prepare)
        }

        /// A view on its own, such as a popover's content, in light and dark.
        private static func pairView(
            _ view: some View, _ name: String, _ folder: URL
        ) async throws {
            for (suffix, appearance) in [("light", NSAppearance.Name.aqua), ("dark", .darkAqua)] {
                let content = view.background(GlassPalette.standard.surface)
                    .background(Palette.page)
                    .environment(\.reducedMotion, true)
                let window = NSWindow(
                    contentRect: CGRect(origin: CGPoint(x: -30_000, y: -30_000), size: .zero),
                    styleMask: [.borderless], backing: .buffered, defer: false)
                window.alphaValue = 0
                window.ignoresMouseEvents = true
                window.appearance = NSAppearance(named: appearance)
                let host = NSHostingView(rootView: content)
                host.frame = CGRect(origin: .zero, size: host.fittingSize)
                window.contentView = host
                try await Task.sleep(for: .milliseconds(400))
                host.frame = CGRect(origin: .zero, size: host.fittingSize)
                host.layoutSubtreeIfNeeded()
                guard let bitmap = host.bitmapImageRepForCachingDisplay(in: host.bounds) else {
                    continue
                }
                host.cacheDisplay(in: host.bounds, to: bitmap)
                try bitmap.representation(using: .png, properties: [:])?
                    .write(to: folder.appending(path: "\(name)-\(suffix).png"))
                window.contentView = nil
                print("wrote \(name)-\(suffix).png")
            }
        }

        /// Web views draw out of process, and terminals inside SwiftUI are sometimes left
        /// out of the window's cache: draws each one's own image over its place.
        private static func drawPlatformViews(in host: NSView, onto bitmap: NSBitmapImageRep)
            async
        {
            var images: [(NSView, NSImage)] = []
            for web in webViews(in: host) where !web.isHiddenOrHasHiddenAncestor {
                if let image = try? await web.takeSnapshot(configuration: nil) {
                    images.append((web, image))
                } else {
                    print("no web view snapshot")
                }
            }
            for terminal in terminalViews(in: host) where !terminal.isHiddenOrHasHiddenAncestor {
                guard let rep = terminal.bitmapImageRepForCachingDisplay(in: terminal.bounds)
                else { continue }
                terminal.cacheDisplay(in: terminal.bounds, to: rep)
                let image = NSImage(size: terminal.bounds.size)
                image.addRepresentation(rep)
                images.append((terminal, image))
            }
            NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
            for (view, image) in images {
                let rect = view.convert(view.bounds, to: host)
                let y = host.isFlipped ? host.bounds.height - rect.maxY : rect.minY
                image.draw(in: CGRect(x: rect.minX, y: y, width: rect.width, height: rect.height))
            }
            NSGraphicsContext.restoreGraphicsState()
        }

        private static func terminalViews(in view: NSView) -> [HarnessTerminalView] {
            ([view as? HarnessTerminalView].compactMap { $0 })
                + view.subviews.flatMap(terminalViews)
        }

        private static func webViews(in view: NSView) -> [WKWebView] {
            ([view as? WKWebView].compactMap { $0 }) + view.subviews.flatMap(webViews)
        }

        /// Scrolls the transcript to the top, lets a new message arrive and prints whether
        /// the visible text moved.
        private static func scrollUpThenReceive(in host: NSView, transcript: TranscriptStore)
            async
        {
            guard let scroll = textViews(in: host).first?.enclosingScrollView else {
                print("no transcript scroll view")
                return
            }
            scroll.contentView.scroll(to: .zero)
            scroll.reflectScrolledClipView(scroll.contentView)
            try? await Task.sleep(for: .milliseconds(300))
            let before = scroll.contentView.bounds.origin.y
            transcript.receive(sampleMessage(nextMessageID, "A new message arrived out of view."))
            nextMessageID += 1
            try? await Task.sleep(for: .milliseconds(500))
            print("transcript offset before \(before), after \(scroll.contentView.bounds.origin.y)")
        }

        private static var nextMessageID = 10_001

        private static func sampleMessage(_ id: Int, _ text: String) -> Event {
            try! SampleData.decode([
                "id": id, "type": "session.message", "ts": "2026-10-06T09:00:00Z",
                "session_id": "c2", "payload": ["blocks": [["type": "text", "text": text]]],
            ])
        }

        private static func textViews(in view: NSView) -> [MessageTextView] {
            ([view as? MessageTextView].compactMap { $0 }) + view.subviews.flatMap(textViews)
        }

        /// Selects from one phrase to another in the transcript text that holds both.
        private static func selectAcrossParagraphs(in view: NSView, from: String, to: String) {
            if let text = view as? MessageTextView {
                let string = text.string as NSString
                let start = string.range(of: from)
                let end = string.range(of: to)
                if start.location != NSNotFound, end.location != NSNotFound {
                    text.window?.makeFirstResponder(text)
                    text.setSelectedRange(
                        NSRange(location: start.location, length: NSMaxRange(end) - start.location))
                }
            }
            for subview in view.subviews {
                selectAcrossParagraphs(in: subview, from: from, to: to)
            }
        }

        private static func snap(
            _ controller: AppController, _ name: String, _ appearance: NSAppearance.Name,
            _ folder: URL, revealsHoverControls: Bool = false,
            prepare: (NSView) async -> Void = { _ in }
        ) async throws {
            // Far off screen and fully transparent: nothing shows up on the user's display.
            let window = NSWindow(
                contentRect: CGRect(origin: CGPoint(x: -30_000, y: -30_000), size: size),
                styleMask: [.borderless], backing: .buffered, defer: false)
            window.alphaValue = 0
            window.ignoresMouseEvents = true
            window.appearance = NSAppearance(named: appearance)
            let host = NSHostingView(
                rootView: RootView()
                    .environment(controller)
                    .environment(\.flatGlass, true)
                    .environment(\.revealsHoverControls, revealsHoverControls))
            host.frame = CGRect(origin: .zero, size: size)
            window.contentView = host
            host.layoutSubtreeIfNeeded()
            try await Task.sleep(for: .milliseconds(900))
            host.layoutSubtreeIfNeeded()
            await prepare(host)
            host.layoutSubtreeIfNeeded()
            guard let bitmap = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { return }
            host.cacheDisplay(in: host.bounds, to: bitmap)
            await drawPlatformViews(in: host, onto: bitmap)
            let png = bitmap.representation(using: .png, properties: [:])
            try png?.write(to: folder.appending(path: "\(name).png"))
            // Drop the views so earlier windows stop updating while later ones render.
            window.contentView = nil
            print("wrote \(name).png")
        }
    }
#endif
