import CoreGraphics
import Foundation
import Testing

@testable import NestKit

private let workspace = CGSize(width: 1000, height: 600)

@Suite struct ToolPaneTests {
    @Test func paneIDsTellTheirKind() {
        let terminal = ToolPane.terminal(in: "/repo")
        let browser = ToolPane.browser()
        #expect(PaneKind(paneID: terminal.id) == .terminal)
        #expect(PaneKind(paneID: browser.id) == .browser)
        #expect(PaneKind(paneID: "5b8f3c2a") == .chat)
        #expect(PaneKind(paneID: "draft-1") == .chat)
        #expect(PaneKind(paneID: "claude-code:abc") == .chat)
        #expect(terminal.kind == .terminal && browser.kind == .browser)
    }

    @Test func eachNewPaneHasItsOwnID() {
        let terminals = (0..<20).map { _ in ToolPane.terminal(in: "/repo").id }
        let browsers = (0..<20).map { _ in ToolPane.browser().id }
        let ids = terminals + browsers
        #expect(Set(ids).count == 40)
    }

    @Test func terminalFoldersAreNormalized() {
        #expect(ToolPane.terminal(in: "/repo/app/").folder == "/repo/app")
        #expect(ToolPane.terminal(in: "/repo/./app/../web").folder == "/repo/web")
    }

    @Test func titlesNameTheFolderOrTheHost() {
        #expect(ToolPane.terminal(in: "/Users/me/cv-page").title == "cv-page")
        #expect(ToolPane(id: "terminal:x", kind: .terminal).title == "Terminal")
        #expect(ToolPane.browser().title == "Browser")
        #expect(ToolPane.browser(url: "http://localhost:3000/about").title == "localhost")
        #expect(ToolPane.browser(url: "not a url").title == "Browser")
        #expect(ToolPane(id: "x", kind: .chat, url: "https://example.com").title == "example.com")
    }

    @Test func aCommandRunsWithOneNewline() {
        #expect(TerminalInput.line(for: "npm test") == "npm test\n")
        #expect(TerminalInput.line(for: "  make check\n\n") == "make check\n")
        #expect(TerminalInput.line(for: "printf\t'%s'") == "printf\t'%s'\n")
    }

    @Test func aCommandOfSeveralLinesIsNotRun() {
        // Each line would run as a command of its own; Copy still offers them.
        for command in [
            "cd web\nnpm run dev", "make \\\n  check", "ls\rrm -r build", "ls\r\npwd",
            "ls\u{2028}pwd", "ls\u{0B}pwd", "ls\u{85}pwd", "   ", "\u{1B}\u{7}",
        ] {
            #expect(TerminalInput.line(for: command) == nil, "\(command.debugDescription)")
        }
    }

    @Test func controlAndDirectionCharactersAreDropped() {
        #expect(TerminalInput.line(for: "echo \u{1B}[2Jhi\u{7}") == "echo [2Jhi\n")
        #expect(TerminalInput.line(for: "rm\u{0} x\u{7F}\u{9B}") == "rm x\n")
        // Shown as "cat exe.txt" but would read the other way round.
        #expect(
            TerminalInput.line(for: "cat \u{202E}txt.exe\u{202C}") == "cat txt.exe\n")
        let marks =
            "\u{200E}\u{200F}\u{061C}\u{202A}\u{202B}\u{202D}\u{2066}\u{2067}\u{2068}\u{2069}"
        #expect(TerminalInput.line(for: "ls\(marks) -la") == "ls -la\n")
        // Joiners in emoji are not direction controls.
        #expect(TerminalInput.line(for: "echo 👩\u{200D}💻") == "echo 👩\u{200D}💻\n")
    }

    @Test func aSessionWorksInItsWorktreeOrItsFolder() {
        var session = Fixture.session()
        session.worktreePath = "/wt/a"
        session.cwd = "/repo"
        #expect(session.folder == "/wt/a")
        session.worktreePath = nil
        #expect(session.folder == "/repo")
        session.cwd = nil
        #expect(session.folder == nil)
    }
}

@Suite struct ProjectToolsTests {
    @Test func toolPanesOpenLikeChats() {
        var state = ProjectState()
        state.view = .board
        state.openChat("c1", in: workspace)
        state.view = .board
        let terminal = ToolPane.terminal(in: "/repo")
        state.openTool(terminal, in: workspace)
        #expect(state.view == .workspace)
        #expect(state.layout.leaves == ["c1", terminal.id])
        #expect(state.layout.focused == terminal.id)
        #expect(state.tools[terminal.id] == terminal)
        #expect(state.openTools == [terminal])
    }

    @Test func theFourPaneRuleAppliesToToolPanes() {
        var state = ProjectState()
        let terminal = ToolPane.terminal(in: "/repo")
        let browser = ToolPane.browser()
        state.openChat("c1", in: workspace)
        state.openTool(terminal, in: workspace)
        state.openChat("c2", in: workspace)
        state.openTool(browser, in: workspace)
        #expect(state.layout.leaves.count == 4)

        // A fifth pane takes the last one's place; the browser it replaced is forgotten.
        state.openChat("c3", in: workspace)
        #expect(state.layout.leaves == ["c1", "c2", terminal.id, "c3"])
        #expect(state.openTools == [terminal])
        #expect(state.tools[browser.id] == nil)

        // A chat dropped on the terminal while full replaces it.
        state.dropChat("c4", onto: terminal.id, side: .left)
        #expect(state.layout.leaves == ["c1", "c2", "c4", "c3"])
        #expect(state.tools.isEmpty)
    }

    @Test func toolPanesSwapResizeMaximizeAndClose() {
        var state = ProjectState()
        let terminal = ToolPane.terminal(in: "/repo")
        state.openChat("c1", in: workspace)
        state.openTool(terminal, in: workspace)
        state.layout.swap("c1", terminal.id)
        #expect(state.layout.leaves == [terminal.id, "c1"])
        state.layout.resize(split: 1, ratio: 0.7, in: workspace)
        #expect(state.layout.gutterFrames(in: workspace).first?.ratio == 0.7)
        state.layout.toggleMaximize(terminal.id)
        #expect(state.layout.maximized == terminal.id)
        state.closePane(terminal.id)
        #expect(state.layout.leaves == ["c1"])
        #expect(state.layout.maximized == nil)
        #expect(state.tools.isEmpty)
    }

    @Test func aDraftBecomingAChatKeepsTheToolPanes() {
        var state = ProjectState()
        let browser = ToolPane.browser()
        state.openChat("draft-1", in: workspace)
        state.openTool(browser, in: workspace)
        state.replaceChat("draft-1", with: "s1")
        #expect(state.layout.leaves == ["s1", browser.id])
        #expect(state.openTools == [browser])
        state.closePane("s1")
        #expect(state.openTools == [browser])
    }

    @Test func commandsGoToTheTerminalOfTheirFolder() {
        var state = ProjectState()
        state.openChat("c1", in: workspace)
        let first = state.terminal(for: "/repo", in: workspace)
        #expect(first.opened)
        #expect(first.pane.folder == "/repo")
        state.focusPane("c1")
        state.view = .board

        let again = state.terminal(for: "/repo/", in: workspace)
        #expect(!again.opened)
        #expect(again.pane == first.pane)
        #expect(state.layout.focused == first.pane.id)
        #expect(state.view == .workspace)

        let other = state.terminal(for: "/wt/a", in: workspace)
        #expect(other.opened)
        // The new terminal splits the chat's pane, so it comes first in reading order.
        #expect(state.openTools.map(\.folder) == ["/wt/a", "/repo"])
    }

    @Test func aBrowserIsNotATerminal() {
        var state = ProjectState()
        state.openTool(ToolPane(id: "browser:1", kind: .browser, folder: "/repo"), in: workspace)
        #expect(state.terminal(for: "/repo", in: workspace).opened)
    }

    @Test func browsersRememberTheirPage() {
        var state = ProjectState()
        let browser = ToolPane.browser()
        state.openTool(browser, in: workspace)
        state.setURL("http://localhost:3000/", of: browser.id)
        state.setURL("http://localhost:4000/", of: "browser:gone")
        #expect(state.openTools.map(\.url) == ["http://localhost:3000/"])
    }
}

@MainActor
@Suite struct SavedToolPanesTests {
    let api = FakeAPI()
    let memory = MemoryStore()

    func app() -> AppStore {
        AppStore(api: api, store: memory)
    }

    @Test func toolPanesAreSavedPerProjectAndReopened() async throws {
        let app = app()
        try await app.loadRepos()
        app.openProject("llm-hunter")
        let terminal = ToolPane.terminal(in: "/repo/cv-page")
        let browser = ToolPane.browser(url: "http://localhost:3000/")
        app.update("cv-page") { state in
            state.openChat("c1", in: workspace)
            state.openTool(terminal, in: workspace)
            state.openTool(browser, in: workspace)
        }
        app.update("cv-page") { $0.setURL("http://localhost:3000/about", of: browser.id) }
        #expect(memory.values["projects.tools.llm-hunter"] == nil)

        let saved = app.state(of: "cv-page").openTools
        // The browser split the chat's pane, so it comes before the terminal.
        #expect(saved.map(\.id) == [browser.id, terminal.id])

        let reopened = self.app()
        let tools = reopened.state(of: "cv-page").openTools
        #expect(tools == saved)
        #expect(tools.map(\.folder) == [nil, "/repo/cv-page"])
        #expect(tools.first?.url == "http://localhost:3000/about")
        #expect(reopened.state(of: "cv-page").layout.leaves == [browser.id, terminal.id])
    }

    @Test func closingTheLastToolPaneForgetsThem() async throws {
        let app = app()
        try await app.loadRepos()
        let terminal = ToolPane.terminal(in: "/repo")
        app.update { $0.openTool(terminal, in: workspace) }
        #expect(memory.values["projects.tools.cv-page"] != nil)
        app.update { $0.closePane(terminal.id) }
        #expect(memory.values["projects.tools.cv-page"] == nil)
        #expect(self.app().state(of: "cv-page") == ProjectState())
    }

    @Test func aProjectOpenedLaterGetsItsToolPanesBack() async throws {
        let browser = ToolPane.browser(url: "https://example.com/")
        memory.values["projects.tools.llm-hunter"] = Fixture.json([browser])
        memory.values["projects.tools.cv-page"] = "not json"
        memory.values["projects.open"] = "cv-page"
        let app = app()
        try await app.loadRepos()
        #expect(app.state(of: "cv-page") == ProjectState())
        #expect(app.state(of: "llm-hunter") == ProjectState())

        app.openProject("llm-hunter")
        #expect(app.state(of: "llm-hunter").openTools == [browser])

        // Opening it again keeps what changed since.
        app.update("llm-hunter") { $0.closePane(browser.id) }
        app.openProject("llm-hunter")
        #expect(app.state(of: "llm-hunter").openTools.isEmpty)
    }

    @Test func aClosedTabKeepsItsToolPanesAndARemovedProjectEndsThem() async throws {
        let app = app()
        try await app.loadRepos()
        app.openProject("llm-hunter")
        let terminal = ToolPane.terminal(in: "/repo/llm-hunter")
        app.update("llm-hunter") { $0.openTool(terminal, in: workspace) }

        app.closeProject("llm-hunter")
        #expect(app.state(of: "llm-hunter").openTools == [terminal])

        api.set { $0.repos.removeAll { $0.name == "llm-hunter" } }
        try await app.loadRepos()
        #expect(app.projects["llm-hunter"] == nil)
        #expect(memory.values["projects.tools.llm-hunter"] == nil)
        #expect(app.state(of: "cv-page") == ProjectState())
    }

    @Test func anEmptySavedListRestoresNothing() async throws {
        memory.values["projects.open"] = "cv-page"
        memory.values["projects.tools.cv-page"] = "[]"
        let app = app()
        #expect(app.projects["cv-page"] == nil)
    }
}
