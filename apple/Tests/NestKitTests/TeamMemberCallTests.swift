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

private func agentUse(_ id: String, _ subagent: String, task: String = "Review") -> String {
    #"{"type": "tool_use", "id": "\#(id)", "name": "Agent", "input": {"subagent_type": "\#(subagent)", "description": "\#(task)"}}"#
}

private func result(_ id: String, _ content: String) -> String {
    #"{"type": "tool_result", "tool_use_id": "\#(id)", "content": "\#(content)"}"#
}

private func subagentDelta(_ text: String, parent: String) -> Event {
    Fixture.event(
        EventType.sessionSubagentDelta,
        #"{"text": "\#(text)", "parent_tool_use_id": "\#(parent)"}"#, id: nil)
}

private func thinkingDelta(_ text: String, parent: String) -> Event {
    Fixture.event(
        EventType.sessionThinkingDelta,
        #"{"text": "\#(text)", "parent_tool_use_id": "\#(parent)"}"#, id: nil)
}

private func state(_ name: String, id: Int) -> Event {
    Fixture.event(EventType.sessionState, #"{"state": "\#(name)"}"#, id: id)
}

private func agent(_ id: String, _ subagent: String, result: String? = nil, steps: [CallStep] = [])
    -> ToolCall
{
    var call = ToolCall(
        id: id, name: "Agent", input: .object(["subagent_type": .string(subagent)]),
        result: result, isError: false)
    call.steps = steps
    return call
}

private func entry(_ call: ToolCall, running: Bool) -> PixieCallEntry {
    PixieCallEntry(id: call.id, call: call, slug: call.subagentType!, isRunning: running)
}

/// A team leader's calls of its members, inside the leader's own call (B75).
@MainActor @Suite struct TeamMemberCallStoreTests {
    let transcript = TranscriptStore(sessionID: "s1", api: FakeAPI())

    private var leader: ToolCall? {
        if case .tool(let call) = transcript.items.first?.content { call } else { nil }
    }

    /// The agent call at this step of the leader's call.
    private func member(_ index: Int) -> ToolCall? {
        guard let steps = leader?.steps, steps.indices.contains(index),
            case .call(let call) = steps[index].kind
        else { return nil }
        return call
    }

    /// A member's call keeps its own messages and gets its report from the leader's
    /// messages; the leader's other tool results, and blocks of unknown types, still show
    /// nothing.
    @Test func aMemberCallKeepsItsMessagesAndReport() async throws {
        try await transcript.load()
        transcript.receive(message(agentUse("lead", "bugs"), id: 1))
        transcript.receive(
            message(
                #"{"type": "text", "text": "Splitting it."}, \#(agentUse("m1", "stylist", task: "Names")), {"type": "tool_use", "id": "r1", "name": "Read", "input": {"file_path": "a.ts"}}"#,
                parent: "lead", id: 2))
        transcript.receive(
            message(
                #"{"type": "text", "text": "Looking at names."}, {"type": "tool_use", "id": "s1", "name": "Grep", "input": {"pattern": "date"}}, {"type": "image"}"#,
                parent: "m1", id: 3))
        transcript.receive(message(result("r1", "x"), parent: "lead", id: 4))
        transcript.receive(message(result("m1", "Names are fine."), parent: "lead", id: 5))

        #expect(leader?.steps.count == 3)
        #expect(
            leader?.steps.map(\.line) == ["Splitting it.", "Agent stylist: Names", "Read a.ts"])
        let call = try #require(member(1))
        #expect(call.id == "m1")
        #expect(call.subagentType == "stylist")
        #expect(call.input["description"]?.stringValue == "Names")
        #expect(call.result == "Names are fine.")
        #expect(
            call.steps.map(\.kind) == [
                .text("Looking at names."),
                .tool(name: "Grep", input: .object(["pattern": .string("date")])),
            ])
    }

    /// A member's text and thinking stream into its own call, and end with the turn.
    @Test func aMemberStreamsIntoItsOwnCall() async throws {
        try await transcript.load()
        transcript.receive(state("running", id: 1))
        transcript.receive(message(agentUse("lead", "bugs"), id: 2))
        transcript.receive(message(agentUse("m1", "stylist"), parent: "lead", id: 3))
        transcript.receive(subagentDelta("Checking ", parent: "m1"))
        transcript.receive(subagentDelta("names", parent: "m1"))
        transcript.receive(thinkingDelta("Hm", parent: "m1"))
        #expect(member(0)?.liveText == "Checking names")
        #expect(member(0)?.liveThinking == "Hm")
        #expect(leader?.liveText == "")

        transcript.receive(state("idle", id: 4))
        #expect(member(0)?.liveText == "")
        #expect(member(0)?.liveThinking == "")
    }

    /// Calls nest deeper: a member's own agent call keeps its messages and report too, and
    /// a result naming no call of the leader's adds nothing.
    @Test func deeperCallsKeepTheirMessages() async throws {
        try await transcript.load()
        transcript.receive(message(agentUse("lead", "bugs"), id: 1))
        transcript.receive(message(agentUse("m1", "stylist"), parent: "lead", id: 2))
        transcript.receive(message(agentUse("x1", "Explore"), parent: "m1", id: 3))
        transcript.receive(
            message(#"{"type": "text", "text": "Found it."}"#, parent: "x1", id: 4))
        transcript.receive(message(result("x1", "In a.ts."), parent: "m1", id: 5))
        transcript.receive(message(result("nope", "?"), parent: "lead", id: 6))

        guard case .call(let explore) = member(0)?.steps.first?.kind else {
            throw Unexpected(leader as Any)
        }
        #expect(explore.subagentType == "Explore")
        #expect(explore.steps.map(\.kind) == [.text("Found it.")])
        #expect(explore.result == "In a.ts.")
        #expect(leader?.steps.count == 1)
    }

    /// A member's report that carries images keeps them with its call.
    @Test func aMemberReportKeepsItsImages() async throws {
        try await transcript.load()
        transcript.receive(message(agentUse("lead", "bugs"), id: 1))
        transcript.receive(message(agentUse("m1", "stylist"), parent: "lead", id: 2))
        transcript.receive(
            message(
                #"{"type": "tool_result", "tool_use_id": "m1", "is_error": true, "content": "Failed.", "images": [{"attachment_id": "i1", "media_type": "image/png"}]}"#,
                parent: "lead", id: 3))
        #expect(member(0)?.isError == true)
        #expect(member(0)?.images.count == 1)
        #expect(leader?.steps.count == 1)
    }
}

/// What an opened pixie call shows: its steps, with its pixie calls as rows (B75).
@Suite struct TeamMemberCallRowTests {
    static let text = CallStep(id: "e1-0", kind: .text("Splitting it."))
    static let read = CallStep(
        id: "e1-2", kind: .tool(name: "Read", input: .object(["file_path": .string("a.ts")])))

    @Test func aDoneMemberShowsItsReport() throws {
        let done = agent("m1", "stylist", result: "Names are fine.")
        let leader = agent(
            "lead", "bugs", steps: [Self.text, CallStep(id: "e1-1", kind: .call(done)), Self.read])
        let rows = entry(leader, running: true).steps(pixies: ["bugs", "stylist"])
        #expect(rows.map(\.id) == ["e1-0", "m1", "e1-2"])
        #expect(rows[0] == .step(Self.text))
        #expect(rows[2] == .step(Self.read))
        guard case .pixieCall(let member) = rows[1] else { throw Unexpected(rows) }
        #expect(member.slug == "stylist")
        #expect(member.call.result == "Names are fine.")
        #expect(!member.isRunning)
        #expect(!member.call.stopped)
        #expect(member.isNested)
        #expect(!entry(leader, running: true).isNested)
    }

    /// Without an answer, a member runs while the leader does, and is stopped once the
    /// leader's call ended.
    @Test func aMemberRunsWhileItsLeaderDoes() throws {
        let leader = agent(
            "lead", "bugs", steps: [CallStep(id: "e1-0", kind: .call(agent("m1", "stylist")))])
        guard
            case .pixieCall(let running) = entry(leader, running: true).steps(pixies: ["stylist"])[
                0]
        else { throw Unexpected(leader) }
        #expect(running.isRunning)
        #expect(!running.call.stopped)
        guard
            case .pixieCall(let stopped) = entry(leader, running: false).steps(pixies: ["stylist"])[
                0]
        else { throw Unexpected(leader) }
        #expect(!stopped.isRunning)
        #expect(stopped.call.stopped)
    }

    /// An agent call of another subagent stays a step, as does any call when no pixie is
    /// known; a pixie inside a member's call is a row in the member's own steps.
    @Test func otherSubagentsStaySteps() throws {
        let explore = CallStep(id: "e1-0", kind: .call(agent("x1", "Explore")))
        let deep = agent(
            "m1", "stylist", steps: [CallStep(id: "e2-0", kind: .call(agent("m2", "scout")))])
        let leader = agent(
            "lead", "bugs", steps: [explore, CallStep(id: "e1-1", kind: .call(deep))])
        let pixies: Set<String> = ["stylist", "scout"]
        let rows = entry(leader, running: true).steps(pixies: pixies)
        #expect(rows[0] == .step(explore))
        #expect(rows[0].id == "e1-0")
        #expect(
            entry(leader, running: true).steps(pixies: []).allSatisfy {
                if case .step = $0 { true } else { false }
            })
        guard case .pixieCall(let member) = rows[1],
            case .pixieCall(let inner) = member.steps(pixies: pixies)[0]
        else { throw Unexpected(rows) }
        #expect(inner.slug == "scout")
        #expect(inner.isRunning)
        #expect(explore.line == "Agent Explore")
    }
}
