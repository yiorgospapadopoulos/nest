import Foundation
import Testing

@testable import NestKit

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

    @Test func agentsStillWorkingInTheBackgroundAreNotDone() {
        let agents = [call("Agent", "1"), call("Agent", "2"), call("Agent", "3")]
        #expect(
            ToolActivity.summary(agents, running: true, background: ["2", "3"])
                == "Running 3 agents, 1 done")
    }
}

@Suite struct TranscriptGroupingTests {
    func shape(_ entries: [TranscriptEntry]) -> [String] {
        entries.map { entry in
            switch entry {
            case .item(let item): item.id
            case .tools(let group): "[\(group.items.map(\.id).joined(separator: " "))]"
            case .pixieCall(let call): "@\(call.slug)"
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

    @Test func aCallWhoseBackgroundTaskStillRunsKeepsItsGroupRunning() throws {
        // Background agents return at once; their tasks run on after the turn ends.
        let items = [
            tool("Agent", "a1"), tool("Agent", "a2"), tool("Agent", "a3"), end("end"),
            tool("Bash", "b1"), tool("Read", "r1"),
        ]
        let entries = TranscriptGrouping.entries(
            items, live: false, background: ["a2", "a3", "elsewhere"])
        guard case .tools(let agents) = entries[0], case .tools(let later) = entries[2] else {
            throw Unexpected(entries)
        }
        #expect(agents.isRunning)
        #expect(agents.summary == "Running 3 agents, 1 done")
        #expect(!later.isRunning)

        guard case .tools(let finished) = TranscriptGrouping.entries(items, live: false)[0]
        else { throw Unexpected(items) }
        #expect(!finished.isRunning)
        #expect(finished.summary == "Ran 3 agents")
    }

    /// A call its turn's end cut off shows as stopped, not running forever (audit
    /// BUG-75, D054); one whose background task runs, or of the open turn, still runs.
    @Test func callsWithoutAResultStopWhenTheirTurnEnds() throws {
        func stopped(_ entries: [TranscriptEntry]) -> [String] {
            entries.flatMap { entry -> [ToolCall] in
                switch entry {
                case .item(let item):
                    if case .tool(let call) = item.content { [call] } else { [] }
                case .tools(let group): group.calls
                case .pixieCall(let call): [call.call]
                }
            }.filter(\.stopped).map(\.id)
        }
        let items = [
            tool("Bash", "lone", result: nil), text("a"), tool("Bash", "t1", result: nil),
            tool("Agent", "bg", result: nil), tool("Read", "t2"), end("end"),
            tool("Bash", "open", result: nil),
        ]
        #expect(
            stopped(TranscriptGrouping.entries(items, live: true, background: ["bg"]))
                == ["lone", "t1"])
        #expect(
            stopped(TranscriptGrouping.entries(items, live: false))
                == ["lone", "t1", "bg", "open"])
        // A new message starts a turn, so the calls before it stopped, even when the
        // interrupted turn's length was unknown and it got no end line.
        let user = TranscriptItem(id: "u", content: .user(text: "go", attachments: []), eventID: 2)
        let next = [tool("Bash", "old", result: nil), user, tool("Bash", "new", result: nil)]
        #expect(stopped(TranscriptGrouping.entries(next, live: true)) == ["old"])
    }

    @Test func findsTheGroupHoldingAnItem() {
        let entries = TranscriptGrouping.entries(
            [text("a"), tool("Bash", "t1"), thought("th"), tool("Bash", "t2")], live: false)
        #expect(TranscriptGrouping.group(containing: "th", in: entries) == "tools-t1")
        #expect(TranscriptGrouping.group(containing: "a", in: entries) == nil)
        #expect(TranscriptGrouping.group(containing: "none", in: entries) == nil)
    }

    func item(_ id: String, _ content: TranscriptItem.Content) -> TranscriptItem {
        TranscriptItem(id: id, content: content, eventID: 1)
    }

    /// Each row of a finished reply leads to its "Worked for" line, shown on hover (B71):
    /// from the message or report that started the turn, exclusive, to the turn's end,
    /// inclusive. The open turn's rows lead nowhere.
    @Test func eachRowOfAFinishedReplyLeadsToItsTurnEnd() {
        let pixie = ToolCall(
            id: "p1", name: "Agent", input: .object(["subagent_type": .string("rex")]),
            result: "done", isError: false)
        let items = [
            text("early"), end("e0"),
            item("u1", .user(text: "go", attachments: [])), text("a"), tool("Bash", "t1"),
            tool("Read", "t2"), item("p1", .tool(pixie)), end("e1"),
            item("r1", .reportBack("back")), thought("th"), end("e2"),
            item("h1", .habitReport("ran")), text("b"), end("e3"),
            item("u2", .user(text: "more", attachments: [])), text("c"), tool("Bash", "t3"),
        ]
        let entries = TranscriptGrouping.entries(items, live: true, pixies: ["rex"])
        #expect(
            TranscriptGrouping.turnEnds(entries) == [
                "early": "e0", "e0": "e0",
                "a": "e1", "tools-t1": "e1", "p1": "e1", "e1": "e1",
                "th": "e2", "e2": "e2",
                "b": "e3", "e3": "e3",
            ])
        #expect(TranscriptGrouping.turnEnds([]).isEmpty)
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

    @Test func anInterruptionStopsTheOpenTurnWithTheDaemonsMeasure() async throws {
        let transcript = try await loaded()
        transcript.receive(user(1, at: 0))
        transcript.receive(marked("interrupted", #""duration_ms": 7000"#, 2, at: 30))
        #expect(transcript.turnStartedAt == nil)
        #expect(ends(transcript) == [TurnEnd(durationMS: 7_000, stopped: true)])
        // "Stopped after 7s" says it all; "Interrupted" is only for an unknown length.
        #expect(transcript.items.map(\.id) == ["e1", "e2-end"])
    }

    /// After a crash or a restart the daemon cannot tell how long the turn ran; the time
    /// between the events would count the downtime too (audit BUG-76).
    @Test func aTurnOfUnknownLengthIsInterruptedNotTimed() async throws {
        let transcript = try await loaded()
        transcript.receive(user(1, at: 0))
        // The daemon's recovery sends no measure at all.
        transcript.receive(state("interrupted", 2, at: 50))
        #expect(transcript.turnStartedAt == nil)
        #expect(ends(transcript).isEmpty)
        #expect(transcript.items.map(\.content).last == .notice("Interrupted"))

        // An explicit null is unknown too, for any end.
        transcript.receive(user(3, at: 51))
        transcript.receive(marked("idle", #""duration_ms": null"#, 4, at: 59))
        transcript.receive(user(5, at: 60))
        transcript.receive(marked("failed", #""duration_ms": null"#, 6, at: 64))
        #expect(ends(transcript).isEmpty)
        #expect(transcript.turnStartedAt == nil)
    }

    @Test func aTurnThatEndsInAnErrorFailsWithItsReason() async throws {
        let transcript = try await loaded()
        transcript.receive(user(1, at: 0))
        transcript.receive(
            event(
                EventType.sessionResult,
                #"{"is_error": true, "subtype": "error_during_execution", "duration_ms": 5000, "num_turns": 1, "cost_usd": null, "errors": ["Usage limit reached"]}"#,
                id: 2, at: 5))
        transcript.receive(
            event(
                EventType.sessionState,
                #"{"state": "failed", "error": "Usage limit reached", "duration_ms": 5200}"#,
                id: 3, at: 6))

        #expect(
            transcript.visibleItems.map(\.content) == [
                .user(text: "go", attachments: []),
                .turnEnd(TurnEnd(durationMS: 5_200, stopped: true)),
                .notice("Failed: Usage limit reached"),
            ])

        // The next turn's failure leaves this one's lines alone.
        transcript.receive(user(4, at: 10))
        transcript.receive(state("failed", 5, at: 12))
        #expect(transcript.visibleItems.count == 6)
        #expect(transcript.visibleItems.last?.content == .notice("Failed"))
    }

    @Test func anOlderErrorTurnKeepsItsResultLine() async throws {
        let transcript = try await loaded()
        transcript.receive(user(1, at: 0))
        for (id, errors) in [(2, #"["API Error: 529"]"#), (3, "[]")] {
            transcript.receive(
                event(
                    EventType.sessionResult,
                    #"{"is_error": true, "subtype": "error_max_turns", "duration_ms": 4000, "num_turns": 1, "cost_usd": null, "errors": \#(errors)}"#,
                    id: id, at: 4))
        }
        transcript.receive(state("idle", 4, at: 5))
        let failures = transcript.visibleItems.compactMap { item in
            if case .result(let result) = item.content { result.failure } else { nil }
        }
        #expect(failures == ["Failed: API Error: 529", "Failed: error_max_turns"])
    }

    /// Send now, or Claude Code ending a turn holding the next message: the result made
    /// way for that message and is no failure (B59).
    @Test func aResultThatHandsOffShowsNoFailure() async throws {
        let transcript = try await loaded()
        transcript.receive(user(1, at: 0))
        transcript.receive(
            event(
                EventType.sessionResult,
                #"{"is_error": true, "subtype": "error_during_execution", "duration_ms": 8000, "num_turns": 3, "errors": ["[ede_diagnostic] result_type=user"], "handoff": true}"#,
                id: 2, at: 8))
        transcript.receive(user(3, at: 9))
        #expect(ends(transcript) == [TurnEnd(durationMS: 8_000, stopped: false)])
        #expect(
            !transcript.visibleItems.contains { item in
                if case .result = item.content { true } else { false }
            })
    }

    /// A turn the user stopped shows only its stopped line, never "Failed:" (B59).
    @Test func aStoppedTurnsErrorResultIsNoFailure() async throws {
        let transcript = try await loaded()
        transcript.receive(user(1, at: 0))
        transcript.receive(
            event(
                EventType.sessionResult,
                #"{"is_error": true, "subtype": "error_during_execution", "duration_ms": 3000, "num_turns": 1, "errors": ["[ede_diagnostic] result_type=user"], "stopped": true}"#,
                id: 2, at: 3))
        transcript.receive(state("interrupted", 3, at: 4))
        #expect(ends(transcript) == [TurnEnd(durationMS: 3_000, stopped: true)])
        #expect(
            !transcript.visibleItems.contains { item in
                if case .result = item.content { true } else { false }
            })
        #expect(!transcript.items.contains { $0.content == .notice("Interrupted") })
    }

    @Test func anInterruptionAfterTheResultMarksThatTurnStopped() async throws {
        let transcript = try await loaded()
        transcript.receive(user(1, at: 0))
        transcript.receive(result(2, at: 7, duration: "6000"))
        transcript.receive(state("failed", 3, at: 8))
        #expect(ends(transcript) == [TurnEnd(durationMS: 6_000, stopped: true)])

        // A later turn's interruption leaves the earlier end alone.
        transcript.receive(user(4, at: 10))
        transcript.receive(marked("interrupted", #""duration_ms": 2000"#, 5, at: 12))
        transcript.receive(marked("interrupted", #""duration_ms": 2100"#, 6, at: 13))
        #expect(
            ends(transcript) == [
                TurnEnd(durationMS: 6_000, stopped: true),
                TurnEnd(durationMS: 2_100, stopped: true),
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

    @Test func anIdleTurnWithoutAResultEndsWithTheDaemonsMeasure() async throws {
        let transcript = try await loaded()
        transcript.receive(marked("running", #""turn_start": true"#, 1, at: 0))
        transcript.receive(marked("idle", #""duration_ms": 3000"#, 2, at: 9))
        #expect(ends(transcript) == [TurnEnd(durationMS: 3_000, stopped: false)])
        #expect(transcript.turnStartedAt == nil)
    }
}

@MainActor
@Suite struct TranscriptRowsTests {
    let api = FakeAPI()

    static func ts(_ second: Int) -> String {
        String(format: "2026-10-06T09:%02d:%02dZ", second / 60, second % 60)
    }

    static func reply(_ id: Int) -> Event {
        Fixture.event(
            EventType.sessionMessage,
            #"{"blocks": [{"type": "text", "text": "ok"}], "parent_tool_use_id": null}"#,
            id: id, session: "x", ts: ts(id))
    }

    static func toolUse(_ id: Int, tool: String, at second: Int) -> Event {
        Fixture.event(
            EventType.sessionMessage,
            #"{"blocks": [{"type": "tool_use", "id": "\#(tool)", "name": "Bash", "input": {}}], "parent_tool_use_id": null}"#,
            id: id, session: "x", ts: ts(second))
    }

    /// The rows are kept until the items or the arguments change (IMP-11).
    @Test func visibleItemsAndRowsFollowEachChange() async throws {
        api.set {
            $0.events["x"] = [Self.toolUse(1, tool: "a", at: 0), Self.toolUse(2, tool: "b", at: 1)]
        }
        let transcript = TranscriptStore(sessionID: "x", api: api)
        try await transcript.load()
        #expect(transcript.visibleItems.map(\.id) == ["a", "b"])
        #expect(transcript.visibleItems.map(\.id) == ["a", "b"])

        let live = transcript.entries(live: true)
        #expect(live == transcript.entries(live: true))
        guard case .tools(let group) = live.first else {
            Issue.record("the two calls are one row")
            return
        }
        #expect(group.isRunning)
        guard case .tools(let stopped) = transcript.entries(live: false).first else {
            Issue.record("the two calls are one row")
            return
        }
        #expect(!stopped.isRunning)
        guard case .tools(let working) = transcript.entries(live: false, background: ["a"]).first
        else {
            Issue.record("the two calls are one row")
            return
        }
        #expect(working.isRunning)

        transcript.receive(Self.reply(3))
        #expect(transcript.visibleItems.map(\.id) == ["a", "b", "e3-0"])
        #expect(transcript.entries(live: false).count == 2)
    }
}
