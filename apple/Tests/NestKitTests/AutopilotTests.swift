import Foundation
import Testing

@testable import NestKit

private let start = Date(timeIntervalSince1970: 1_791_288_000)

/// A chat on Autopilot (B120).
@MainActor
@Suite struct AutopilotTests {
    let api = FakeAPI()
    let store: SessionsStore

    init() {
        store = SessionsStore(api: api, approvals: ApprovalsStore(api: api))
    }

    /// A session's JSON with these keys added.
    private func sessionJSON(_ keys: String) -> String {
        String(Fixture.json(Fixture.session()).dropLast()) + "," + keys + "}"
    }

    // MARK: Decoding

    @Test func oldPayloadsHaveNoAutopilot() {
        let session = Fixture.decode(Session.self, json: Fixture.json(Fixture.session()))
        #expect(session.autopilot == nil)
        let habit = PixieHabitsTests.habit()
        #expect(habit.autopilot == nil)
        #expect(!HabitDraft(habit: habit).autopilot)
    }

    @Test func aRunDecodesAsTheDaemonSendsIt() throws {
        let session = Fixture.decode(
            Session.self,
            json: sessionJSON(
                #"""
                "autopilot": {"started_at": "2026-01-01T12:00:00Z", "until": "2026-01-01T14:00:00Z",
                 "weekly_cap": 70, "mode": "default", "follows_claude_code_mode": false, "turns": 2,
                 "idle_turns": 0, "nudges": 0, "nudged_since": null, "errors": 0, "retry_at": null,
                 "summary": null, "decisions": []}
                """#))
        let run = try #require(session.autopilot)
        #expect(run.weeklyCap == 70)
        #expect(AutopilotBudget(run: run).stopAfterMinutes == 120)
    }

    @Test func aDecisionFromBeforeTheDetailsDecodes() {
        let at = #""at": "2026-01-01T12:20:00Z""#
        let denied = Fixture.decode(
            AutopilotDecision.self,
            json: #"{"kind": "denied", "title": "git push", "answer": "Blocked", \#(at)}"#)
        #expect(denied.options.isEmpty)
        #expect(denied.reason == nil)
        #expect(denied.detail == nil)
        #expect(denied.shownAnswer == "Denied")
        #expect(denied.why == "Blocked")

        let allowed = Fixture.decode(
            AutopilotDecision.self,
            json: #"{"kind": "allowed", "title": "ls", "answer": "Allowed", \#(at)}"#)
        #expect(!allowed.opens)
    }

    // MARK: The budget

    @Test func aNewChatsChoiceOnlyGoesWithItsRequest() {
        let control = AutopilotControl(choice: AutopilotChoice(), chatExists: false, run: nil)
        let on = control.turning(on: true)
        #expect(on.request == nil)
        #expect(on.choice.request == SetAutopilotRequest(on: true))
        #expect(AutopilotChoice().request == nil)
    }

    /// While a chat is off, choices wait for the switch, and the switch sends them.
    @Test func anIdleChatKeepsItsChoiceUntilTurnedOn() {
        let idle = AutopilotControl(choice: AutopilotChoice(), chatExists: true, run: nil)
        let capped = idle.capping(at: 70)
        #expect(capped.request == nil)
        #expect(!idle.on)
        let next = AutopilotControl(choice: capped.choice, chatExists: true, run: nil)
        #expect(
            next.turning(on: true).request
                == SetAutopilotRequest(on: true, budget: AutopilotBudget(weeklyCap: 70)))
    }

    /// A change on a run replaces its whole budget, starting from the run's, not the
    /// composer's old choice.
    @Test func aChangeDuringARunReplacesItsBudget() {
        let run = AutopilotRun(
            startedAt: start, until: start.addingTimeInterval(4 * 3600), weeklyCap: 80)
        let stale = AutopilotChoice(budget: AutopilotBudget(weeklyCap: 50))
        let control = AutopilotControl(choice: stale, chatExists: true, run: run)
        #expect(control.on)
        #expect(control.stopAfter == .time)
        #expect(
            control.capping(at: nil).request
                == SetAutopilotRequest(on: true, budget: AutopilotBudget(stopAfterMinutes: 240)))
        #expect(
            control.stopping(after: .done).request
                == SetAutopilotRequest(on: true, budget: AutopilotBudget(weeklyCap: 80)))
        #expect(control.turning(on: false).request == SetAutopilotRequest(on: false))
    }

    @Test func theCapsReadAsPercentages() {
        #expect(AutopilotText.weeklyCaps.map(\.1) == ["Off", "50%", "60%", "70%", "80%", "90%"])
        #expect(AutopilotText.weeklyCaps.map(\.0) == [nil, 50, 60, 70, 80, 90])
    }

    @Test func choosingTimeStartsAtTheFirstOption() {
        let control = AutopilotControl(choice: AutopilotChoice(), chatExists: false, run: nil)
        #expect(control.stopping(after: .time).choice.budget.stopAfterMinutes == 60)
    }

    /// A chat on Autopilot works in a worktree unless the user chose a place.
    @Test func aNewChatOnAutopilotMovesToAWorktree() {
        let on = AutopilotChoice(on: true)
        #expect(on.place(chosen: nil, fallback: .inPlace) == .newWorktree(from: nil))
        #expect(on.place(chosen: .inPlace, fallback: .inPlace) == .inPlace)
        #expect(AutopilotChoice().place(chosen: nil, fallback: .inPlace) == .inPlace)
    }

    @Test func turningOffAsksTheDaemonAndFollowsItsAnswer() async throws {
        var running = Fixture.session("s1", state: .idle)
        running.autopilot = AutopilotRun(startedAt: start)
        let session = running
        api.set { $0.sessions = [session] }
        try await store.load()
        try await store.setAutopilot("s1", SetAutopilotRequest(on: false))
        #expect(api.calls.last == "setAutopilot s1 false")
        #expect(store.session("s1")?.autopilot == nil)
        #expect(store.settingAutopilot.isEmpty)
    }

    // MARK: The bar

    @Test func theLineSaysHowLongAndHowManyDecisions() {
        let now = start.addingTimeInterval(3 * 60 + 4)
        #expect(AutopilotText.line(AutopilotRun(startedAt: start), now: now) == "3m 4s running")
        let decision = AutopilotDecision(kind: .allowed, title: "x", answer: "y", at: start)
        let timed = AutopilotRun(
            startedAt: start, until: now.addingTimeInterval(72 * 60), decisions: [decision])
        #expect(AutopilotText.line(timed, now: now) == "1h 12m left · 1 decision")
        var two = timed
        two.decisions.append(decision)
        #expect(AutopilotText.line(two, now: now) == "1h 12m left · 2 decisions")
    }

    @Test func theStepComesFromTheTaskList() {
        let tasks = [
            GoalsTests.task("1", .completed),
            GoalsTests.task("2", .deleted),
            GoalsTests.task("3", .inProgress, active: "Writing tests"),
            GoalsTests.task("4", .pending),
        ]
        #expect(AutopilotText.step(tasks) == "Step 2 of 3: Writing tests")
        #expect(AutopilotText.step([]) == nil)
        #expect(AutopilotText.step([GoalsTests.task("1", .completed)]) == nil)
    }

    // MARK: Nest's line

    // MARK: Habits

    @Test func aHabitsSwitchSavesOnlyWhenItChanges() {
        let habit = PixieHabitsTests.habit()
        var draft = HabitDraft(habit: habit)
        #expect(draft.update(from: habit).autopilot == nil)
        draft.autopilot = true
        #expect(draft.update(from: habit).autopilot == true)
        #expect(Fixture.json(draft.create).contains(#""autopilot":true"#))
    }
}
