import Foundation
import Testing

@testable import NestKit

/// B112: a pixie on any engine, called natively or with Nest's call_pixie tool, looks and
/// acts like a Claude subagent: the same rows, Goals, Stop, Skills and `#` memory.
@MainActor @Suite struct PixieParityTests {
    let api = FakeAPI()

    private func message(_ blocks: String, parent: String? = nil, id: Int) -> Event {
        let parentJSON = parent.map { "\"\($0)\"" } ?? "null"
        return Fixture.event(
            EventType.sessionMessage,
            #"{"blocks": [\#(blocks)], "parent_tool_use_id": \#(parentJSON)}"#, id: id)
    }

    /// An engine's plan with no parent replaces the chat's task list, as TaskCreate and
    /// TaskUpdate fill Goals; with a parent its step in progress is that row's activity.
    @Test func anEnginesPlanFillsGoalsAndTheCallsRow() {
        let store = ActivityStore(api: api)
        store.apply(
            Fixture.event(
                EventType.sessionPlan,
                #"{"steps": [{"text": "Read", "status": "completed"}, {"text": "Fix", "status": "in_progress"}, {"text": "Test", "status": "pending"}], "parent_tool_use_id": null}"#,
                id: 1))
        let goals = store.goals(session: "s1")
        #expect(goals.tasks.map(\.subject) == ["Read", "Fix", "Test"])
        #expect(goals.tasks.map(\.id) == ["1", "2", "3"])
        #expect(goals.current?.subject == "Fix")

        store.apply(Self.agents(activity: "Read a.ts"))
        store.apply(
            Fixture.event(
                EventType.sessionPlan,
                #"{"steps": [{"text": "Check the diff", "status": "in_progress"}], "parent_tool_use_id": "c1"}"#,
                id: 2))
        #expect(store.agents(session: "s1").last?.activity == "Check the diff")
        // A subagent's plan leaves the chat's own list alone.
        #expect(store.goals(session: "s1").tasks.count == 3)
    }

    /// A called pixie paused at the usage limit says so on its row until it goes on; its
    /// plan does not cover that.
    @Test func aPausedCallSaysSoOnItsRow() {
        let store = ActivityStore(api: api)
        store.apply(Self.agents(activity: "Read a.ts"))
        store.apply(
            Fixture.event(
                EventType.sessionAgentPaused, #"{"tool_use_id": "c1", "paused": true}"#, id: 1))
        #expect(store.agents(session: "s1").last?.activity == "Paused at limit")
        store.apply(
            Fixture.event(
                EventType.sessionPlan,
                #"{"steps": [{"text": "Fix", "status": "in_progress"}], "parent_tool_use_id": "c1"}"#,
                id: 2))
        #expect(store.agents(session: "s1").last?.activity == "Paused at limit")
        store.apply(
            Fixture.event(
                EventType.sessionAgentPaused, #"{"tool_use_id": "c1", "paused": false}"#, id: 3))
        #expect(store.agents(session: "s1").last?.activity == nil)
    }

    static func agents(activity: String) -> Event {
        Fixture.event(
            EventType.sessionAgents,
            #"{"agents": [{"id": "main", "name": "main", "status": "running", "steps": []}, {"id": "c1", "name": "reviewer", "status": "running", "activity": "\#(activity)", "steps": []}], "background": null}"#,
            id: nil)
    }

    /// Codex as the daemon lists it since B112: Stop on a call, questions, the task list
    /// and a pixie's Skills work; `#` to CLAUDE.md still does not.
    @Test func aCodexPixieGetsStopAndSkills() async {
        api.set {
            $0.providers = Fixture.decode(ProviderList.self, json: Self.engines).providers
        }
        let store = ProvidersStore(api: api)
        await store.load()
        for engine in ["codex", "opencode"] {
            #expect(store.supports(.stopTask, on: engine))
            #expect(store.supports(.pixieSkills, on: engine))
            #expect(store.supports(.questions, on: engine))
            #expect(store.supports(.taskList, on: engine))
            #expect(!store.supports(.memory, on: engine))
        }
    }

    static let engines = """
        {"providers": [
          {"name": "claude", "display_name": "Claude", "unsupported": []},
          {"name": "codex", "display_name": "Codex",
           "unsupported": ["rewind", "fork", "slash_commands", "withdraw", "plan_review",
                           "memory"]},
          {"name": "opencode", "display_name": "OpenCode",
           "unsupported": ["rewind", "fork", "withdraw", "plan_review", "memory"]}
        ]}
        """

    /// `#` in a pixie's own chat saves to the pixie's memory on every engine; elsewhere
    /// only where the engine saves to CLAUDE.md.
    @Test func hashSavesAPixiesMemoryOnEveryEngine() throws {
        var pixieChat = Fixture.session()
        pixieChat.pixieID = "p1"
        #expect(ComposerInput.offersMemory(in: pixieChat, engineSaves: false))
        #expect(!ComposerInput.offersMemory(in: Fixture.session(), engineSaves: false))
        #expect(ComposerInput.offersMemory(in: Fixture.session(), engineSaves: true))

        #expect(MemoryScope.choices(pixie: true) == [.pixie])
        // The daemon takes project or user; it writes a pixie chat's to the pixie.
        #expect(
            Fixture.json(MemoryRequest(text: "x", scope: MemoryScope.pixie.requested))
                == #"{"scope":"user","text":"x"}"#)
        let saved = Fixture.decode(
            SavedMemory.self,
            json: #"{"scope": "pixie", "path": "/p/memory.md", "line": "- 2026-10-27: x"}"#)
        #expect(saved.confirmation == "Saved to pixie memory")
    }
}
