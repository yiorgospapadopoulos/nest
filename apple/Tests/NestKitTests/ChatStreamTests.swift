import Foundation
import Testing

@testable import NestKit

private func message(_ blocks: String, parent: String? = nil, id: Int?) -> Event {
    let parentJSON = parent.map { "\"\($0)\"" } ?? "null"
    return Fixture.event(
        EventType.sessionMessage,
        #"{"blocks": [\#(blocks)], "parent_tool_use_id": \#(parentJSON)}"#, id: id)
}

private func thinkingDelta(_ text: String, parent: String? = nil) -> Event {
    let parentJSON = parent.map { "\"\($0)\"" } ?? "null"
    return Fixture.event(
        EventType.sessionThinkingDelta,
        #"{"text": "\#(text)", "parent_tool_use_id": \#(parentJSON)}"#, id: nil)
}

private func subagentDelta(_ text: String, parent: String) -> Event {
    Fixture.event(
        EventType.sessionSubagentDelta,
        #"{"text": "\#(text)", "parent_tool_use_id": "\#(parent)"}"#,
        id: nil)
}

private func thinking(_ active: Bool) -> Event {
    Fixture.event(EventType.sessionThinking, #"{"active": \#(active)}"#, id: nil)
}

private func state(_ name: String, id: Int) -> Event {
    Fixture.event(EventType.sessionState, #"{"state": "\#(name)"}"#, id: id)
}

private func hook(
    _ name: String, outcome: String = "success", exit: String = "0", message: String? = nil,
    output: String? = nil, id: Int
) -> Event {
    func json(_ text: String?) -> String { text.map { "\"\($0)\"" } ?? "null" }
    return Fixture.event(
        EventType.sessionHook,
        #"{"hook_id": "h", "hook_name": "\#(name)", "hook_event": "PostToolUse", "outcome": "\#(outcome)", "exit_code": \#(exit), "system_message": \#(json(message)), "output": \#(json(output))}"#,
        id: id)
}

private let agentUse =
    #"{"type": "tool_use", "id": "toolu_A", "name": "Agent", "input": {"subagent_type": "Explore", "description": "Find callers"}}"#

@MainActor @Suite struct ThinkingStreamTests {
    let transcript = TranscriptStore(sessionID: "s1", api: FakeAPI())

    /// Thinking text streams while the block runs, and the finished block replaces it.
    @Test func thinkingStreamsUntilTheFinishedBlock() async throws {
        try await transcript.load()
        transcript.receive(state("running", id: 1))
        transcript.receive(thinking(true))
        transcript.receive(thinkingDelta("Let me check "))
        transcript.receive(thinkingDelta("the test"))
        #expect(transcript.liveThinking == "Let me check the test")
        #expect(transcript.isThinking)

        transcript.receive(
            message(
                #"{"type": "thinking", "text": "Let me check the test", "duration_ms": 900}"#, id: 2
            ))
        #expect(transcript.liveThinking.isEmpty)
        #expect(
            transcript.items.map(\.content) == [.thinking("Let me check the test", durationMS: 900)]
        )
    }

    /// A new thinking block, or the session leaving the running state, starts over.
    @Test func theStreamResetsAtANewBlockAndAtTheTurnsEnd() async throws {
        try await transcript.load()
        transcript.receive(state("running", id: 1))
        transcript.receive(thinkingDelta("first"))
        transcript.receive(thinking(true))
        #expect(transcript.liveThinking.isEmpty)
        transcript.receive(thinkingDelta("second"))
        #expect(transcript.liveThinking == "second")
        transcript.receive(state("idle", id: 2))
        #expect(transcript.liveThinking.isEmpty)
        transcript.receive(thinkingDelta("third"))
        transcript.receive(state("interrupted", id: 3))
        #expect(transcript.liveThinking.isEmpty)
        // A text message of the main agent leaves the stream alone.
        transcript.receive(state("running", id: 4))
        transcript.receive(thinkingDelta("fourth"))
        transcript.receive(message(#"{"type": "text", "text": "Hi"}"#, id: 5))
        #expect(transcript.liveThinking == "fourth")
    }

    /// Deltas are live only: before the history loads they are dropped.
    @Test func deltasBeforeTheLoadAreDropped() {
        transcript.receive(thinkingDelta("early"))
        #expect(transcript.liveThinking.isEmpty)
    }

    @Test func theCollapsedRowPreviewsTheLatestLine() {
        #expect(ThinkingPreview.line("") == nil)
        #expect(ThinkingPreview.line("  \n ") == nil)
        #expect(ThinkingPreview.line("One line") == "One line")
        #expect(ThinkingPreview.line("First\nSecond line  \n\n") == "Second line")
    }
}

@MainActor @Suite struct SubagentStreamTests {
    let transcript = TranscriptStore(sessionID: "s1", api: FakeAPI())

    private var call: ToolCall? {
        if case .tool(let call) = transcript.items.first?.content { call } else { nil }
    }

    /// A subagent's text and thinking stream into its agent call, never the main text;
    /// its stored messages replace the streams.
    @Test func subagentTextStreamsIntoItsCall() async throws {
        try await transcript.load()
        transcript.receive(state("running", id: 1))
        transcript.receive(message(agentUse, id: 2))
        transcript.receive(subagentDelta("Found 3 ", parent: "toolu_A"))
        transcript.receive(subagentDelta("call sites", parent: "toolu_A"))
        transcript.receive(thinkingDelta("Where is it", parent: "toolu_A"))
        #expect(call?.liveText == "Found 3 call sites")
        #expect(call?.liveThinking == "Where is it")
        #expect(transcript.liveThinking.isEmpty)
        #expect(transcript.items.count == 1)

        transcript.receive(
            message(
                #"{"type": "thinking", "text": "Where is it", "duration_ms": null}"#,
                parent: "toolu_A", id: 3))
        #expect(call?.liveThinking == "")
        #expect(call?.liveText == "Found 3 call sites")
        transcript.receive(
            message(#"{"type": "text", "text": "Found 3 call sites."}"#, parent: "toolu_A", id: 4))
        #expect(call?.liveText == "")
        #expect(
            call?.steps.map(\.kind) == [.thinking("Where is it"), .text("Found 3 call sites.")])
    }

    /// Deltas of a call the transcript does not hold, or of another tool, go nowhere; the
    /// streams end with the turn.
    @Test func strayDeltasAreDroppedAndStreamsEndWithTheTurn() async throws {
        try await transcript.load()
        transcript.receive(state("running", id: 1))
        transcript.receive(message(agentUse, id: 2))
        transcript.receive(
            message(#"{"type": "tool_use", "id": "b1", "name": "Bash", "input": {}}"#, id: 3))
        transcript.receive(subagentDelta("x", parent: "nope"))
        transcript.receive(subagentDelta("x", parent: "b1"))
        transcript.receive(thinkingDelta("y", parent: "b1"))
        guard case .tool(let bash) = transcript.items[1].content else {
            throw Unexpected(transcript.items)
        }
        #expect(bash.liveText.isEmpty && bash.liveThinking.isEmpty)

        transcript.receive(subagentDelta("Reading", parent: "toolu_A"))
        transcript.receive(thinkingDelta("Hm", parent: "toolu_A"))
        transcript.receive(state("failed", id: 4))
        #expect(call?.liveText == "")
        #expect(call?.liveThinking == "")
    }
}

@MainActor @Suite struct HookRowTests {
    /// Hooks are muted lines at their place in the transcript, and do not start a turn.
    @Test func hooksAreTranscriptLines() async throws {
        let transcript = TranscriptStore(sessionID: "s1", api: FakeAPI())
        try await transcript.load()
        transcript.receive(hook("SessionStart:startup", message: "Loaded", id: 1))
        #expect(transcript.turnStartedAt == nil)
        #expect(
            transcript.visibleItems.map(\.content) == [
                .hook(
                    HookRun(
                        name: "SessionStart:startup", event: "PostToolUse", outcome: .success,
                        exitCode: 0, systemMessage: "Loaded", output: nil))
            ])
        #expect(transcript.items[0].eventID == 1)
    }

    /// Output a hook that succeeded gives Claude (SessionStart, UserPromptSubmit) shows
    /// nothing, as in Claude Code; older chats stored it (B59).
    @Test func aSuccessfulHooksOutputForClaudeIsNotShown() async throws {
        let transcript = TranscriptStore(sessionID: "s1", api: FakeAPI())
        try await transcript.load()
        transcript.receive(hook("UserPromptSubmit", output: "[14:37 EEST]", id: 1))
        transcript.receive(hook("SessionStart:startup", exit: "null", output: "notes", id: 2))
        transcript.receive(hook("Stop", exit: "1", output: "bad config", id: 3))
        transcript.receive(hook("PostToolUse:Edit", outcome: "cancelled", output: "slow", id: 4))
        #expect(transcript.items.map(\.eventID) == [3, 4])
    }

    @Test func aHooksLineSaysWhatItReported() {
        let says = HookRun(
            name: "PostToolUse:Edit", event: "PostToolUse", outcome: .success, exitCode: 0,
            systemMessage: "Formatted 2 files", output: nil)
        #expect(says.title == "PostToolUse:Edit says: Formatted 2 files")
        #expect(says.detail == nil)
        #expect(!says.isFailure)

        let both = HookRun(
            name: "Stop", event: "Stop", outcome: .success, exitCode: 0,
            systemMessage: "Done", output: "log")
        #expect(both.title == "Stop says: Done")
        #expect(both.detail == "log")

        let printed = HookRun(
            name: "PostToolUse:Edit", event: "PostToolUse", outcome: .cancelled, exitCode: nil,
            systemMessage: nil, output: "3 files")
        #expect(printed.title == "PostToolUse:Edit hook output")
        #expect(printed.detail == "3 files")
        #expect(!printed.isFailure)

        let failed = HookRun(
            name: "PreToolUse:Bash", event: "PreToolUse", outcome: .error, exitCode: 2,
            systemMessage: nil, output: "Blocked: run the tests first")
        #expect(failed.isFailure)
        #expect(failed.title == "PreToolUse:Bash hook failed (exit 2)")
        #expect(failed.detail == "Blocked: run the tests first")

        let failedWithMessage = HookRun(
            name: "Stop", event: "Stop", outcome: .error, exitCode: nil,
            systemMessage: "Tests failed", output: "2 failures")
        #expect(failedWithMessage.title == "Stop hook failed")
        #expect(failedWithMessage.detail == "Tests failed\n2 failures")
    }

    /// A hook between tool calls stays inside their group, as thinking does.
    @Test func hooksBetweenToolCallsStayInTheGroup() throws {
        func tool(_ id: String) -> TranscriptItem {
            TranscriptItem(
                id: id,
                content: .tool(
                    ToolCall(
                        id: id, name: "Edit", input: .object([:]), result: "ok", isError: false)),
                eventID: 1)
        }
        let run = HookRun(
            name: "PostToolUse:Edit", event: "PostToolUse", outcome: .success, exitCode: 0,
            systemMessage: "ok", output: nil)
        let hookItem = TranscriptItem(id: "h1", content: .hook(run), eventID: 2)
        let entries = TranscriptGrouping.entries(
            [tool("t1"), hookItem, tool("t2"), hookItem.with(id: "h2")], live: false)
        #expect(entries.map(\.id) == ["tools-t1", "h2"])
        guard case .tools(let group) = entries[0] else { throw Unexpected(entries) }
        #expect(group.items.map(\.id) == ["t1", "h1", "t2"])
        // Alone, it is its own line.
        #expect(TranscriptGrouping.entries([hookItem], live: false).map(\.id) == ["h1"])
    }
}

extension TranscriptItem {
    fileprivate func with(id: String) -> TranscriptItem {
        TranscriptItem(id: id, content: content, eventID: eventID)
    }
}

@Suite struct ToolOutputTests {
    /// Short output shows whole; long output shows its first lines with how many more.
    @Test func longOutputCollapsesToItsFirstLines() {
        let short = CollapsedOutput("a\nb\nc")
        #expect(!short.isCollapsible)
        #expect(short.preview == "a\nb\nc")
        #expect(short.expandLabel == nil)

        let lines = (1...30).map { "line \($0)" }.joined(separator: "\n")
        let long = CollapsedOutput(lines)
        #expect(long.isCollapsible)
        #expect(
            long.preview
                == (1...CollapsedOutput.maxLines).map { "line \($0)" }.joined(separator: "\n"))
        #expect(long.hiddenLines == 30 - CollapsedOutput.maxLines)
        #expect(long.expandLabel == "Show 20 more lines")
        #expect(CollapsedOutput(lines, maxLines: 29).expandLabel == "Show 1 more line")
        // The whole output is kept: nothing is cut.
        #expect(long.full == lines)
    }

    /// A few very long lines collapse by characters.
    @Test func veryLongLinesCollapseByCharacters() {
        let wide = String(repeating: "x", count: CollapsedOutput.maxCharacters + 10)
        let output = CollapsedOutput(wide)
        #expect(output.isCollapsible)
        #expect(output.preview.count == CollapsedOutput.maxCharacters)
        #expect(output.hiddenLines == 0)
        #expect(output.expandLabel == "Show all")
    }
}
