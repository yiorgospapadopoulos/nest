import Foundation
import Testing

@testable import HarnessKit

private func call(
    _ name: String, _ id: String, result: String? = "ok", isError: Bool = false
) -> ToolCall {
    ToolCall(id: id, name: name, input: .object([:]), result: result, isError: isError)
}

private func tool(_ name: String, _ id: String, result: String? = "ok", isError: Bool = false)
    -> TranscriptItem
{
    TranscriptItem(
        id: id, content: .tool(call(name, id, result: result, isError: isError)), eventID: 1)
}

private func text(_ id: String) -> TranscriptItem {
    TranscriptItem(id: id, content: .assistant("text", streaming: false), eventID: 1)
}

private func thought(_ id: String) -> TranscriptItem {
    TranscriptItem(id: id, content: .thinking("hm", durationMS: 1_000), eventID: 1)
}

private func end(_ id: String) -> TranscriptItem {
    TranscriptItem(
        id: id, content: .turnEnd(TurnEnd(durationMS: 5_000, stopped: false)), eventID: 1)
}

@Suite struct TurnTextTests {
    let start = Date(timeIntervalSince1970: 1_000)

    @Test func theWorkingLineCountsFromTheTurnStart() {
        #expect(
            TurnText.working(since: start, at: start + 12.7, thinking: false) == "Working... 12s")
        #expect(
            TurnText.working(since: start, at: start + 72, thinking: false) == "Working... 1m 12s")
        #expect(TurnText.working(since: start, at: start + 4, thinking: true) == "Thinking... 4s")
        #expect(
            TurnText.working(since: start, at: start + 3_720, thinking: false) == "Working... 1h 2m"
        )
        #expect(TurnText.working(since: start, at: start - 5, thinking: false) == "Working... 0s")
        #expect(TurnText.working(since: nil, at: start, thinking: false) == "Working...")
        #expect(TurnText.working(since: nil, at: start, thinking: true) == "Thinking...")
    }

    @Test func aFinishedTurnSaysHowLongItWorkedOrWhenItStopped() {
        #expect(TurnText.ended(TurnEnd(durationMS: 72_400, stopped: false)) == "Worked for 1m 12s")
        #expect(TurnText.ended(TurnEnd(durationMS: 40_000, stopped: true)) == "Stopped after 40s")
    }

    @Test func thinkingSaysHowLongItTook() {
        #expect(TurnText.thought(durationMS: 8_300) == "Thought for 8s")
        #expect(TurnText.thought(durationMS: nil) == "Thought")
    }
}

@Suite struct ToolActivityTests {
    @Test func runningGroupsSpeakInThePresentTense() {
        let calls = [
            call("Bash", "1", result: nil), call("Read", "2"), call("Bash", "3"),
        ]
        #expect(ToolActivity.summary(calls, running: true) == "Running 2 commands, reading 1 file")
    }

    @Test func finishedGroupsSpeakInThePastTenseInOrderOfAppearance() {
        let calls = [
            call("Bash", "1"), call("Read", "2"), call("Bash", "3"), call("Edit", "4"),
            call("Read", "5"), call("Bash", "6"),
        ]
        #expect(
            ToolActivity.summary(calls, running: false)
                == "Ran 3 commands, read 2 files, edited 1 file")
    }

    @Test func everyKindHasItsWords() {
        let calls = [
            call("Write", "1"), call("MultiEdit", "2"), call("NotebookEdit", "3"),
            call("Grep", "4"), call("Glob", "5"), call("WebFetch", "6"), call("WebSearch", "7"),
            call("TodoWrite", "8"), call("TodoWrite", "9"), call("mcp__github__get_issue", "10"),
        ]
        #expect(
            ToolActivity.summary(calls, running: false)
                == "Edited 3 files, searched for 2 patterns, fetched 2 pages, used TodoWrite 2 times, used get_issue"
        )
        #expect(
            ToolActivity.summary(Array(calls.prefix(8)), running: true)
                == "Editing 3 files, searching for 2 patterns, fetching 2 pages, using TodoWrite")
        #expect(
            ToolActivity.summary([call("Grep", "1"), call("WebFetch", "2")], running: true)
                == "Searching for 1 pattern, fetching 1 page")
    }

    @Test func failedCallsAreCounted() {
        let calls = [
            call("Bash", "1", isError: true), call("Bash", "2"), call("Read", "3", isError: true),
        ]
        #expect(
            ToolActivity.summary(calls, running: false) == "Ran 2 commands, read 1 file, 2 failed")
        #expect(
            ToolActivity.summary(Array(calls.prefix(2)), running: false)
                == "Ran 2 commands, 1 failed")
    }

    @Test func agentsSayHowManyAreDone() {
        let agents = [
            call("Task", "1"), call("Agent", "2", result: nil), call("Agent", "3"),
        ]
        #expect(ToolActivity.summary(agents, running: true) == "Running 3 agents, 2 done")
        #expect(ToolActivity.summary(agents, running: false) == "Ran 3 agents")
        let none = [call("Agent", "1", result: nil), call("Agent", "2", result: nil)]
        #expect(ToolActivity.summary(none, running: true) == "Running 2 agents")
        #expect(
            ToolActivity.summary(
                [call("Agent", "1"), call("Bash", "2", result: nil)], running: true)
                == "Running 1 agent, 1 done, running 1 command")
    }
}

@Suite struct TranscriptGroupingTests {
    func shape(_ entries: [TranscriptEntry]) -> [String] {
        entries.map { entry in
            switch entry {
            case .item(let item): item.id
            case .tools(let group): "[\(group.items.map(\.id).joined(separator: " "))]"
            }
        }
    }

    @Test func consecutiveToolsCollapseUntilAssistantText() throws {
        let items = [
            text("a"), tool("Bash", "t1"), thought("th"), tool("Read", "t2"), thought("tail"),
            text("b"), tool("Read", "t3"), text("c"),
        ]
        let entries = TranscriptGrouping.entries(items, live: false)
        #expect(shape(entries) == ["a", "[t1 th t2]", "tail", "b", "t3", "c"])
        #expect(entries[1].id == "tools-t1")
        guard case .tools(let group) = entries[1] else { throw Unexpected(entries[1]) }
        #expect(group.calls.map(\.id) == ["t1", "t2"])
        #expect(!group.isRunning)
        #expect(group.summary == "Ran 1 command, read 1 file")
        #expect(entries[0].id == "a")
    }

    @Test func aLoneToolKeepsItsThinkingAsPlainRows() {
        let items = [tool("Bash", "t1"), thought("th"), text("a")]
        #expect(shape(TranscriptGrouping.entries(items, live: true)) == ["t1", "th", "a"])
        #expect(shape(TranscriptGrouping.entries([], live: true)).isEmpty)
    }

    @Test func otherItemsBreakAGroup() {
        let approval = TranscriptItem(
            id: "ap", content: .approval(id: "ap", kind: .permission, status: .pending), eventID: 2)
        let items = [
            tool("Bash", "t1"), tool("Bash", "t2"), approval, tool("Bash", "t3"), end("end"),
            tool("Bash", "t4"), tool("Read", "t5"),
        ]
        #expect(
            shape(TranscriptGrouping.entries(items, live: false))
                == ["[t1 t2]", "ap", "t3", "end", "[t4 t5]"])
    }

    @Test func onlyToolsOfTheOpenTurnRunWhileLive() throws {
        let items = [
            tool("Bash", "t1", result: nil), tool("Read", "t2"), end("end"),
            tool("Bash", "t3", result: nil), tool("Read", "t4"),
        ]
        let live = TranscriptGrouping.entries(items, live: true)
        guard case .tools(let old) = live[0], case .tools(let open) = live[2] else {
            throw Unexpected(live)
        }
        #expect(!old.isRunning)
        #expect(old.summary == "Ran 1 command, read 1 file")
        #expect(open.isRunning)
        #expect(open.summary == "Running 1 command, reading 1 file")

        guard case .tools(let idle) = TranscriptGrouping.entries(items, live: false)[2] else {
            throw Unexpected(items)
        }
        #expect(!idle.isRunning)
    }

    @Test func findsTheGroupHoldingAnItem() {
        let entries = TranscriptGrouping.entries(
            [text("a"), tool("Bash", "t1"), thought("th"), tool("Bash", "t2")], live: false)
        #expect(TranscriptGrouping.group(containing: "th", in: entries) == "tools-t1")
        #expect(TranscriptGrouping.group(containing: "a", in: entries) == nil)
        #expect(TranscriptGrouping.group(containing: "none", in: entries) == nil)
    }
}

@MainActor
@Suite struct TurnTimingTests {
    let api = FakeAPI()

    func event(_ type: String, _ payload: String, id: Int?, at second: Int) -> Event {
        Fixture.event(type, payload, id: id, ts: String(format: "2026-10-06T09:00:%02dZ", second))
    }

    func user(_ id: Int, at second: Int) -> Event {
        event(
            EventType.sessionUserMessage, #"{"text": "go", "attachments": []}"#, id: id, at: second)
    }

    func state(_ name: String, _ id: Int, at second: Int) -> Event {
        event(EventType.sessionState, #"{"state": "\#(name)", "error": null}"#, id: id, at: second)
    }

    func result(_ id: Int, at second: Int, duration: String = "null", error: Bool = false) -> Event
    {
        event(
            EventType.sessionResult,
            #"{"is_error": \#(error), "subtype": "success", "duration_ms": \#(duration), "num_turns": 1, "cost_usd": null, "errors": []}"#,
            id: id, at: second)
    }

    func message(_ blocks: String, _ id: Int, at second: Int) -> Event {
        event(
            EventType.sessionMessage, #"{"blocks": [\#(blocks)], "parent_tool_use_id": null}"#,
            id: id, at: second)
    }

    func loaded() async throws -> TranscriptStore {
        let transcript = TranscriptStore(sessionID: "s1", api: api)
        try await transcript.load()
        return transcript
    }

    func ends(_ transcript: TranscriptStore) -> [TurnEnd] {
        transcript.items.compactMap {
            if case .turnEnd(let end) = $0.content { end } else { nil }
        }
    }

    @Test func aTurnRunsFromTheUserMessageToItsResult() async throws {
        let transcript = try await loaded()
        #expect(transcript.turnStartedAt == nil)
        transcript.receive(user(1, at: 0))
        transcript.receive(state("running", 2, at: 1))
        #expect(transcript.turnStartedAt == Fixture.date("2026-10-06T09:00:00Z"))

        transcript.receive(result(3, at: 30, duration: "12500"))
        #expect(transcript.turnStartedAt == nil)
        #expect(ends(transcript) == [TurnEnd(durationMS: 12_500, stopped: false)])
        #expect(transcript.items.map(\.id) == ["e1", "e3-end", "e3"])
        #expect(transcript.visibleItems.map(\.id) == ["e1", "e3-end"])
    }

    @Test func withoutADurationTheTimestampsTell() async throws {
        let transcript = try await loaded()
        transcript.receive(user(1, at: 0))
        transcript.receive(result(2, at: 40, error: true))
        #expect(ends(transcript) == [TurnEnd(durationMS: 40_000, stopped: true)])
        #expect(transcript.visibleItems.map(\.id) == ["e1", "e2-end", "e2"])
    }

    @Test func aResultWithoutAKnownStartGetsNoEndLine() async throws {
        let transcript = try await loaded()
        transcript.receive(result(1, at: 40))
        transcript.receive(result(2, at: 41, duration: "900"))
        #expect(ends(transcript) == [TurnEnd(durationMS: 900, stopped: false)])
    }

    @Test func theAgentCanStartATurnOnItsOwn() async throws {
        let transcript = try await loaded()
        transcript.receive(state("running", 1, at: 5))
        transcript.receive(state("waiting", 2, at: 6))
        transcript.receive(state("running", 3, at: 9))
        #expect(transcript.turnStartedAt == Fixture.date("2026-10-06T09:00:05Z"))
        transcript.receive(user(4, at: 10))
        #expect(transcript.turnStartedAt == Fixture.date("2026-10-06T09:00:05Z"))
        // Going idle without a result ends the turn, timed from its start.
        transcript.receive(state("idle", 5, at: 12))
        #expect(transcript.turnStartedAt == nil)
        #expect(ends(transcript) == [TurnEnd(durationMS: 7_000, stopped: false)])
    }

    @Test func anInterruptionStopsTheOpenTurn() async throws {
        let transcript = try await loaded()
        transcript.receive(user(1, at: 0))
        transcript.receive(state("interrupted", 2, at: 7))
        #expect(transcript.turnStartedAt == nil)
        #expect(ends(transcript) == [TurnEnd(durationMS: 7_000, stopped: true)])
        #expect(transcript.items.map(\.id) == ["e1", "e2-end", "e2"])
    }

    @Test func anInterruptionAfterTheResultMarksThatTurnStopped() async throws {
        let transcript = try await loaded()
        transcript.receive(user(1, at: 0))
        transcript.receive(result(2, at: 7, duration: "6000"))
        transcript.receive(state("failed", 3, at: 8))
        #expect(ends(transcript) == [TurnEnd(durationMS: 6_000, stopped: true)])

        // A later turn's interruption leaves the earlier end alone.
        transcript.receive(user(4, at: 10))
        transcript.receive(state("interrupted", 5, at: 12))
        transcript.receive(state("interrupted", 6, at: 13))
        #expect(
            ends(transcript) == [
                TurnEnd(durationMS: 6_000, stopped: true),
                TurnEnd(durationMS: 2_000, stopped: true),
            ])
    }

    @Test func anInterruptionWithoutATurnIsOnlyANotice() async throws {
        let transcript = try await loaded()
        transcript.receive(state("interrupted", 1, at: 0))
        #expect(transcript.items.map(\.content) == [.notice("Interrupted")])
    }

    @Test func thinkingKeepsItsDurationAndShowsWhileItHasOne() async throws {
        let transcript = try await loaded()
        transcript.receive(user(1, at: 0))
        #expect(!transcript.isThinking)
        transcript.receive(
            message(
                #"{"type": "thinking", "text": "", "duration_ms": 8000}, {"type": "thinking", "text": " "}"#,
                2, at: 3))
        #expect(transcript.isThinking)
        #expect(
            transcript.items.map(\.content).suffix(2) == [
                .thinking("", durationMS: 8_000), .thinking(" ", durationMS: nil),
            ])
        #expect(transcript.visibleItems.map(\.id) == ["e1", "e2-0"])

        transcript.receive(result(3, at: 9))
        #expect(!transcript.isThinking)
    }

    func thinking(_ active: Bool, at second: Int) -> Event {
        event(EventType.sessionThinking, #"{"active": \#(active)}"#, id: nil, at: second)
    }

    /// The daemon marks a thinking block's start and end (D045); a finished block is not
    /// thinking any more.
    @Test func theDaemonsThinkingEventsDriveTheLabel() async throws {
        let transcript = try await loaded()
        transcript.receive(user(1, at: 0))
        transcript.receive(thinking(true, at: 1))
        #expect(transcript.isThinking)
        transcript.receive(thinking(false, at: 4))
        #expect(!transcript.isThinking)

        // The finished block arrives after its end: still working, not thinking.
        transcript.receive(thinking(true, at: 5))
        transcript.receive(
            message(#"{"type": "thinking", "text": "hm", "duration_ms": 3000}"#, 2, at: 8))
        #expect(!transcript.isThinking)

        // The next result or state clears a mark whose end never came.
        transcript.receive(thinking(true, at: 9))
        transcript.receive(result(3, at: 10))
        #expect(!transcript.isThinking)
        transcript.receive(user(4, at: 11))
        transcript.receive(thinking(true, at: 12))
        transcript.receive(state("interrupted", 5, at: 13))
        #expect(!transcript.isThinking)
    }

    @Test func thinkingThatStartsBeforeTheHistoryLoadsShows() async throws {
        api.set { $0.events["s1"] = [user(1, at: 0)] }
        let transcript = TranscriptStore(sessionID: "s1", api: api)
        transcript.receive(thinking(true, at: 2))
        try await transcript.load()
        #expect(transcript.isThinking)
    }

    @Test func aReloadStartsTheTurnsOver() async throws {
        let events = [user(1, at: 0), result(2, at: 4), user(3, at: 6)]
        api.set { $0.claudeChatEvents["c1"] = events }
        let transcript = TranscriptStore(sessionID: "c1", api: api, source: .claudeChat)
        try await transcript.load()
        #expect(transcript.turnStartedAt == Fixture.date("2026-10-06T09:00:06Z"))
        api.set { $0.claudeChatEvents["c1"] = Array(events.prefix(2)) }
        try await transcript.load()
        #expect(transcript.turnStartedAt == nil)
        #expect(ends(transcript).count == 1)
    }

    /// The daemon marks a turn's start and measures the turn in its end state (D045).
    func marked(_ name: String, _ extra: String, _ id: Int, at second: Int) -> Event {
        event(
            EventType.sessionState, #"{"state": "\#(name)", "error": null, \#(extra)}"#, id: id,
            at: second)
    }

    @Test func theDaemonsMarksStartAndMeasureTheTurn() async throws {
        let transcript = try await loaded()
        transcript.receive(user(1, at: 0))
        transcript.receive(marked("running", #""turn_start": true"#, 2, at: 2))
        #expect(transcript.turnStartedAt == Fixture.date("2026-10-06T09:00:02Z"))
        transcript.receive(result(3, at: 20, duration: "15000"))
        transcript.receive(marked("idle", #""duration_ms": 18250"#, 4, at: 21))
        #expect(ends(transcript) == [TurnEnd(durationMS: 18_250, stopped: false)])

        // A turn the agent starts by itself, stopped before any result.
        transcript.receive(marked("running", #""turn_start": true"#, 5, at: 30))
        transcript.receive(marked("interrupted", #""duration_ms": 4100"#, 6, at: 35))
        #expect(ends(transcript).last == TurnEnd(durationMS: 4_100, stopped: true))

        // An idle state without a measure keeps the result's.
        transcript.receive(user(7, at: 40))
        transcript.receive(result(8, at: 45, duration: "5000"))
        transcript.receive(state("idle", 9, at: 46))
        #expect(ends(transcript).last == TurnEnd(durationMS: 5_000, stopped: false))
    }

    @Test func theExchangeRunsFromTheUsersLatestMessage() async throws {
        let transcript = try await loaded()
        #expect(transcript.exchangeStartedAt == nil)
        transcript.receive(user(1, at: 0))
        transcript.receive(marked("running", #""turn_start": true"#, 2, at: 1))
        #expect(transcript.exchangeStartedAt == Fixture.date("2026-10-06T09:00:00Z"))
        transcript.receive(result(3, at: 20))
        transcript.receive(state("idle", 4, at: 21))
        #expect(transcript.exchangeStartedAt == Fixture.date("2026-10-06T09:00:00Z"))

        // The agent going on by itself, after a background task finished, stays in it.
        transcript.receive(marked("running", #""turn_start": true"#, 5, at: 30))
        #expect(transcript.exchangeStartedAt == Fixture.date("2026-10-06T09:00:00Z"))

        // A message sent while that turn runs opens the next exchange.
        transcript.receive(user(6, at: 35))
        #expect(transcript.exchangeStartedAt == Fixture.date("2026-10-06T09:00:35Z"))
    }

    @Test func aReloadedClaudeChatFindsItsExchangeAgain() async throws {
        let events = [user(1, at: 0), result(2, at: 5), user(3, at: 9)]
        api.set { $0.claudeChatEvents["c1"] = events }
        let transcript = TranscriptStore(sessionID: "c1", api: api, source: .claudeChat)
        try await transcript.load()
        #expect(transcript.exchangeStartedAt == Fixture.date("2026-10-06T09:00:09Z"))
        api.set { $0.claudeChatEvents["c1"] = [] }
        try await transcript.load()
        #expect(transcript.exchangeStartedAt == nil)
    }

    @Test func anIdleTurnWithoutAResultEndsWithTheDaemonsMeasure() async throws {
        let transcript = try await loaded()
        transcript.receive(marked("running", #""turn_start": true"#, 1, at: 0))
        transcript.receive(marked("idle", #""duration_ms": 3000"#, 2, at: 9))
        #expect(ends(transcript) == [TurnEnd(durationMS: 3_000, stopped: false)])
        #expect(transcript.turnStartedAt == nil)
    }
}

/// The background bar's exchange starts at the session's latest user message, whatever
/// page of the transcript is loaded.
@MainActor
@Suite struct ExchangeStartTests {
    let api = FakeAPI()

    /// Event `id` at that many seconds after 09:00: user messages at `users`, agent text
    /// everywhere else, up to `count` events in session "x".
    func history(_ count: Int, users: Set<Int>) -> [Event] {
        (1...count).map { users.contains($0) ? Self.user($0) : Self.reply($0) }
    }

    static func ts(_ second: Int) -> String {
        String(format: "2026-10-06T09:%02d:%02dZ", second / 60, second % 60)
    }

    static func at(_ second: Int) -> Date {
        Fixture.date(ts(second))
    }

    static func user(_ id: Int) -> Event {
        Fixture.event(
            EventType.sessionUserMessage, #"{"text": "go", "attachments": []}"#, id: id,
            session: "x", ts: ts(id))
    }

    static func reply(_ id: Int) -> Event {
        Fixture.event(
            EventType.sessionMessage,
            #"{"blocks": [{"type": "text", "text": "ok"}], "parent_tool_use_id": null}"#,
            id: id, session: "x", ts: ts(id))
    }

    func jumped(to event: Int, in events: [Event]) async throws -> TranscriptStore {
        api.set { $0.events["x"] = events }
        let transcript = TranscriptStore(sessionID: "x", api: api)
        transcript.requestFocus(event: event)
        try await transcript.load()
        return transcript
    }

    static let newest = "before=\(Int.max) limit=100"

    @Test func aSearchPageFindsTheLatestUserMessageAfterIt() async throws {
        let transcript = try await jumped(to: 20, in: history(250, users: [1, 200]))
        #expect(transcript.hasNewer)
        #expect(transcript.exchangeStartedAt == Self.at(200))
        #expect(api.calls.last == "sessionEvents x after=120 \(Self.newest)")
    }

    @Test func theLookupReadsBackPageByPageUntilAMessage() async throws {
        let transcript = try await jumped(to: 20, in: history(400, users: [1, 150]))
        #expect(transcript.exchangeStartedAt == Self.at(150))
        #expect(
            api.calls.suffix(3) == [
                "sessionEvents x after=120 \(Self.newest)",
                "sessionEvents x after=120 before=301 limit=100",
                "sessionEvents x after=120 before=201 limit=100",
            ])
    }

    @Test func withoutAMessageAfterThePageItsOwnLatestStarts() async throws {
        let transcript = try await jumped(to: 20, in: history(250, users: [1, 3]))
        #expect(transcript.exchangeStartedAt == Self.at(3))
        #expect(api.calls.last == "sessionEvents x after=120 before=151 limit=100")
    }

    @Test func pagesAndLiveMessagesKeepTheLatestStart() async throws {
        let transcript = try await jumped(to: 20, in: history(250, users: [1, 200]))
        transcript.requestFocus(event: 240)
        _ = try await transcript.resolveFocus()
        #expect(!transcript.hasNewer)

        // A search hit's page holds only an older message; the start stays, without
        // looking it up again.
        transcript.requestFocus(event: 5)
        _ = try await transcript.resolveFocus()
        #expect(transcript.hasNewer)
        #expect(transcript.exchangeStartedAt == Self.at(200))
        #expect(api.calls.count == 7)

        // A message sent while that page shows opens the next exchange.
        transcript.receive(Self.user(251))
        #expect(transcript.exchangeStartedAt == Self.at(251))
        try await transcript.loadNewer()
        #expect(transcript.exchangeStartedAt == Self.at(251))
    }

    @Test func aLiveMessageBeforeTheFirstLoadIsTheLatest() async throws {
        api.set { $0.events["x"] = history(250, users: [1, 150]) }
        let transcript = TranscriptStore(sessionID: "x", api: api)
        transcript.receive(Self.user(251))
        transcript.requestFocus(event: 20)
        try await transcript.load()
        #expect(transcript.exchangeStartedAt == Self.at(251))
        #expect(api.calls.count == 2)
    }

    @Test func untilTheStartIsKnownTheBarShowsOnlyTasksAtWork() async throws {
        let summary = try #require(Fixture.sessionDetail.background)
        api.set { $0.events["x"] = [] }
        let transcript = TranscriptStore(sessionID: "x", api: api)
        #expect(transcript.exchange(of: summary).items.map(\.id) == ["toolu_10"])

        // Loaded without any user message, every task counts.
        try await transcript.load()
        #expect(transcript.exchange(of: summary) == summary)

        transcript.receive(
            Fixture.event(
                EventType.sessionUserMessage, #"{"text": "go", "attachments": []}"#, id: 1,
                session: "x", ts: "2026-10-06T09:13:05Z"))
        #expect(transcript.exchange(of: summary).items.map(\.id) == ["toolu_10", "toolu_11"])
    }
}
