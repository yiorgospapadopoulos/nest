import CoreGraphics
import Foundation
import Testing

@testable import NestKit

@MainActor
@Suite struct CommandPaletteTests {
    let api = FakeAPI()
    let approvals: ApprovalsStore
    let sessions: SessionsStore
    let app: AppStore

    init() {
        approvals = ApprovalsStore(api: api)
        sessions = SessionsStore(api: api, approvals: approvals)
        app = AppStore(api: api, store: MemoryStore())
    }

    func load() async throws {
        var question = Fixture.approval("ap-question")
        question.sessionID = "h1"
        question.repo = "map-viewer"
        api.set {
            $0.sessions = [
                Fixture.session(
                    "c1", title: "Validate the form", state: .running,
                    updatedAt: .init(timeIntervalSince1970: 3)),
                Fixture.session(
                    "c2", title: "Dark mode", state: .idle,
                    updatedAt: .init(timeIntervalSince1970: 2)),
                Fixture.session("c3", title: "Old", archived: true),
                Fixture.session("h1", repo: "map-viewer", title: "Retry", state: .waiting),
            ]
            $0.approvals = [question]
        }
        try await app.loadRepos()
        app.openProject("map-viewer")
        app.selectProject("todo-ui")
        try await sessions.load()
        try await approvals.load()
    }

    @Test func listsChatsCommandsAndProjects() async throws {
        try await load()
        let palette = CommandPalette.catalog(app: app, sessions: sessions)

        #expect(
            palette.items.map(\.title) == [
                "Validate the form", "Dark mode", "Retry", "New chat in todo-ui",
                "New terminal in todo-ui", "New browser", "Show the Board view",
                "Collapse the chat sidebar", "Collapse the activity panel",
                "Show usage", "Open todo-ui in VS Code", "Go to map-viewer",
            ])
        #expect(
            palette.items.prefix(3).map(\.subtitle) == [
                "todo-ui · Running", "todo-ui · Idle", "map-viewer · Question",
            ])
        #expect(palette.items[1].glyph == .status(.done, hollow: true))
        #expect(palette.items[0].glyph == .status(.running, hollow: false))
        #expect(palette.items[2].action == .openChat(project: "map-viewer", chat: "h1"))
        #expect(palette.items.last?.subtitle == "1 need you")
        #expect(palette.items.last?.action == .goToProject("map-viewer"))
        #expect(palette.items[0].id == palette.items[0].action)
        #expect(Set(palette.items.map(\.group)) == [.chats, .commands, .projects])
        #expect(palette.messages.isEmpty)
    }

    @Test func commandsFollowTheProjectsState() async throws {
        try await load()
        app.update { state in
            state.view = .board
            state.leftCollapsed = true
            state.rightCollapsed = true
        }
        app.selectProject("map-viewer")
        app.selectProject("todo-ui")
        let titles = CommandPalette.catalog(app: app, sessions: sessions).items.map(\.title)
        #expect(titles.contains("Show the Workspace view"))
        #expect(titles.contains("Expand the chat sidebar"))
        #expect(titles.contains("Expand the activity panel"))
        app.selectProject("map-viewer")
        let other = CommandPalette.catalog(app: app, sessions: sessions).items
        #expect(other.last?.title == "Go to todo-ui")
        #expect(other.last?.subtitle == "Project")
    }

    @Test func withoutAProjectOnlyChatsShow() {
        let palette = CommandPalette.catalog(app: app, sessions: sessions)
        #expect(palette.items.isEmpty)
        #expect(palette.selected == nil)
    }

    @Test func searchFiltersByEveryWord() async throws {
        try await load()
        var palette = CommandPalette.catalog(app: app, sessions: sessions)
        palette.move(by: 2)
        palette.search("  cv  MODE ")
        #expect(palette.query == "  cv  MODE ")
        #expect(palette.selection == 0)
        #expect(palette.visible.map(\.title) == ["Dark mode"])
        palette.search("question")
        #expect(palette.selected?.title == "Retry")
        palette.search("nothing like this")
        #expect(palette.visible.isEmpty)
        #expect(palette.selected == nil)
        palette.move(by: 1)
        #expect(palette.selection == 0)
    }

    @Test func arrowsWrapAround() async throws {
        try await load()
        var palette = CommandPalette.catalog(app: app, sessions: sessions)
        palette.move(by: -1)
        #expect(palette.selected?.title == "Go to map-viewer")
        palette.move(by: 1)
        #expect(palette.selected?.title == "Validate the form")
        palette.select(palette.items[4])
        #expect(palette.selection == 4)
        palette.search("dark")
        palette.select(palette.items[4])
        #expect(palette.selection == 0)
    }

    @Test func messageHitsFollowTheMatchesOncePerChatAndEvent() async throws {
        try await load()
        var palette = CommandPalette.catalog(app: app, sessions: sessions)
        palette.search("form")
        #expect(palette.searchesMessages)
        palette.show(SearchFixture.results, for: "form")

        #expect(palette.indexing)
        #expect(palette.messages.allSatisfy { $0.group == .messages })
        #expect(
            palette.messages.map(\.action) == [
                .openMessage(project: "todo-ui", pane: "s1", event: nil),
                .openMessage(project: "todo-ui", pane: "s1", event: 14),
                .openMessage(project: "map-viewer", pane: "claude-code:cc-1", event: nil),
                .openMessage(project: "todo-ui", pane: "s2", event: 3),
            ])
        let hit = palette.messages[1]
        #expect(hit.title == "Validate the form")
        #expect(hit.subtitle == "todo-ui · Claude")
        #expect(hit.glyph == .message(.assistant))
        #expect(hit.snippet.filter(\.matched).map(\.text) == ["form", "JSON"])
        #expect(palette.messages[2].subtitle == "map-viewer · Claude Code chat")
        let titles = ["Validate the form"] + palette.messages.map(\.title)
        #expect(palette.visible.map(\.title) == titles)
        palette.move(by: 2)
        #expect(palette.selected == hit)
    }

    @Test func staleOrShortQueriesDropTheHits() async throws {
        try await load()
        var palette = CommandPalette.catalog(app: app, sessions: sessions)
        palette.search("form")
        palette.show(SearchFixture.results, for: "for")
        #expect(palette.messages.isEmpty)

        palette.show(SearchFixture.results, for: "form")
        palette.search("forms")
        #expect(palette.messages.count == 4)
        palette.search("f")
        #expect(!palette.searchesMessages)
        #expect(palette.messages.isEmpty)
        #expect(!palette.indexing)
        palette.show(SearchFixture.results, for: "f")
        #expect(palette.messages.isEmpty)
    }

    @Test func fewerHitsKeepTheSelectionInRange() async throws {
        try await load()
        var palette = CommandPalette.catalog(app: app, sessions: sessions)
        palette.search("zz")
        palette.show(SearchFixture.results, for: "zz")
        palette.move(by: 3)
        #expect(palette.selection == 3)
        let one = SearchResults(hits: [SearchFixture.results.hits[0]], indexing: false)
        palette.show(one, for: "zz")
        #expect(palette.selection == 0)
        palette.show(SearchResults(hits: [], indexing: false), for: "zz")
        #expect(palette.selection == 0)
        #expect(palette.selected == nil)
    }
}
