import CoreGraphics
import Foundation
import Testing

@testable import NestKit

private let folder = "/Users/me/code/nest/.claude/worktrees/nest-1a2b3c4d"
private let workspace = CGSize(width: 1000, height: 600)

enum RunFixture {
    static let defaultFolder = folder
    static let block = PortBlock(start: 41020, end: 41029)

    static func status(
        _ state: RunState = .stopped, listening: [Int] = [], exitCode: Int? = nil,
        startedAt: Date? = nil, folder: String = defaultFolder, available: Bool = true
    ) -> RunStatus {
        RunStatus(
            available: available, command: available ? "npm run dev" : nil, folder: folder,
            block: block, state: state, listening: listening, exitCode: exitCode,
            startedAt: startedAt)
    }

    static func changed(_ status: RunStatus) -> Event {
        let json = String(decoding: try! NestJSON.encoder.encode(status), as: UTF8.self)
        return Fixture.event(
            EventType.runChanged,
            #"{"folder": "\#(status.folder)", "repo": "nest", "status": \#(json)}"#, id: nil,
            session: nil)
    }

    static func output(_ text: String, folder: String = defaultFolder) -> Event {
        Fixture.event(
            EventType.runOutput, #"{"folder": "\#(folder)", "text": "\#(text)"}"#, id: nil,
            session: nil)
    }
}

@Suite struct RunStatusTests {
    @Test func decodesTheWireContract() {
        let status = Fixture.decode(
            RunStatus.self,
            json: """
                {"available": true, "command": "npm run dev",
                 "folder": "\(folder)", "block": {"start": 41020, "end": 41029},
                 "state": "running", "listening": [41020, 41021], "exit_code": null,
                 "started_at": "2026-10-26T22:41:07Z"}
                """)
        #expect(status.available)
        #expect(status.command == "npm run dev")
        #expect(status.folder == folder)
        #expect(status.block == PortBlock(start: 41020, end: 41029))
        #expect(status.state == .running)
        #expect(status.listening == [41020, 41021])
        #expect(status.exitCode == nil)
        #expect(status.startedAt == Fixture.date("2026-10-26T22:41:07Z"))
        #expect(status.isAlive)
    }

    @Test func aChatWithoutACommandOrBlockDecodes() {
        let status = Fixture.decode(
            RunStatus.self,
            json: """
                {"available": false, "command": null, "folder": "/repo", "block": null,
                 "state": "exited", "listening": [], "exit_code": 2, "started_at": null}
                """)
        #expect(!status.available && status.command == nil && status.block == nil)
        #expect(status.exitCode == 2 && !status.isAlive)
    }

    @Test func aNewerStateReadsAsUnknown() {
        let status = Fixture.decode(
            RunStatus.self,
            json: """
                {"available": true, "command": "make", "folder": "/repo", "block": null,
                 "state": "paused", "listening": [], "exit_code": null, "started_at": null}
                """)
        #expect(status.state == .unknown)
        #expect(RunFixture.status(.starting).isAlive)
        #expect(!RunFixture.status(.stopped).isAlive)
    }

    @Test func eventsCarryTheStatusAndTheOutput() {
        let status = RunFixture.status(
            .running, listening: [41020], startedAt: Fixture.date("2026-10-26T22:41:07Z"))
        let changed = RunFixture.changed(status)
        #expect(
            changed.body == .runChanged(RunChanged(folder: folder, repo: "nest", status: status)))
        #expect(
            RunFixture.output("ready\\n").body == .runOutput(folder: folder, text: "ready\n"))
        let broken = Fixture.event(EventType.runOutput, #"{"folder": 3}"#)
        #expect(broken.body == .other)
    }
}

@MainActor
@Suite struct RunStoreTests {
    let api = FakeAPI()
    let store: RunStore

    init() {
        store = RunStore(api: api)
        api.set {
            $0.runs = [
                "s1": RunFixture.status(), "s2": RunFixture.status(),
                "s3": RunFixture.status(folder: "/repo"),
            ]
            $0.runOutputs = ["s1": "$ npm run dev\n"]
        }
    }

    @Test func chatsSharingAFolderShareItsRun() async {
        #expect(store.status(of: "s1") == nil)
        await store.load("s1")
        await store.load("s2")
        await store.load("s3")
        #expect(store.status(of: "s1") == RunFixture.status())
        #expect(store.status(ofFolder: folder) == RunFixture.status())

        let running = RunFixture.status(.running, listening: [41020])
        store.apply(RunFixture.changed(running))
        #expect(store.status(of: "s1") == running)
        #expect(store.status(of: "s2") == running)
        #expect(store.status(of: "s3")?.state == .stopped)
    }

    @Test func aFailedReadKeepsWhatItHad() async {
        await store.load("s1")
        api.fail("runStatus")
        await store.load("s1")
        #expect(store.status(of: "s1") == RunFixture.status())
        await store.load("s9")
        #expect(store.status(of: "s9") == nil)
    }

    @Test func startStopAndRestartAnswerTheNewStatus() async throws {
        try await store.start("s1")
        #expect(store.status(of: "s1")?.state == .starting)
        try await store.stop("s1")
        #expect(store.status(of: "s1")?.state == .stopped)
        try await store.restart("s1")
        #expect(store.status(of: "s1")?.state == .starting)
        #expect(api.calls == ["startRun s1", "stopRun s1", "restartRun s1"])

        api.fail("startRun", with: APIError.server(status: 409, detail: "no run command"))
        await #expect(throws: APIError.self) { try await store.start("s1") }
        #expect(store.status(of: "s1")?.state == .starting)
    }

    @Test func outputFollowsItsFolderOnly() async {
        await store.loadOutput(folder: folder, session: "s1")
        #expect(store.output(of: folder)?.text == "$ npm run dev\n")
        store.apply(RunFixture.output("VITE ready"))
        store.apply(RunFixture.output(" in 412 ms\\n"))
        store.apply(RunFixture.output("other", folder: "/repo"))
        store.apply(Fixture.event(EventType.sessionDelta, #"{"text": "hi"}"#))
        #expect(store.output(of: folder)?.text == "$ npm run dev\nVITE ready in 412 ms\n")
        // A folder no pane reads keeps nothing.
        #expect(store.output(of: "/repo") == nil)
        #expect(store.output(of: folder)?.generation == 1)

        api.fail("runOutput")
        await store.loadOutput(folder: folder, session: "s1")
        #expect(store.output(of: folder)?.text == "$ npm run dev\nVITE ready in 412 ms\n")
    }

    @Test func aNewRunReadsTheOutputAgain() async throws {
        await store.loadOutput(folder: folder, session: "s1")
        store.apply(RunFixture.output("old line\\n"))
        api.set { $0.runOutputs["s1"] = "$ npm run dev\nfresh\n" }

        // Same run, other ports: the output goes on.
        let started = Date(timeIntervalSince1970: 5)
        store.apply(RunFixture.changed(RunFixture.status(.starting, startedAt: started)))
        // A first status for the folder is no new run either.
        #expect(store.refreshing == nil)
        store.apply(
            RunFixture.changed(RunFixture.status(.running, listening: [41020], startedAt: started)))
        #expect(store.refreshing == nil)
        // Stopped keeps the last start time: still the same output.
        store.apply(RunFixture.changed(RunFixture.status(.stopped, startedAt: started)))
        store.apply(RunFixture.changed(RunFixture.status(.stopped)))
        #expect(store.refreshing == nil)

        try await store.restart("s1")
        await store.refreshing?.value
        #expect(store.output(of: folder)?.text == "$ npm run dev\nfresh\n")
        #expect(store.output(of: folder)?.generation == 2)
    }

    @Test func aStatusChangeWithoutAShownOutputReadsNothing() async throws {
        try await store.start("s1")
        try await store.restart("s1")
        #expect(store.refreshing == nil)
        #expect(!api.calls.contains("runOutput s1"))
    }

    @Test func reloadingReadsEveryKnownChatAndOutput() async {
        await store.load("s3")
        await store.loadOutput(folder: folder, session: "s2")
        api.set {
            $0.runs["s3"]?.state = .exited
            $0.runOutputs["s2"] = "again\n"
        }
        await store.reload()
        #expect(store.status(of: "s3")?.state == .exited)
        #expect(store.output(of: folder)?.text == "again\n")
        #expect(api.calls.suffix(3) == ["runStatus s2", "runStatus s3", "runOutput s2"])
    }

    @Test func liveSyncFeedsTheStore() async {
        let model = AppModel(api: api, events: ManualEventSource(), preferences: MemoryStore())
        await model.runs.load("s1")
        model.live.route(RunFixture.changed(RunFixture.status(.running, listening: [41020])))
        #expect(model.runs.status(of: "s1")?.listening == [41020])
        await model.live.refresh()
        #expect(api.calls.filter { $0 == "runStatus s1" }.count == 2)
    }
}

@Suite struct RunOutputBufferTests {
    @Test func appendsAndReplaces() {
        var buffer = RunOutputBuffer()
        buffer.append("a\n")
        buffer.append("b")
        #expect(buffer.text == "a\nb" && buffer.generation == 0)
        buffer.replace(with: "c\n")
        #expect(buffer.text == "c\n" && buffer.generation == 1)
    }

    @Test func dropsWholeLinesPastTheLimit() {
        let line = String(repeating: "x", count: 99) + "\n"
        var buffer = RunOutputBuffer(text: String(repeating: line, count: 4_000))
        #expect(buffer.text.utf8.count == 400_000 && buffer.generation == 0)
        buffer.append("y\n")
        // The first line is cut in part, so it goes whole.
        #expect(buffer.text.utf8.count == 399_902)
        #expect(buffer.text.hasPrefix(line) && buffer.text.hasSuffix(line + "y\n"))
        #expect(buffer.generation == 1)
    }

    @Test func oneHugeLineLeavesNothing() {
        let buffer = RunOutputBuffer(text: String(repeating: "x", count: 400_001))
        #expect(buffer.text.isEmpty && buffer.generation == 1)
    }
}

@Suite struct RunOutputFeedTests {
    @Test func feedsOnlyWhatIsNew() {
        var feed = RunOutputFeed()
        var buffer = RunOutputBuffer(text: "$ npm run dev\n")
        #expect(feed.next(buffer) == (true, "$ npm run dev\r\n"))
        #expect(feed.next(buffer) == (false, ""))
        buffer.append("é ready\n")
        #expect(feed.next(buffer) == (false, "é ready\r\n"))
        buffer.replace(with: "fresh")
        #expect(feed.next(buffer) == (true, "fresh"))
    }

    @Test func aShorterBufferStartsOver() {
        var feed = RunOutputFeed()
        _ = feed.next(RunOutputBuffer(text: "long text"))
        #expect(feed.next(RunOutputBuffer(text: "short")) == (true, "short"))
    }

    @Test func bareLineFeedsGetACarriageReturn() {
        #expect(RunOutputFeed.terminalText("a\nb\r\nc\n\n") == "a\r\nb\r\nc\r\n\r\n")
        #expect(RunOutputFeed.terminalText("\u{1B}[32mok\u{1B}[0m") == "\u{1B}[32mok\u{1B}[0m")
        #expect(RunOutputFeed.terminalText("") == "")
    }
}

@Suite struct RunControlTests {
    @Test func noControlWithoutACommand() {
        #expect(RunControl(status: nil) == nil)
        #expect(RunControl(status: RunFixture.status(available: false)) == nil)
        var status = RunFixture.status()
        status.command = nil
        #expect(RunControl(status: status) == nil)
    }

    @Test func stoppedAndCleanExitsOfferRun() {
        let run = RunControl.run(help: "Run npm run dev")
        #expect(RunControl(status: RunFixture.status()) == run)
        #expect(RunControl(status: RunFixture.status(.exited, exitCode: 0)) == run)
        #expect(RunControl(status: RunFixture.status(.exited)) == run)
        #expect(RunControl(status: RunFixture.status(.unknown)) == run)
    }

    @Test func startingStopsOnClick() {
        let starting = RunControl.starting(help: "Starting npm run dev. Click to stop")
        #expect(RunControl(status: RunFixture.status(.starting)) == starting)
        // Running with nothing listening yet reads as starting.
        #expect(RunControl(status: RunFixture.status(.running)) == starting)
    }

    @Test func aFailedExitSaysItsCode() {
        #expect(
            RunControl(status: RunFixture.status(.exited, exitCode: 1))
                == .exited(
                    label: "Exited 1", help: "npm run dev exited with code 1. Click to run again"))
        #expect(
            RunControl(status: RunFixture.status(.exited, exitCode: -15))
                == .exited(
                    label: "Exited -15",
                    help: "npm run dev exited with code -15. Click to run again"))
    }

    @Test func runningShowsItsPortsTheFirstLive() {
        let control = RunControl(status: RunFixture.status(.running, listening: [41020, 41021]))
        #expect(
            control
                == .running(
                    ports: [
                        RunPort(
                            port: 41020, live: true, url: "http://localhost:41020",
                            help: "Open localhost:41020"),
                        RunPort(
                            port: 41021, live: false, url: "http://localhost:41021",
                            help: "Open localhost:41021"),
                    ], more: 0, moreHelp: nil, stopHelp: "Stop npm run dev"))
        let port = RunControl.ports(RunFixture.status(.running, listening: [41020]))[0]
        #expect(port.id == 41020 && port.label == "41020")
    }

    @Test func moreThanThreePortsShowTwoAndTheRest() {
        let three = RunControl(
            status: RunFixture.status(.running, listening: [41020, 41021, 41022]))
        guard case .running(let ports, let more, let help, _) = three else {
            Issue.record("not running")
            return
        }
        #expect(ports.map(\.port) == [41020, 41021, 41022] && more == 0 && help == nil)

        let four = RunControl(
            status: RunFixture.status(.running, listening: [41020, 41021, 41022, 41023]))
        guard case .running(let shown, let rest, let restHelp, _) = four else {
            Issue.record("not running")
            return
        }
        #expect(shown.map(\.port) == [41020, 41021] && rest == 2)
        #expect(restHelp == "Also 41022, 41023")
    }

    @Test func narrowPanesShowOnlyTheFirstPort() {
        let control = RunControl(
            status: RunFixture.status(.running, listening: [41020, 41021, 41022, 41023]),
            compact: true)
        guard case .running(let ports, let more, let help, let stop) = control else {
            Issue.record("not running")
            return
        }
        #expect(ports.map(\.port) == [41020] && ports[0].live)
        #expect(more == 3 && help == "Also 41021, 41022, 41023" && stop == "Stop npm run dev")
    }

    @Test func aPortOutsideTheBlockSaysSo() {
        let ports = RunControl.ports(RunFixture.status(.running, listening: [5173, 41020]))
        #expect(ports[0].help == "Outside this folder's ports 41020 to 41029")
        #expect(ports[0].url == "http://localhost:5173" && ports[0].live)
        #expect(ports[1].help == "Open localhost:41020")
        // Without a block nothing is outside it.
        var status = RunFixture.status(.running, listening: [5173])
        status.block = nil
        #expect(RunControl.ports(status)[0].help == "Open localhost:5173")
    }

    /// B105: the ports are the other machine's localhost, so they do not open here.
    @Test func aRemoteDaemonsPortsDoNotOpen() {
        let ports = RunControl.ports(
            RunFixture.status(.running, listening: [41020, 5173]), machine: "Mac mini")
        #expect(ports.map(\.url) == [nil, nil])
        #expect(ports.map(\.help) == ["Runs on Mac mini", "Runs on Mac mini"])
        let control = RunControl(
            status: RunFixture.status(.running, listening: [41020]), machine: "Mac mini")
        guard case .running(let chips, _, _, _) = control else {
            Issue.record("not running")
            return
        }
        #expect(chips[0].url == nil)
        // Run itself still works through the daemon.
        #expect(
            RunControl(status: RunFixture.status(), machine: "Mac mini")
                == .run(help: "Run npm run dev"))
    }

    @Test func theOutputPaneNamesItsCommandAndBranch() {
        #expect(RunPaneText.title(RunFixture.status()) == "npm run dev")
        #expect(RunPaneText.title(nil) == "Run")
        var session = Fixture.session(repo: "nest")
        session.branch = "board-filters"
        #expect(RunPaneText.place(session) == "board-filters")
        session.branch = nil
        #expect(RunPaneText.place(session) == "nest")
        #expect(RunPaneText.place(nil) == nil)
    }
}

@Suite struct RunPaneLayoutTests {
    @Test func runPanesTellTheirKindAndFolder() {
        let pane = ToolPane.run(folder: folder, session: "s1")
        #expect(PaneKind(paneID: pane.id) == .run)
        #expect(pane.kind == .run && pane.folder == folder && pane.session == "s1")
        #expect(pane.title == "nest-1a2b3c4d")
        let decoded = try? JSONDecoder().decode(
            ToolPane.self, from: JSONEncoder().encode(pane))
        #expect(decoded == pane)
        // Panes saved before B108 have no session.
        let old = try? JSONDecoder().decode(
            ToolPane.self, from: Data(#"{"id": "terminal:1", "kind": "terminal"}"#.utf8))
        #expect(old == ToolPane(id: "terminal:1", kind: .terminal))
    }

    @Test func runOpensBesideTheChatAndKeepsTheFocus() {
        var state = ProjectState()
        state.openChat("c1", in: workspace)
        state.view = .board
        let result = state.runOutput(folder: folder, session: "c1", beside: "c1", in: workspace)
        #expect(result.opened)
        #expect(state.view == .workspace)
        #expect(state.layout.leaves == ["c1", result.pane.id])
        #expect(state.layout.focused == "c1")
        #expect(state.selectedChat == "c1")
        #expect(state.openTools == [result.pane])
    }

    @Test func oneOutputPanePerFolderLeavesTheFocusInTheChat() {
        var state = ProjectState()
        state.openChat("c1", in: workspace)
        state.openChat("c2", in: workspace)
        let first = state.runOutput(folder: folder, session: "c1", beside: "c1", in: workspace)
        state.focusPane("c2")
        let again = state.runOutput(folder: folder, session: "c2", beside: "c2", in: workspace)
        #expect(!again.opened && again.pane == first.pane)
        #expect(state.layout.focused == "c2")
        let other = state.runOutput(folder: "/repo", session: "c2", beside: "c2", in: workspace)
        #expect(other.opened)
        #expect(state.openTools.count == 2)
        // A terminal in the folder is no output pane.
        var terminals = ProjectState()
        terminals.openTool(
            ToolPane(id: "terminal:1", kind: .terminal, folder: folder), in: workspace)
        #expect(
            terminals.runOutput(folder: folder, session: "c1", beside: "c1", in: workspace).opened)
    }

    @MainActor @Test func runPanesAreSavedWithTheWorkspace() async throws {
        let memory = MemoryStore()
        let app = AppStore(api: FakeAPI(), store: memory)
        try await app.loadRepos()
        var pane: ToolPane?
        app.update("todo-ui") { state in
            state.openChat("c1", in: workspace)
            pane = state.runOutput(folder: folder, session: "c1", beside: "c1", in: workspace).pane
        }
        let reopened = AppStore(api: FakeAPI(), store: memory)
        #expect(reopened.state(of: "todo-ui").openTools == [pane!])
    }
}

@Suite struct PlaceBesideTests {
    @Test func aWidePaneSplitsSideBySide() {
        var layout = WorkspaceLayout()
        layout.open("c1", in: workspace)
        layout.place("run:1", beside: "c1", in: workspace)
        #expect(layout.leaves == ["c1", "run:1"])
        #expect(layout.focused == "c1")
        #expect(layout.paneFrames(in: workspace)[1].frame.minY == 0)
        // Already open: nothing moves.
        layout.place("run:1", beside: "c1", in: workspace)
        #expect(layout.leaves == ["c1", "run:1"])
    }

    @Test func aNarrowPaneSplitsBelow() {
        var layout = WorkspaceLayout()
        layout.open("c1", in: CGSize(width: 600, height: 800))
        layout.place("run:1", beside: "c1", in: CGSize(width: 600, height: 800))
        let frames = layout.paneFrames(in: CGSize(width: 600, height: 800))
        #expect(frames.map(\.chat) == ["c1", "run:1"])
        #expect(frames[1].frame.minX == 0 && frames[1].frame.minY > 0)
        #expect(layout.focused == "c1")
    }

    @Test func aMaximizedChatStaysMaximized() {
        var layout = WorkspaceLayout()
        layout.open("c1", in: CGSize(width: 600, height: 800))
        layout.open("c2", in: CGSize(width: 600, height: 800))
        layout.toggleMaximize("c2")
        layout.place("run:1", beside: "c2", in: CGSize(width: 600, height: 800))
        #expect(layout.maximized == "c2" && layout.focused == "c2")
        #expect(layout.leaves.contains("run:1"))
    }

    @Test func aFullWorkspaceReplacesTheLastOtherPane() {
        var layout = WorkspaceLayout()
        for chat in ["c1", "c2", "c3", "c4"] {
            layout.open(chat, in: workspace)
        }
        let last = layout.leaves.last!
        layout.focus(last)
        layout.place("run:1", beside: last, in: workspace)
        #expect(layout.leaves.count == 4 && layout.contains(last) && layout.focused == last)
        #expect(layout.contains("run:1"))

        // The replaced pane had the focus: the chat takes it.
        var full = WorkspaceLayout()
        for chat in ["c1", "c2", "c3", "c4"] {
            full.open(chat, in: workspace)
        }
        let victim = full.leaves.last!
        let chat = full.leaves.first!
        full.focus(victim)
        full.place("run:1", beside: chat, in: workspace)
        #expect(!full.contains(victim) && full.focused == chat)
    }

    @Test func withoutTheChatItOpensAsAClickWould() {
        var layout = WorkspaceLayout()
        layout.place("run:1", beside: "gone", in: workspace)
        #expect(layout.leaves == ["run:1"] && layout.focused == "run:1")
    }
}
