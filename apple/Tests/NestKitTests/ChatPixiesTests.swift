import Foundation
import Testing

@testable import NestKit

/// JSON for each chat's pixies and their calls, as the daemon sends them (B46).
enum ChatPixieJSON {
    static func call(
        _ id: String, pixie: String = "p1", tool: String? = nil, agent: String? = "ag1",
        state: String = "done", continued: Bool = false, started: Int = 0
    ) -> String {
        let agentJSON = agent.map { "\"\($0)\"" } ?? "null"
        return """
            {"id": "\(id)", "pixie_id": "\(pixie)", "tool_use_id": "\(tool ?? "tu-\(id)")",
             "agent_id": \(agentJSON), "state": "\(state)", "continued": \(continued),
             "started_at": "2026-10-16T10:\(String(format: "%02d", started)):00Z",
             "finished_at": null}
            """
    }

    static func pixie(_ id: String, state: String = "done", calls: [String] = []) -> String {
        """
        {"kind": "pixie", "pixie_id": "\(id)", "team_id": null, "state": "\(state)",
         "members": [], "calls": [\(calls.joined(separator: ","))]}
        """
    }

    static func team(
        _ id: String, members: [(String, Bool, String?)], state: String = "running",
        calls: [String] = []
    ) -> String {
        let list = members.map { pixie, leader, state in
            let stateJSON = state.map { "\"\($0)\"" } ?? "null"
            return #"{"pixie_id": "\#(pixie)", "leader": \#(leader), "state": \#(stateJSON)}"#
        }
        return """
            {"kind": "team", "pixie_id": null, "team_id": "\(id)", "state": "\(state)",
             "members": [\(list.joined(separator: ","))], "calls": [\(calls.joined(separator: ","))]}
            """
    }

    static func message(_ event: Int, _ blocks: String) -> String {
        #"{"event_id": \#(event), "ts": "2026-10-16T10:00:0\#(event % 10)Z", "blocks": [\#(blocks)]}"#
    }

    static func work(
        _ call: String, prompt: String? = "Review it", messages: [String] = [],
        report: String? = nil
    ) -> String {
        let promptJSON = prompt.map { "\"\($0)\"" } ?? "null"
        let reportJSON = report.map { "\"\($0)\"" } ?? "null"
        let body = call.dropLast()
        return """
            \(body), "prompt": \(promptJSON), "messages": [\(messages.joined(separator: ","))],
             "report": \(reportJSON)}
            """
    }

    static func transcript(
        _ tool: String, prompt: String? = "Find the DOIs", messages: [String] = [],
        report: String? = nil
    ) -> String {
        let promptJSON = prompt.map { "\"\($0)\"" } ?? "null"
        let reportJSON = report.map { "\"\($0)\"" } ?? "null"
        return """
            {"tool_use_id": "\(tool)", "prompt": \(promptJSON),
             "messages": [\(messages.joined(separator: ","))], "report": \(reportJSON)}
            """
    }

    static func entries(_ json: String...) -> [ChatPixieEntry] {
        Fixture.decode([ChatPixieEntry].self, json: "[\(json.joined(separator: ","))]")
    }

    static func groupEvent(_ session: String?, _ entries: String..., id: Int? = nil) -> Event {
        Fixture.event(
            EventType.sessionPixies, #"{"group": [\#(entries.joined(separator: ","))]}"#,
            id: id, session: session)
    }

    static func text(_ value: String) -> String { #"{"type": "text", "text": "\#(value)"}"# }

    static func use(_ id: String, _ name: String, _ input: String = "{}") -> String {
        #"{"type": "tool_use", "id": "\#(id)", "name": "\#(name)", "input": \#(input)}"#
    }

    static func result(_ id: String, _ content: String, error: Bool = false) -> String {
        #"{"type": "tool_result", "tool_use_id": "\#(id)", "content": "\#(content)", "is_error": \#(error)}"#
    }

    /// A live `session.message` event.
    static func live(_ id: Int?, session: String = "s1", parent: String?, _ blocks: String...)
        -> Event
    {
        let parentJSON = parent.map { "\"\($0)\"" } ?? "null"
        return Fixture.event(
            EventType.sessionMessage,
            #"{"blocks": [\#(blocks.joined(separator: ","))], "parent_tool_use_id": \#(parentJSON)}"#,
            id: id, session: session)
    }
}

@Suite struct ChatPixieModelTests {
    typealias J = ChatPixieJSON

    @Test func aChatsGroupDecodes() throws {
        let entries = J.entries(
            J.pixie("p1", calls: [J.call("k2", continued: true, started: 5), J.call("k1")]),
            J.team("t1", members: [("p2", true, "running"), ("p3", false, nil)]))
        #expect(entries.map(\.id) == ["pixie:p1", "team:t1"])
        let pixie = entries[0]
        #expect(pixie.kind == .pixie)
        #expect(pixie.pixieID == "p1")
        #expect(pixie.teamID == nil)
        #expect(pixie.state == .done)
        #expect(pixie.calls.map(\.id) == ["k2", "k1"])
        let call = pixie.calls[0]
        #expect(call.pixieID == "p1")
        #expect(call.toolUseID == "tu-k2")
        #expect(call.agentID == "ag1")
        #expect(call.continued)
        #expect(call.startedAt == Fixture.date("2026-10-16T10:05:00Z"))
        #expect(call.finishedAt == nil)
        let team = entries[1]
        #expect(team.kind == .team)
        #expect(team.members.map(\.pixieID) == ["p2", "p3"])
        #expect(team.members.map(\.leader) == [true, false])
        #expect(team.members.map(\.state) == [.running, nil])
        #expect(team.state == .running)
    }

    @Test func valuesItDoesNotKnowReadAsUnknown() {
        let odd = J.entries(
            #"{"kind": "crew", "pixie_id": null, "team_id": null, "state": "paused", "members": [], "calls": []}"#
        )[0]
        #expect(odd.kind == .unknown)
        #expect(odd.state == .unknown)
        #expect(odd.id == "pixie:")
        let nameless = J.entries(
            #"{"kind": "team", "pixie_id": null, "team_id": null, "state": "done", "members": [], "calls": []}"#
        )[0]
        #expect(nameless.id == "team:")
    }

    @Test func callStatesKnowWhenTheyRun() {
        #expect(PixieCallState.running.isRunning)
        #expect(!PixieCallState.done.isRunning)
    }

    @Test func sendingAwayNamesThePixieOrTheTeam() {
        let entries = J.entries(J.pixie("p1"), J.team("t1", members: []))
        #expect(entries[0].sendAway == SendAwayRequest(pixieID: "p1"))
        #expect(entries[1].sendAway == SendAwayRequest(teamID: "t1"))
        #expect(Fixture.json(entries[0].sendAway) == #"{"pixie_id":"p1"}"#)
        #expect(Fixture.json(entries[1].sendAway) == #"{"team_id":"t1"}"#)
    }

    @Test func aSubagentNamesTheSubagentThatStartedIt() throws {
        let event = Fixture.event(
            EventType.sessionAgents,
            #"{"agents": [{"id": "tu2", "name": "Explore", "description": null, "parent": "tu1", "status": "running", "activity": null, "started_at": null, "finished_at": null, "steps": []}, {"id": "tu1", "name": "Plan", "status": "running", "steps": []}]}"#
        )
        guard case .agents(let agents, _) = event.body else { throw Unexpected(event.body) }
        #expect(agents.map(\.parent) == ["tu1", nil])
    }

    @Test func aFinishedTaskMayCarryItsSummary() throws {
        let event = Fixture.event(
            EventType.sessionAgentTask,
            #"{"task_id": "ag1", "phase": "finished", "tool_use_id": "tu9", "status": "completed", "summary": "platypus"}"#
        )
        guard case .agentTask(let task) = event.body else { throw Unexpected(event.body) }
        #expect(task.summary == "platypus")
        let plain = Fixture.event(
            EventType.sessionAgentTask, #"{"task_id": "t2", "phase": "started"}"#)
        guard case .agentTask(let started) = plain.body else { throw Unexpected(plain.body) }
        #expect(started.summary == nil)
    }

    @Test func aGroupEventDecodes() {
        let event = J.groupEvent("s1", J.pixie("p1"))
        #expect(event.body == .pixieGroup(J.entries(J.pixie("p1"))))
        let broken = Fixture.event(EventType.sessionPixies, #"{"group": 3}"#)
        #expect(broken.body == .other)
    }

    @Test func callingATeamMemberAloneIsRefusedWithTheDaemonsWords() {
        let detail = "Ada is in @qa; call the team or a solo copy"
        let error = APIError.from(
            HTTPResponse(
                status: 422,
                body: Data(#"{"detail": "\#(detail)", "code": "pixie_in_team"}"#.utf8)))
        #expect(error == .pixieInTeam(detail))
        #expect(error.message == detail)
        #expect(!error.isConflict)
        // Other 422s stay invalid input.
        let other = APIError.from(
            HTTPResponse(status: 422, body: Data(#"{"detail": "bad"}"#.utf8)))
        #expect(other == .invalidInput("bad"))
    }
}

/// Pixies with these ids as slugs, names capitalized, in these teams.
private func pixies(_ rows: (id: String, team: String?)...) -> [Pixie] {
    rows.enumerated().map { index, row in
        var pixie = Fixture.decode(Pixie.self, "pixie")
        pixie.id = row.id
        pixie.slug = row.id
        pixie.name = row.id.capitalized
        pixie.color = "#00000\(index)"
        pixie.position = index
        pixie.teamID = row.team
        return pixie
    }
}

private func team(_ id: String, leader: String?, handle: String? = nil) -> PixieTeam {
    var team = Fixture.decode(PixieTeam.self, "pixie_team")
    team.id = id
    team.name = id.uppercased()
    team.handle = handle ?? id
    team.leaderID = leader
    return team
}

private func agent(
    _ id: String, _ name: String = "Explore", parent: String? = nil,
    status: AgentStatus = .running
) -> TrackedAgent {
    Fixture.decode(
        TrackedAgent.self,
        json: """
            {"id": "\(id)", "name": "\(name)", "description": "Look around",
             "parent": \(parent.map { "\"\($0)\"" } ?? "null"), "status": "\(status.rawValue)",
             "steps": []}
            """)
}

@Suite struct ChatTreeTests {
    typealias J = ChatPixieJSON

    let list = pixies(("ada", "t1"), ("bob", "t1"), ("cy", nil), ("dee", nil))
    let teams = [team("t1", leader: "ada", handle: "qa")]

    /// Each row as "<guides><elbow> <label>", for reading the tree's shape.
    private func shape(_ rows: [ChatTreeRow]) -> [String] {
        rows.map { row in
            let guides = row.guides.map { $0 ? "|" : " " }.joined()
            let elbow = row.isLast ? "`" : "+"
            let label: String =
                switch row.kind {
                case .group(let group): group.title
                case .pixie(let pixie, let entry): "\(pixie.name) \(entry.state.label)"
                case .team(let team, let color, _): "\(team.name) \(color ?? "-")"
                case .member(let pixie, let leader, let state, _):
                    "\(pixie.name)\(leader ? " leader" : "") \(ChatTree.label(of: state))"
                case .subagent(let agent): agent.name
                }
            return "\(guides)\(elbow) \(label)"
        }
    }

    @Test func nothingCalledAndNothingRunningIsNoTree() {
        let rows = ChatTree.rows(
            group: [], agents: [agent("main", "main")], pixies: list, teams: teams)
        #expect(rows.isEmpty)
    }

    @Test func pixiesAndTeamsThenRunningSubagents() {
        let group = J.entries(
            J.pixie("cy", calls: [J.call("k1", pixie: "cy", tool: "tu-cy")]),
            J.team(
                "t1", members: [("ada", true, "running"), ("bob", false, "done")],
                calls: [J.call("k2", pixie: "ada", tool: "tu-ada")]),
            // A pixie or team deleted since is left out.
            J.pixie("gone"), J.team("t9", members: []))
        let agents = [
            agent("main", "main"),
            // Pixie calls are in the Pixies group, by their call or their name.
            agent("tu-cy", "cy"), agent("tu-other", "dee"),
            agent("tu1", "Explore"),
            agent("tu2", "general-purpose", parent: "tu1"),
            agent("tu3", "Plan"),
            agent("tu4", "Done", status: .done),
            // Its parent finished: it shows at the top.
            agent("tu5", "Orphan", parent: "tu4"),
        ]
        let rows = ChatTree.rows(group: group, agents: agents, pixies: list, teams: teams)
        #expect(
            shape(rows) == [
                "+ Pixies",
                "|+ Cy done",
                "|` T1 #000000",
                "| + Ada leader working",
                "| ` Bob done",
                "` Subagents",
                " + Explore",
                " |` general-purpose",
                " + Plan",
                " ` Orphan",
            ])
        #expect(rows.map(\.depth) == [0, 1, 1, 2, 2, 0, 1, 2, 1, 1])
        #expect(
            rows.map(\.id) == [
                "pixies", "pixie:cy", "team:t1", "team:t1/ada", "team:t1/bob", "subagents",
                "tu1", "tu2", "tu3", "tu5",
            ])
    }

    @Test func eachGroupShowsOnlyWhenItHasRows() {
        let onlyPixies = ChatTree.rows(
            group: J.entries(J.pixie("cy")), agents: [], pixies: list, teams: teams)
        #expect(shape(onlyPixies) == ["` Pixies", " ` Cy done"])
        let onlyAgents = ChatTree.rows(
            group: [], agents: [agent("tu1")], pixies: list, teams: teams)
        #expect(shape(onlyAgents) == ["` Subagents", " ` Explore"])
        // A team with no known member, and a leaderless team, still show.
        let leaderless = ChatTree.rows(
            group: J.entries(J.team("t1", members: [("zed", false, nil)])), agents: [],
            pixies: list, teams: [team("t1", leader: nil)])
        #expect(shape(leaderless) == ["` Pixies", " ` T1 -"])
    }

    @Test func membersNotCalledYetSaySo() {
        #expect(ChatTree.label(of: nil) == "not called yet")
        #expect(ChatTree.label(of: .running) == "working")
    }
}

@MainActor @Suite struct ChatPixiesStoreTests {
    typealias J = ChatPixieJSON

    @Test func loadsEveryChatsGroup() async {
        let api = FakeAPI()
        api.set { $0.pixieGroups = ["s1": J.entries(J.pixie("p1")), "s2": []] }
        let store = ChatPixiesStore(api: api)
        await store.load()
        #expect(store.group(session: "s1").map(\.id) == ["pixie:p1"])
        #expect(store.group(session: "s2").isEmpty)
        #expect(store.group(session: "s3").isEmpty)
        #expect(api.calls == ["pixieGroups"])
    }

    @Test func aFailedLoadKeepsWhatWasThere() async {
        let api = FakeAPI()
        api.set { $0.pixieGroups = ["s1": J.entries(J.pixie("p1"))] }
        let store = ChatPixiesStore(api: api)
        await store.load()
        api.fail("pixieGroups")
        await store.load()
        #expect(store.group(session: "s1").count == 1)
    }

    @Test func eventsReplaceAChatsGroup() {
        let store = ChatPixiesStore(api: FakeAPI())
        store.apply(J.groupEvent("s1", J.pixie("p1"), J.pixie("p2")))
        #expect(store.group(session: "s1").count == 2)
        store.apply(J.groupEvent("s1"))
        #expect(store.group(session: "s1").isEmpty)
        // Without a chat it means nothing.
        store.apply(J.groupEvent(nil, J.pixie("p1")))
        #expect(store.group(session: "s1").isEmpty)
        store.apply(J.groupEvent("s2", J.pixie("p1")))
        store.apply(Fixture.event(EventType.sessionDeleted, #"{"session_id": "s2"}"#))
        #expect(store.group(session: "s2").isEmpty)
        store.apply(Fixture.event(EventType.sessionDelta, #"{"text": "x"}"#))
    }

    @Test func eventsDuringALoadApplyOnTopOfIt() async throws {
        let api = FakeAPI()
        let (gate, open) = AsyncStream<Void>.makeStream()
        api.set {
            $0.pixieGroups = ["s1": J.entries(J.pixie("old"))]
            $0.gates["pixieGroups"] = gate
        }
        let store = ChatPixiesStore(api: api)
        let loading = Task { await store.load() }
        await api.untilCalls { $0.count == 1 }
        // Published after the daemon read the groups: only the live copy brings it.
        store.apply(J.groupEvent("s1", J.pixie("new")))
        open.finish()
        await loading.value
        #expect(store.group(session: "s1").map(\.id) == ["pixie:new"])
    }

    @Test func sendingAwayShowsTheDaemonsGroup() async throws {
        let api = FakeAPI()
        let store = ChatPixiesStore(api: api)
        store.apply(J.groupEvent("s1", J.pixie("p1"), J.team("t1", members: [])))
        api.set { $0.sendAwayAnswer = J.entries(J.team("t1", members: [])) }
        try await store.sendAway(store.group(session: "s1")[0], session: "s1")
        #expect(store.group(session: "s1").map(\.id) == ["team:t1"])
        api.set { $0.sendAwayAnswer = [] }
        try await store.sendAway(store.group(session: "s1")[0], session: "s1")
        #expect(store.group(session: "s1").isEmpty)
        #expect(api.calls == ["sendAway s1 pixie=p1", "sendAway s1 team=t1"])
    }

    @Test func aRefusedSendAwayKeepsTheGroup() async {
        let api = FakeAPI()
        api.fail("sendAway")
        let store = ChatPixiesStore(api: api)
        store.apply(J.groupEvent("s1", J.pixie("p1")))
        await #expect(throws: APIError.self) {
            try await store.sendAway(store.group(session: "s1")[0], session: "s1")
        }
        #expect(store.group(session: "s1").count == 1)
    }
}

@Suite struct TeamMemberMentionTests {
    let list = pixies(("ada", "t1"), ("bob", "t1"), ("cy", nil), ("dee", "t2"))
    let teams = [team("t1", leader: "ada", handle: "qa"), team("t2", leader: "zed")]

    @Test func membersOfAnOfferedTeamAreLeftOutOfTheList() {
        let mentions = PixieMentions.available(
            pixies: list, teams: teams, souls: [:])
        // t2 is not offered (its leader is unknown), so Dee is called on her own.
        #expect(mentions.map(\.token) == ["qa", "cy", "dee"])
        #expect(PixieMentions.members(mentions) == ["ada": "qa", "bob": "qa"])
    }

    @Test func callingAMemberAloneIsStoppedBeforeSending() {
        let mentions = PixieMentions.available(
            pixies: list, teams: teams, souls: [:])
        #expect(
            PixieMentions.memberCall(in: "please @bob look", mentions: mentions)
                == "Bob is in @qa; call the team or a solo copy")
        #expect(
            PixieMentions.memberCall(in: "@ada, then", mentions: mentions)
                == "Ada is in @qa; call the team or a solo copy")
        // Whole tokens only, and the team or a solo pixie is fine.
        #expect(PixieMentions.memberCall(in: "@bobby and x@bob", mentions: mentions) == nil)
        #expect(PixieMentions.memberCall(in: "@qa and @cy and @dee", mentions: mentions) == nil)
    }
}
