import Foundation
import Testing

@testable import NestKit

private func message(_ blocks: String, parent: String? = nil, id: Int) -> Event {
    let parentJSON = parent.map { "\"\($0)\"" } ?? "null"
    return Fixture.event(
        EventType.sessionMessage,
        #"{"blocks": [\#(blocks)], "parent_tool_use_id": \#(parentJSON)}"#,
        id: id)
}

private func agentUse(_ id: String, _ subagent: String, tool: String = "Agent") -> String {
    #"{"type": "tool_use", "id": "\#(id)", "name": "\#(tool)", "input": {"subagent_type": "\#(subagent)", "description": "Review"}}"#
}

private func call(_ id: String, _ subagent: String?, name: String = "Agent", result: String? = nil)
    -> TranscriptItem
{
    let input: JSONValue = subagent.map { .object(["subagent_type": .string($0)]) } ?? .object([:])
    return TranscriptItem(
        id: id,
        content: .tool(ToolCall(id: id, name: name, input: input, result: result, isError: false)),
        eventID: 1)
}

@MainActor @Suite struct PixieCallTranscriptTests {
    /// A call's own messages are kept with it: text and tool calls, in order; its thinking
    /// and the results of its own tools are not shown.
    @Test func aCallKeepsItsOwnMessages() async throws {
        let transcript = TranscriptStore(sessionID: "s1", api: FakeAPI())
        try await transcript.load()
        transcript.receive(message(agentUse("toolu_1", "reviewer"), id: 1))
        transcript.receive(
            message(
                #"{"type": "thinking", "text": "hm"}, {"type": "text", "text": "Reading the diff."}, {"type": "tool_use", "id": "sub1", "name": "Read", "input": {"file_path": "src/a.ts"}}"#,
                parent: "toolu_1", id: 2))
        transcript.receive(
            message(
                #"{"type": "tool_result", "tool_use_id": "sub1", "content": "x"}, {"type": "text", "text": "  "}"#,
                parent: "toolu_1", id: 3))
        transcript.receive(
            message(
                #"{"type": "tool_use", "id": "sub2", "name": "Bash", "input": {"command": "npm test"}}, {"type": "text", "text": "Looks good."}"#,
                parent: "toolu_1", id: 4))
        // Another call's messages, or those of a call this page does not hold, go nowhere.
        transcript.receive(
            message(#"{"type": "text", "text": "elsewhere"}"#, parent: "nope", id: 5))
        transcript.receive(
            message(
                #"{"type": "tool_result", "tool_use_id": "toolu_1", "content": "All fine."}"#, id: 6
            ))

        #expect(transcript.items.count == 1)
        guard case .tool(let call) = transcript.items[0].content else {
            throw Unexpected(transcript.items)
        }
        #expect(call.result == "All fine.")
        #expect(call.subagentType == "reviewer")
        #expect(
            call.steps.map(\.kind) == [
                .text("Reading the diff."),
                .tool(name: "Read", input: .object(["file_path": .string("src/a.ts")])),
                .tool(name: "Bash", input: .object(["command": .string("npm test")])),
                .text("Looks good."),
            ])
        #expect(call.steps.map(\.id) == ["e2-1", "e2-2", "e4-0", "e4-1"])
        #expect(
            call.steps.map(\.line) == [
                "Reading the diff.", "Read src/a.ts", "Bash npm test", "Looks good.",
            ])
    }

    /// Only agent calls hold messages: a message naming another tool as its parent is
    /// dropped.
    @Test func otherToolsHoldNoMessages() async throws {
        let transcript = TranscriptStore(sessionID: "s1", api: FakeAPI())
        try await transcript.load()
        transcript.receive(
            message(#"{"type": "tool_use", "id": "b1", "name": "Bash", "input": {}}"#, id: 1))
        transcript.receive(message(#"{"type": "text", "text": "x"}"#, parent: "b1", id: 2))
        guard case .tool(let call) = transcript.items[0].content else {
            throw Unexpected(transcript.items)
        }
        #expect(call.steps.isEmpty)
        #expect(call.subagentType == nil)
    }

    @Test func aPixieCallIsItsOwnRow() throws {
        let items = [
            call("t1", nil, name: "Bash", result: "ok"),
            call("p1", "reviewer", result: "Done."),
            call("t2", nil, name: "Read", result: "ok"),
            call("t3", nil, name: "Read", result: "ok"),
            call("a1", "Explore", result: "ok"),
        ]
        let entries = TranscriptGrouping.entries(items, live: false, pixies: ["reviewer"])
        #expect(entries.map(\.id) == ["t1", "p1", "tools-t2"])
        guard case .pixieCall(let pixieCall) = entries[1] else { throw Unexpected(entries) }
        #expect(pixieCall.slug == "reviewer")
        #expect(pixieCall.call.result == "Done.")
        #expect(!pixieCall.isRunning)
        // Without pixies, or with "Task" as the tool, the same rules as before apply.
        #expect(
            TranscriptGrouping.entries(items, live: false).map(\.id) == ["tools-t1"])
        let task = [call("p1", "reviewer", name: "Task")]
        #expect(
            TranscriptGrouping.entries(task, live: false, pixies: ["reviewer"]).map(\.id) == ["p1"])
        guard
            case .pixieCall = TranscriptGrouping.entries(task, live: false, pixies: ["reviewer"])[0]
        else { throw Unexpected(task) }
    }

    /// A call without an answer runs while its turn does, or while its background task
    /// runs; once the turn ended it is stopped.
    @Test func aPixieCallRunsLikeOtherAgentRows() throws {
        let running = [call("p1", "reviewer")]
        func entry(_ items: [TranscriptItem], live: Bool, background: Set<String> = [])
            throws -> PixieCallEntry
        {
            let entries = TranscriptGrouping.entries(
                items, live: live, background: background, pixies: ["reviewer"])
            guard case .pixieCall(let entry) = entries.last else { throw Unexpected(entries) }
            return entry
        }
        #expect(try entry(running, live: true).isRunning)
        #expect(try !entry(running, live: true).call.stopped)
        let stopped = try entry(running, live: false)
        #expect(!stopped.isRunning)
        #expect(stopped.call.stopped)
        // Its turn ended: stopped even while the chat works on.
        let ended =
            running + [
                TranscriptItem(
                    id: "end", content: .turnEnd(TurnEnd(durationMS: 1, stopped: false)), eventID: 2
                )
            ]
        let endedEntries = TranscriptGrouping.entries(ended, live: true, pixies: ["reviewer"])
        guard case .pixieCall(let endedCall) = endedEntries[0] else { throw Unexpected(ended) }
        #expect(endedCall.call.stopped)
        let answered = [call("p1", "reviewer", result: "Launched")]
        #expect(try entry(answered, live: false, background: ["p1"]).isRunning)
        #expect(try !entry(answered, live: true).isRunning)
    }

    @Test func theStoreKeepsEntriesPerPixieSet() async throws {
        let transcript = TranscriptStore(sessionID: "s1", api: FakeAPI())
        try await transcript.load()
        transcript.receive(message(agentUse("toolu_1", "reviewer"), id: 1))
        #expect(transcript.entries(live: false).map(\.isPixieCall) == [false])
        #expect(transcript.entries(live: false, pixies: ["reviewer"]).map(\.isPixieCall) == [true])
        #expect(transcript.entries(live: false, pixies: ["reviewer"]).map(\.isPixieCall) == [true])
    }

    @Test func aCallNamesItsPixie() {
        var reviewer = Fixture.decode(Pixie.self, "pixie")
        reviewer.slug = "reviewer"
        guard case .tool(let toolCall) = call("p1", "reviewer").content else { return }
        #expect(PixieCalls.pixie(of: toolCall, among: [reviewer]) == reviewer)
        #expect(PixieCalls.pixie(of: toolCall, among: []) == nil)
        #expect(PixieCalls.slugs([reviewer]) == ["reviewer"])
    }
}

extension TranscriptEntry {
    fileprivate var isPixieCall: Bool {
        if case .pixieCall = self { true } else { false }
    }
}

@Suite struct SubagentReportTests {
    /// The hand-back Claude Code stored for a pixie call, as the daemon keeps it.
    static let handBack: String = {
        let message = Fixture.decode(AgentMessage.self, "subagent_handback")
        guard case .toolResult(_, let content, _) = message.blocks[0] else { return "" }
        return content
    }()

    @Test func aHandBackShowsOnlyTheReport() {
        #expect(Self.handBack.hasPrefix("[Subagent hand-back]"))
        #expect(
            SubagentReport.clean(Self.handBack)
                == "I'm New pixie 2 (@new-pixie-2-2), running on Claude Opus 5.5 (`claude-opus-5-5`)."
        )
    }

    @Test func indentationUsageAndTheAgentLineGo() {
        let report = "  First line.\n\n    nested\n plain\n  Last.\n<usage>tool_uses: 0</usage>\n"
        #expect(SubagentReport.clean(report) == "First line.\n\n  nested\n plain\nLast.")
        #expect(SubagentReport.clean("Done.\nagentId: a1 (use SendMessage)\nmore") == "Done.")
        // A usage block that is not at the end stays.
        #expect(
            SubagentReport.clean("Saw <usage>x</usage> in a log.")
                == "Saw <usage>x</usage> in a log.")
        // Without the frame, the "follows" line is plain text.
        #expect(
            SubagentReport.clean("The report follows:\nok") == "The report follows:\nok")
    }

    @Test func nothingLeftFallsBackToTheText() {
        let empty = "[Subagent hand-back] frame. The report follows:\nagentId: a1"
        #expect(SubagentReport.clean(empty) == empty)
        #expect(SubagentReport.clean("") == "")
        // A frame without its "follows" line keeps the whole text.
        #expect(SubagentReport.clean("[Subagent hand-back] cut") == "[Subagent hand-back] cut")
    }

    /// Agent rows' one-line note shows the report's first line; other tools as before.
    @Test func agentNotesUseTheReport() {
        var call = ToolCall(
            id: "a", name: "Agent", input: .object([:]), result: Self.handBack, isError: false)
        #expect(ToolSummary.result(of: call).hasPrefix("I'm New pixie 2 (@new-pixie-2-2)"))
        #expect(ToolSummary.output(of: call) == SubagentReport.clean(Self.handBack))
        call.result = nil
        #expect(ToolSummary.output(of: call) == nil)
        let bash = ToolCall(
            id: "b", name: "Bash", input: .object([:]), result: Self.handBack, isError: false)
        #expect(ToolSummary.result(of: bash).hasPrefix("[Subagent hand-back]"))
        #expect(ToolSummary.output(of: bash) == Self.handBack)
    }
}
