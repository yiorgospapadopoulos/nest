import Foundation
import Testing

@testable import HarnessKit

@Suite struct BackgroundDecodingTests {
    @Test func decodesTheSessionDetailsBackgroundWork() throws {
        let background = try #require(Fixture.sessionDetail.background)

        #expect((background.running, background.completed) == (1, 2))
        #expect(background.items.map(\.kind) == [.agent, .bash, .bash])
        #expect(background.items.map(\.status) == [.done, .running, .failed])
        #expect(background.items[1].description == "Start the dev server")
        #expect(background.items[1].finishedAt == nil)
        #expect(background.items[0].finishedAt == Date(timeIntervalSince1970: 1_791_277_985.5))
        #expect(Fixture.sessions[0].background == nil)
    }

    @Test func unknownKindsAndStatusesDecodeAsUnknown() throws {
        let json = Fixture.text("session_detail")
            .replacingOccurrences(of: "\"kind\": \"bash\"", with: "\"kind\": \"mcp\"")
            .replacingOccurrences(of: "\"status\": \"failed\"", with: "\"status\": \"killed\"")
        let background = try #require(Fixture.decode(Session.self, json: json).background)

        #expect(background.items.map(\.kind) == [.agent, .unknown, .unknown])
        #expect(background.items[2].status == .unknown)
    }

    @Test func agentsEventsCarryTheBackgroundSummary() throws {
        let summary = try #require(Fixture.sessionDetail.background)
        let event = Fixture.event(
            EventType.sessionAgents,
            "{\"agents\": [], \"background\": \(Fixture.json(summary))}", id: nil)

        #expect(event.body == .agents([], background: summary))
    }

    @Test func decodesAgentTaskEvents() throws {
        let finished = Fixture.event(
            EventType.sessionAgentTask,
            #"{"task_id": "t1", "phase": "finished", "tool_use_id": "toolu_10", "task_type": "local_bash", "description": "Dev server", "background": true, "status": "stopped"}"#
        )
        guard case .agentTask(let task) = finished.body else { throw Unexpected(finished.body) }
        #expect(task.taskID == "t1")
        #expect(task.phase == .finished)
        #expect(task.toolUseID == "toolu_10")
        #expect(task.taskType == "local_bash")
        #expect(task.description == "Dev server")
        #expect(task.background)
        #expect(task.status == .stopped)
        #expect(task.agentStatus == .failed)

        let started = Fixture.event(
            EventType.sessionAgentTask, #"{"task_id": "t2", "phase": "paused"}"#)
        guard case .agentTask(let minimal) = started.body else { throw Unexpected(started.body) }
        #expect(minimal.phase == .unknown)
        #expect(minimal.toolUseID == nil)
        #expect(minimal.taskType == nil)
        #expect(!minimal.background)
        #expect(minimal.status == nil)

        let broken = Fixture.event(EventType.sessionAgentTask, #"{"phase": "started"}"#)
        #expect(broken.body == .other)
    }

    @Test func aCompletedTaskLeavesItsAgentDone() {
        let task = Fixture.decode(
            AgentTask.self, json: #"{"task_id": "t", "phase": "finished", "status": "completed"}"#)
        #expect(task.agentStatus == .done)
    }
}

@Suite struct BackgroundSummaryTests {
    let summary = Fixture.sessionDetail.background!

    @Test func labelsCountsAndSplitsTheItems() {
        #expect(summary.label == "1 running · 2 completed")
        #expect(!summary.isEmpty)
        #expect(BackgroundSummary.empty.isEmpty)
        #expect(BackgroundSummary.empty.label == "0 running · 0 completed")
        #expect(BackgroundSummary(running: 1, completed: 0, items: []).label == "1 running task")
        #expect(BackgroundSummary(running: 2, completed: 0, items: []).label == "2 running tasks")
        #expect(summary.runningItems.map(\.id) == ["toolu_10"])
        #expect(summary.finishedItems.map(\.id) == ["toolu_09", "toolu_11"])
        #expect(summary.runningCommands.map(\.name) == ["npm run dev"])
    }

    @Test func showsHowLongEachItemRan() {
        let start = summary.items[1].startedAt!
        #expect(summary.items[1].duration(at: start.addingTimeInterval(75)) == "1m 15s")
        #expect(summary.items[0].duration(at: .distantFuture) == "25s")
        var unstarted = summary.items[0]
        unstarted.startedAt = nil
        #expect(unstarted.duration(at: start) == nil)
    }

    @Test func aFinishedTaskMovesItsRunningItemToCompleted() {
        var copy = summary
        let at = Date(timeIntervalSince1970: 1_791_278_100)
        copy.finish(toolUseID: "toolu_10", as: .done, at: at)

        #expect(copy.label == "0 running · 3 completed")
        #expect(copy.items[1].status == .done)
        #expect(copy.items[1].finishedAt == at)

        copy.finish(toolUseID: "toolu_10", as: .failed, at: at)
        copy.finish(toolUseID: "toolu_99", as: .failed, at: at)
        #expect(copy.label == "0 running · 3 completed")
        #expect(copy.items[1].status == .done)
    }

    @Test func theExchangeKeepsItsOwnTasksAndAnyStillRunning() {
        // Started 09:12:40 (done 09:13:05.5), 09:13:00 (running) and 09:13:10 (failed).
        let current = summary.exchange(since: Fixture.date("2026-10-06T09:13:06Z"))
        #expect(current.items.map(\.id) == ["toolu_10", "toolu_11"])
        #expect((current.running, current.completed) == (1, 1))
        #expect(current.label == "1 running · 1 completed")

        // An earlier task that finishes during the exchange counts as completed in it.
        let carried = summary.exchange(since: Fixture.date("2026-10-06T09:13:05Z"))
        #expect(carried.items.map(\.id) == ["toolu_09", "toolu_10", "toolu_11"])
        #expect(carried.label == "1 running · 2 completed")

        // A task started at the very moment of the message belongs to it.
        #expect(summary.exchange(since: Fixture.date("2026-10-06T09:12:40Z")) == summary)
        // Without a message to start from, every task counts.
        #expect(summary.exchange(since: nil) == summary)

        // An earlier task still at work counts as running, its finished siblings do not.
        let next = Fixture.date("2026-10-06T10:00:00Z")
        let later = summary.exchange(since: next)
        #expect(later.items.map(\.id) == ["toolu_10"])
        #expect(later.label == "1 running task")

        // When it finishes, it stays as completed instead of vanishing (B-16).
        var settled = summary
        settled.finish(toolUseID: "toolu_10", as: .done, at: next)
        #expect(settled.exchange(since: next).items.map(\.id) == ["toolu_10"])
        #expect(settled.exchange(since: next).label == "0 running · 1 completed")
        // One that finished before the exchange began stays out.
        #expect(settled.exchange(since: next.addingTimeInterval(1)).isEmpty)

        // A finished task of unknown start and end cannot be placed in the exchange.
        var unknown = summary
        unknown.items[0].startedAt = nil
        unknown.items[0].finishedAt = nil
        #expect(
            unknown.exchange(since: .distantPast).items.map(\.id) == ["toolu_10", "toolu_11"])
    }

    @Test func runningNeverGoesBelowZero() {
        var odd = summary
        odd.running = 0
        odd.finish(toolUseID: "toolu_10", as: .done, at: .distantPast)
        #expect((odd.running, odd.completed) == (0, 3))
    }
}

@Suite struct DurationFormattingTests {
    let start = Date(timeIntervalSince1970: 0)

    @Test func showsSecondsWhileShort() {
        #expect(Elapsed.duration(from: start, to: start) == "0s")
        #expect(Elapsed.duration(from: start, to: start.addingTimeInterval(8.9)) == "8s")
        #expect(Elapsed.duration(from: start, to: start.addingTimeInterval(120)) == "2m")
        #expect(Elapsed.duration(from: start, to: start.addingTimeInterval(184)) == "3m 4s")
        #expect(Elapsed.duration(from: start, to: start.addingTimeInterval(4_320)) == "1h 12m")
        #expect(Elapsed.duration(from: start, to: start.addingTimeInterval(-5)) == "0s")
    }
}

@MainActor
@Suite struct ActivityBackgroundTests {
    let api = FakeAPI()
    let store: ActivityStore
    let sessionID = Fixture.sessionDetail.id

    init() {
        store = ActivityStore(api: api)
        let detail = Fixture.sessionDetail
        api.set { $0.details[detail.id] = detail }
    }

    private func agentsEvent(_ agents: String, background: BackgroundSummary?) -> Event {
        let tail = background.map { ", \"background\": \(Fixture.json($0))" } ?? ""
        return Fixture.event(
            EventType.sessionAgents, "{\"agents\": \(agents)\(tail)}", id: nil, session: sessionID)
    }

    private func taskEvent(_ payload: String, session: String? = nil) -> Event {
        Fixture.event(EventType.sessionAgentTask, payload, session: session ?? sessionID)
    }

    @Test func loadsTheBackgroundWorkWithTheDetail() async throws {
        #expect(store.background(session: sessionID) == .empty)

        try await store.load(session: sessionID)

        #expect(store.background(session: sessionID).label == "1 running · 2 completed")
        #expect(store.hasRunningWork(session: sessionID))
        // The main agent and the dev server; the done Explore agent is not counted.
        #expect(store.runningAgents(in: [sessionID]) == 2)
    }

    @Test func aDetailWithoutBackgroundLoadsEmpty() async throws {
        api.set { $0.sessions = [Fixture.session("plain")] }
        try await store.load(session: "plain")
        #expect(store.background(session: "plain") == .empty)
        #expect(!store.hasRunningWork(session: "plain"))
    }

    @Test func anIdleChatWithABackgroundCommandStillHasRunningWork() throws {
        var summary = try #require(Fixture.sessionDetail.background)
        store.apply(agentsEvent("[]", background: summary))
        #expect(store.hasRunningWork(session: sessionID))
        #expect(store.runningAgents(in: [sessionID, "other"]) == 1)

        summary.finish(toolUseID: "toolu_10", as: .done, at: .distantPast)
        store.apply(agentsEvent("[]", background: summary))
        #expect(!store.hasRunningWork(session: sessionID))
        #expect(store.background(session: sessionID).label == "0 running · 3 completed")
    }

    @Test func anAgentsEventWithoutBackgroundKeepsTheLastSummary() async throws {
        try await store.load(session: sessionID)
        store.apply(agentsEvent("[]", background: nil))
        #expect(store.agents(session: sessionID).isEmpty)
        #expect(store.background(session: sessionID).running == 1)
    }

    @Test func aFinishedTaskUpdatesTheBarBeforeTheNextSnapshot() async throws {
        try await store.load(session: sessionID)

        store.apply(
            taskEvent(#"{"task_id": "a", "phase": "started", "tool_use_id": "toolu_10"}"#))
        store.apply(taskEvent(#"{"task_id": "a", "phase": "finished", "status": "completed"}"#))
        store.apply(
            Fixture.event(
                EventType.sessionAgentTask,
                #"{"task_id": "a", "phase": "finished", "tool_use_id": "toolu_10"}"#,
                session: nil))
        store.apply(
            taskEvent(
                #"{"task_id": "a", "phase": "finished", "tool_use_id": "toolu_10"}"#,
                session: "unloaded"))
        #expect(store.background(session: sessionID).running == 1)
        #expect(store.background(session: "unloaded") == .empty)

        store.apply(
            taskEvent(
                #"{"task_id": "a", "phase": "finished", "tool_use_id": "toolu_10", "status": "failed"}"#
            ))

        let summary = store.background(session: sessionID)
        #expect(summary.label == "0 running · 3 completed")
        #expect(summary.items[1].status == .failed)
        #expect(summary.items[1].finishedAt == Date(timeIntervalSince1970: 1_791_277_200))
    }

    @Test func deletionForgetsTheBackgroundWork() async throws {
        try await store.load(session: sessionID)
        store.apply(
            Fixture.event(
                EventType.sessionDeleted, "{\"session_id\": \"\(sessionID)\"}", session: nil))
        #expect(store.background(session: sessionID) == .empty)
    }

    @Test func watchesBusyOpenRecentAndStillWorkingChats() {
        let now = Date(timeIntervalSince1970: 100_000)
        let recent = now.addingTimeInterval(-3600)
        let old = now.addingTimeInterval(-ActivityStore.idleWatchWindow - 1)
        let sessions = [
            Fixture.session("running", state: .running, updatedAt: old),
            Fixture.session("recent", state: .idle, updatedAt: recent),
            Fixture.session("old", state: .idle, updatedAt: old),
            Fixture.session("archived", state: .idle, archived: true, updatedAt: recent),
            Fixture.session("failed", state: .failed, updatedAt: recent),
            Fixture.session(sessionID, state: .idle, updatedAt: old),
        ]
        store.apply(agentsEvent("[]", background: Fixture.sessionDetail.background))

        let watched = store.watchList(sessions, open: ["old", "pane"], now: now)

        #expect(watched == ["running", "recent", sessionID, "old", "pane"])
    }
}

@Suite struct BackgroundBarStateTests {
    @Test func togglesAChatsBarAndForgetsItOnDelete() {
        var state = ProjectState()
        state.toggleBackground("c1")
        state.toggleBackground("c2")
        #expect(state.expandedBackground == ["c1", "c2"])
        state.toggleBackground("c2")
        #expect(state.expandedBackground == ["c1"])
        state.forget("c1")
        #expect(state.expandedBackground.isEmpty)
    }
}
