import Foundation
import Synchronization
import Testing

@testable import NestKit

/// Holds every sleep until released, to see which of several queries waits.
final class GateSleeper: Sleeper {
    private struct State {
        var waiting: [CheckedContinuation<Void, Never>] = []
        var arrived = 0
    }

    private let state = Mutex(State())
    private let changes = Changes()

    func sleep(seconds: Double) async throws {
        await withCheckedContinuation { continuation in
            state.withLock { state in
                state.waiting.append(continuation)
                state.arrived += 1
            }
            changes.note()
        }
    }

    /// Ends once `count` sleeps have begun.
    func arrivals(_ count: Int) async {
        await changes.until { [self] in self.state.withLock { $0.arrived >= count } }
    }

    func releaseAll() {
        state.withLock { state in
            state.waiting.forEach { $0.resume() }
            state.waiting = []
        }
    }
}

/// A sleep the task was cancelled in.
struct CancelledSleeper: Sleeper {
    func sleep(seconds: Double) async throws {
        throw CancellationError()
    }
}

enum SearchFixture {
    static let json = """
        {"hits": [
          {"session_id": "s1", "repo": "todo-ui", "title": "Validate the form", "event_id": null,
           "ts": "2026-10-06T09:00:00Z", "kind": "title", "snippet": "Validate the [[form]]"},
          {"session_id": "s1", "repo": "todo-ui", "title": "Validate the form", "event_id": 14,
           "ts": "2026-10-06T09:01:00Z", "kind": "assistant",
           "snippet": "…the [[form]] posts [[JSON]] to the route"},
          {"session_id": "s1", "repo": "todo-ui", "title": "Validate the form", "event_id": 14,
           "ts": "2026-10-06T09:01:00Z", "kind": "tool", "snippet": "Read app/[[form]].tsx"},
          {"session_id": "cc-1", "repo": "map-viewer", "title": "Form scraper", "event_id": null,
           "ts": "2026-10-06T09:02:00Z", "kind": "claude_chat", "snippet": "[[Form]] scraper"},
          {"session_id": "s2", "repo": "todo-ui", "title": "Other", "event_id": 3,
           "ts": "2026-10-06T09:03:00Z", "kind": "subagent", "snippet": "a [[form]]"},
          {"session_id": "cx-1", "repo": "todo-ui", "title": "Form footer", "event_id": null,
           "ts": "2026-10-06T09:04:00Z", "kind": "codex_chat", "snippet": "[[Form]] footer"}
        ], "indexing": true}
        """

    static var results: SearchResults { Fixture.decode(SearchResults.self, json: json) }
}

@Suite struct SearchModelTests {
    @Test func decodesHitsWithTheirPanes() {
        let results = SearchFixture.results
        #expect(results.indexing)
        #expect(results.hits.count == 6)
        let hit = results.hits[1]
        #expect(hit.sessionID == "s1")
        #expect(hit.repo == "todo-ui")
        #expect(hit.title == "Validate the form")
        #expect(hit.eventID == 14)
        #expect(hit.kind == .assistant)
        #expect(hit.ts == Date(timeIntervalSince1970: 1_791_277_260))
        #expect(hit.pane == "s1")
        #expect(results.hits[0].eventID == nil)
        #expect(results.hits[3].kind == .claudeChat)
        #expect(results.hits[3].pane == "claude-code:cc-1")
        #expect(ClaudeChat.chatID(ofPane: results.hits[3].pane) == "cc-1")
        #expect(results.hits[4].kind == .unknown)
        // A Codex chat from outside Nest opens like a Claude Code one, by its id.
        #expect(results.hits[5].kind == .codexChat)
        #expect(results.hits[5].pane == "claude-code:cx-1")
    }

    @Test func kindsHaveLabels() {
        let kinds: [SearchHitKind] = [
            .title, .user, .assistant, .tool, .toolResult, .claudeChat, .codexChat, .unknown,
        ]
        #expect(
            kinds.map(\.label) == [
                "Title", "You", "Claude", "Tool call", "Tool output", "Claude Code chat",
                "Codex chat", "Message",
            ])
        // An answer is its chat's engine's (B91).
        #expect(SearchHitKind.assistant.label(agent: "Codex") == "Codex")
        #expect(SearchHitKind.user.label(agent: "Codex") == "You")
    }

    @Test func snippetsSplitAtTheirMarkers() {
        #expect(
            Snippet.parts("…the [[form]] posts [[JSON]]") == [
                SnippetPart(text: "…the ", matched: false),
                SnippetPart(text: "form", matched: true),
                SnippetPart(text: " posts ", matched: false),
                SnippetPart(text: "JSON", matched: true),
            ])
        #expect(
            Snippet.parts("[[Form]] scraper") == [
                SnippetPart(text: "Form", matched: true),
                SnippetPart(text: " scraper", matched: false),
            ])
        #expect(Snippet.parts("no match") == [SnippetPart(text: "no match", matched: false)])
        #expect(
            Snippet.parts("cut [[off") == [
                SnippetPart(text: "cut ", matched: false), SnippetPart(text: "off", matched: true),
            ])
        #expect(Snippet.parts("").isEmpty)
    }
}

@MainActor
@Suite struct MessageSearchTests {
    let api = FakeAPI()

    @Test func shortQueriesAreNotSent() async {
        let search = MessageSearch(api: api, sleeper: FakeSleeper())
        #expect(await search.results(for: "") == nil)
        #expect(await search.results(for: " a ") == nil)
        #expect(api.calls.isEmpty)
    }

    @Test func waitsForTypingToPauseThenSearchesTheTrimmedQuery() async {
        let sleeper = FakeSleeper()
        api.set { $0.searches["zod"] = SearchFixture.results }
        let search = MessageSearch(api: api, sleeper: sleeper)

        let results = await search.results(for: "  zod ")

        #expect(results == SearchFixture.results)
        #expect(sleeper.delays.withLock { $0 } == [0.2])
        #expect(api.calls == ["search zod all 20"])
    }

    @Test func onlyTheNewestQueryIsSent() async {
        let sleeper = GateSleeper()
        api.set { $0.searches["form"] = SearchFixture.results }
        let search = MessageSearch(api: api, sleeper: sleeper)

        let first = Task { await search.results(for: "fo") }
        await sleeper.arrivals(1)
        let second = Task { await search.results(for: "form") }
        await sleeper.arrivals(2)
        sleeper.releaseAll()

        #expect(await first.value == nil)
        #expect(await second.value == SearchFixture.results)
        #expect(api.calls == ["search form all 20"])
    }

    @Test func aSlowAnswerToAnOlderQueryIsDropped() async {
        let (gate, open) = AsyncStream<Void>.makeStream()
        let sleeper = FakeSleeper()
        api.set {
            $0.gates["search fo"] = gate
            $0.searches["fo"] = SearchFixture.results
        }
        let search = MessageSearch(api: api, sleeper: sleeper)

        let first = Task { await search.results(for: "fo") }
        await api.reached("search fo")
        let second = await search.results(for: "form")
        open.finish()

        #expect(second == SearchResults(hits: [], indexing: false))
        #expect(await first.value == nil)
    }

    @Test func aFailedSearchShowsNoHits() async {
        api.fail("search")
        let search = MessageSearch(api: api, sleeper: FakeSleeper())
        #expect(await search.results(for: "zod") == SearchResults(hits: [], indexing: false))
    }

    @Test func aCancelledPauseSendsNothing() async {
        let search = MessageSearch(api: api, sleeper: CancelledSleeper())
        #expect(await search.results(for: "zod") == nil)
        #expect(api.calls.isEmpty)
    }
}
