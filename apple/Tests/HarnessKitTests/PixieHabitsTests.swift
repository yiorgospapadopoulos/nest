import Foundation
import Testing

@testable import HarnessKit

/// B42: a pixie's habits as the app shows and edits them: schedules and triggers in
/// words, the editor, the last and next run, the history and the store behind the page.
@MainActor @Suite struct PixieHabitsTests {
    nonisolated static func habitJSON(
        id: String = "h1", pixie: String = "p1", name: String = "Morning check",
        schedule: String = #"{"kind": "weekdays", "time": "09:00"}"#,
        triggers: String = #"["stuck", "ci_failed"]"#, enabled: Bool = true,
        nextDue: String = #""2026-10-15T09:00:00Z""#, lastRun: String = "null",
        updated: String = "2026-10-14T08:00:00Z"
    ) -> String {
        """
        {"id": "\(id)", "pixie_id": "\(pixie)", "name": "\(name)", "prompt": "Look at failing PRs",
         "schedule": \(schedule), "triggers": \(triggers), "max_minutes": 20,
         "enabled": \(enabled), "created_at": "2026-10-14T08:00:00Z",
         "updated_at": "\(updated)", "next_due_at": \(nextDue), "last_run": \(lastRun)}
        """
    }

    static func habit(
        id: String = "h1", pixie: String = "p1", name: String = "Morning check",
        schedule: String = #"{"kind": "weekdays", "time": "09:00"}"#,
        triggers: String = #"["stuck", "ci_failed"]"#, enabled: Bool = true,
        nextDue: String = #""2026-10-15T09:00:00Z""#, lastRun: String = "null",
        updated: String = "2026-10-14T08:00:00Z"
    ) -> PixieHabit {
        Fixture.decode(
            PixieHabit.self,
            json: habitJSON(
                id: id, pixie: pixie, name: name, schedule: schedule, triggers: triggers,
                enabled: enabled, nextDue: nextDue, lastRun: lastRun, updated: updated))
    }

    nonisolated static func runJSON(
        id: String = "r1", habit: String = "h1", outcome: String = "reported",
        started: String = #""2026-10-14T09:00:00Z""#, ended: String = #""2026-10-14T09:02:05Z""#,
        title: String = #""2 pull requests fail""#, reason: String = "null"
    ) -> String {
        """
        {"id": "\(id)", "habit_id": "\(habit)", "pixie_id": "p1", "session_id": "hs-\(id)",
         "due_at": "2026-10-14T09:00:00Z", "started_at": \(started), "ended_at": \(ended),
         "outcome": "\(outcome)", "reason": \(reason), "report_title": \(title)}
        """
    }

    static func run(
        id: String = "r1", habit: String = "h1", outcome: String = "reported",
        started: String = #""2026-10-14T09:00:00Z""#, ended: String = #""2026-10-14T09:02:05Z""#,
        title: String = #""2 pull requests fail""#, reason: String = "null"
    ) -> HabitRun {
        Fixture.decode(
            HabitRun.self,
            json: runJSON(
                id: id, habit: habit, outcome: outcome, started: started, ended: ended,
                title: title, reason: reason))
    }

    static var utc: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar
    }

    // MARK: Models

    @Test func aHabitDecodes() throws {
        let habit = Self.habit(lastRun: Self.runJSON())
        #expect(habit.id == "h1")
        #expect(habit.pixieID == "p1")
        #expect(habit.prompt == "Look at failing PRs")
        #expect(habit.schedule == .weekdays("09:00"))
        #expect(habit.triggers == [.stuck, .ciFailed])
        #expect(habit.maxMinutes == 20)
        #expect(habit.enabled)
        #expect(habit.nextDueAt == Fixture.date("2026-10-15T09:00:00Z"))
        let run = try #require(habit.lastRun)
        #expect(run.outcome == .reported)
        #expect(run.sessionID == "hs-r1")
        #expect(run.reportTitle == "2 pull requests fail")
        #expect(run.dueAt == Fixture.date("2026-10-14T09:00:00Z"))

        let bare = Self.habit(schedule: "null", nextDue: "null")
        #expect(bare.schedule == nil)
        #expect(bare.nextDueAt == nil)
        #expect(bare.lastRun == nil)

        let odd = Self.habit(
            schedule: #"{"kind": "monthly", "day": 3}"#, triggers: #"["review_ready", "moon"]"#)
        #expect(odd.schedule?.kind == .unknown)
        #expect(odd.triggers == [.reviewReady, .unknown])
        #expect(Self.run(outcome: "lost").outcome == .unknown)
    }

    @Test func schedulesEncodeAsTheDaemonReadsThem() {
        #expect(Fixture.json(HabitSchedule.hourly(minute: 15)) == #"{"kind":"hourly","minute":15}"#)
        #expect(Fixture.json(HabitSchedule.daily("07:30")) == #"{"kind":"daily","time":"07:30"}"#)
        #expect(
            Fixture.json(HabitSchedule.weekdays("09:00")) == #"{"kind":"weekdays","time":"09:00"}"#)
        #expect(
            Fixture.json(HabitSchedule.weekly(weekday: 4, time: "17:00"))
                == #"{"kind":"weekly","time":"17:00","weekday":4}"#)
    }

    @Test func requestsEncode() {
        let create = CreateHabitRequest(
            name: "Check", prompt: "Look", schedule: .daily("09:00"), triggers: [.failed],
            maxMinutes: 20)
        #expect(
            Fixture.json(create)
                == #"{"enabled":true,"max_minutes":20,"name":"Check","prompt":"Look","schedule":{"kind":"daily","time":"09:00"},"triggers":["failed"]}"#
        )
        let triggered = CreateHabitRequest(
            name: "On fail", prompt: "Look", schedule: nil, triggers: [.failed], maxMinutes: 5,
            enabled: false)
        #expect(
            Fixture.json(triggered)
                == #"{"enabled":false,"max_minutes":5,"name":"On fail","prompt":"Look","schedule":null,"triggers":["failed"]}"#
        )
        #expect(Fixture.json(UpdateHabitRequest(enabled: false)) == #"{"enabled":false}"#)
        #expect(
            Fixture.json(UpdateHabitRequest(clearsSchedule: true)) == #"{"schedule":null}"#)
        #expect(
            Fixture.json(
                UpdateHabitRequest(
                    name: "N", prompt: "P", schedule: .hourly(minute: 0), triggers: [],
                    maxMinutes: 30))
                == #"{"max_minutes":30,"name":"N","prompt":"P","schedule":{"kind":"hourly","minute":0},"triggers":[]}"#
        )
        #expect(Fixture.json(UpdateHabitRequest()) == "{}")
    }

    // MARK: In words

    @Test func schedulesReadPlainly() {
        #expect(HabitText.schedule(.hourly(minute: 15)) == "Every hour at :15")
        #expect(HabitText.schedule(.hourly(minute: 5)) == "Every hour at :05")
        #expect(HabitText.schedule(.daily("07:30")) == "Every day at 07:30")
        #expect(HabitText.schedule(.weekdays("09:00")) == "Weekdays at 09:00")
        #expect(HabitText.schedule(.weekly(weekday: 0, time: "08:00")) == "Mondays at 08:00")
        #expect(HabitText.schedule(.weekly(weekday: 6, time: "18:00")) == "Sundays at 18:00")
        #expect(HabitText.schedule(.weekly(weekday: 9, time: "18:00")) == "Weekly at 18:00")
        #expect(
            HabitText.schedule(HabitSchedule(kind: .unknown, minute: nil, time: nil, weekday: nil))
                == "On a schedule")
        #expect(HabitText.schedule(.hourly(minute: nil)) == "Every hour at :00")
        #expect(HabitText.schedule(.daily(nil)) == "Every day at 00:00")
    }

    @Test func triggersReadPlainly() {
        #expect(HabitText.triggers([]) == nil)
        #expect(HabitText.triggers([.stuck]) == "When a chat is stuck")
        #expect(HabitText.triggers([.stuck, .failed]) == "When a chat is stuck or fails")
        #expect(
            HabitText.triggers([.stuck, .failed, .reviewReady, .ciFailed])
                == "When a chat is stuck, fails, is ready for review or fails CI")
        #expect(HabitText.triggers([.unknown]) == nil)
        #expect(HabitTrigger.choices == [.stuck, .failed, .reviewReady, .ciFailed])
        #expect(
            HabitTrigger.choices.map(\.label) == [
                "A chat is stuck", "A chat fails", "A chat is ready for review",
                "A pull request's checks fail",
            ])
        #expect(HabitTrigger.unknown.label == "")
    }

    @Test func aHabitsSummaryJoinsScheduleAndTriggers() {
        #expect(Self.habit().summary == "Weekdays at 09:00 · When a chat is stuck or fails CI")
        #expect(Self.habit(triggers: "[]").summary == "Weekdays at 09:00")
        #expect(
            Self.habit(schedule: "null", triggers: #"["failed"]"#).summary == "When a chat fails")
        #expect(Self.habit(schedule: "null", triggers: "[]").summary == "")
    }

    @Test func outcomesReadAsWords() {
        let words = [
            HabitRunOutcome.queued, .running, .reported, .quiet, .failed, .stalled, .timedOut,
            .skipped, .unknown,
        ].map(\.label)
        #expect(
            words == [
                "Queued", "Running", "Reported", "Quiet", "Failed", "Stalled", "Timed out",
                "Skipped", "Unknown",
            ])
        #expect(HabitRunOutcome.reported.tone == .review)
        #expect(HabitRunOutcome.running.tone == .running)
        #expect(HabitRunOutcome.queued.tone == .running)
        #expect(HabitRunOutcome.failed.tone == .failed)
        #expect(HabitRunOutcome.timedOut.tone == .failed)
        #expect(HabitRunOutcome.stalled.tone == .waiting)
        #expect(HabitRunOutcome.quiet.tone == .done)
        #expect(HabitRunOutcome.skipped.tone == .interrupted)
        #expect(HabitRunOutcome.unknown.tone == .done)
        #expect(HabitRunOutcome.running.isActive)
        #expect(HabitRunOutcome.queued.isActive)
        #expect(!HabitRunOutcome.quiet.isActive)
    }

    @Test func theLastAndNextRunReadPlainly() {
        let now = Fixture.date("2026-10-14T12:00:00Z")
        let calendar = Self.utc
        #expect(HabitText.lastRun(nil, now: now, calendar: calendar) == "Not run yet")
        #expect(
            HabitText.lastRun(Self.run(), now: now, calendar: calendar) == "Reported 09:02")
        #expect(
            HabitText.lastRun(
                Self.run(outcome: "running", ended: "null"), now: now, calendar: calendar)
                == "Running since 09:00")
        #expect(
            HabitText.lastRun(
                Self.run(outcome: "queued", started: "null", ended: "null"), now: now,
                calendar: calendar) == "Queued")
        #expect(
            HabitText.lastRun(
                Self.run(outcome: "skipped", started: "null", ended: "null", reason: #""late""#),
                now: now, calendar: calendar) == "Skipped 09:00 (late)")
        #expect(
            HabitText.lastRun(
                Self.run(outcome: "running", started: "null", ended: "null"), now: now,
                calendar: calendar) == "Running since now")
        var undated = Self.run(outcome: "quiet", started: "null", ended: "null")
        undated.dueAt = nil
        #expect(HabitText.lastRun(undated, now: now, calendar: calendar) == "Quiet")

        #expect(
            HabitText.nextRun(Self.habit(), now: now, calendar: calendar) == "Next 15 Oct 09:00")
        #expect(
            HabitText.nextRun(
                Self.habit(nextDue: #""2026-10-14T17:00:00Z""#), now: now, calendar: calendar)
                == "Next 17:00")
        #expect(
            HabitText.nextRun(Self.habit(enabled: false), now: now, calendar: calendar) == "Paused")
        #expect(
            HabitText.nextRun(
                Self.habit(schedule: "null", nextDue: "null"), now: now, calendar: calendar)
                == "Runs on events")
    }

    @Test func historyRowsReadPlainly() {
        let now = Fixture.date("2026-10-14T12:00:00Z")
        let calendar = Self.utc
        let run = Self.run()
        #expect(HabitText.started(run, now: now, calendar: calendar) == "09:00")
        #expect(HabitText.duration(run, now: now) == "2m 5s")
        let running = Self.run(outcome: "running", ended: "null")
        #expect(HabitText.duration(running, now: now) == "3h")
        let skipped = Self.run(outcome: "skipped", started: "null", ended: "null")
        #expect(HabitText.started(skipped, now: now, calendar: calendar) == "Due 09:00")
        #expect(HabitText.duration(skipped, now: now) == nil)
        var never = skipped
        never.dueAt = nil
        #expect(HabitText.started(never, now: now, calendar: calendar) == "")
        #expect(HabitText.emptyHistory == "No runs yet.")
        #expect(
            HabitText.emptyList
                == "No habits yet. A habit runs on a schedule or when chats need attention, and reports what it finds."
        )
    }

    // MARK: Editor

    @Test func aNewDraftStartsDailyAtNine() {
        let draft = HabitDraft()
        #expect(draft.repeats == .daily)
        #expect(draft.time == "09:00")
        #expect(draft.maxMinutes == 20)
        #expect(draft.schedule == .daily("09:00"))
        #expect(draft.problem == "Name the habit")
        #expect(
            HabitDraft.Repeat.allCases.map(\.label) == [
                "No schedule", "Every hour", "Every day", "Weekdays", "Weekly",
            ])
        #expect(HabitDraft.maxMinutesRange == 1...120)
        #expect(HabitDraft.weekdayNames.count == 7)
        #expect(HabitDraft.weekdayNames.first == "Monday")
    }

    @Test func aDraftBuildsEachSchedule() {
        var draft = HabitDraft()
        draft.hour = 7
        draft.minute = 5
        draft.repeats = .hourly
        draft.hourlyMinute = 45
        #expect(draft.schedule == .hourly(minute: 45))
        draft.repeats = .daily
        #expect(draft.schedule == .daily("07:05"))
        draft.repeats = .weekdays
        #expect(draft.schedule == .weekdays("07:05"))
        draft.repeats = .weekly
        draft.weekday = 2
        #expect(draft.schedule == .weekly(weekday: 2, time: "07:05"))
        draft.repeats = .never
        #expect(draft.schedule == nil)
    }

    @Test func aDraftSaysWhatIsMissing() {
        var draft = HabitDraft()
        draft.name = "  "
        #expect(draft.problem == "Name the habit")
        draft.name = String(repeating: "a", count: 61)
        #expect(draft.problem == "A name has at most 60 characters")
        draft.name = "Check"
        #expect(draft.problem == "Say what it should check")
        draft.prompt = String(repeating: "b", count: 4001)
        #expect(draft.problem == "The instructions have at most 4000 characters")
        draft.prompt = "Look"
        #expect(draft.problem == nil)
        draft.repeats = .never
        #expect(draft.problem == "Choose a schedule or at least one trigger")
        draft.triggers = [.failed]
        #expect(draft.problem == nil)
    }

    @Test func aDraftComesFromAHabitAndSavesOnlyChanges() {
        let habit = Self.habit(
            schedule: #"{"kind": "weekly", "weekday": 3, "time": "17:45"}"#,
            triggers: #"["failed"]"#)
        var draft = HabitDraft(habit: habit)
        #expect(draft.name == "Morning check")
        #expect(draft.prompt == "Look at failing PRs")
        #expect(draft.repeats == .weekly)
        #expect(draft.weekday == 3)
        #expect(draft.hour == 17)
        #expect(draft.minute == 45)
        #expect(draft.triggers == [.failed])
        #expect(draft.maxMinutes == 20)
        #expect(draft.update(from: habit) == UpdateHabitRequest())

        draft.name = " Evening check "
        draft.triggers = [.failed, .stuck]
        draft.maxMinutes = 30
        draft.prompt = "New"
        draft.repeats = .hourly
        draft.hourlyMinute = 10
        #expect(
            draft.update(from: habit)
                == UpdateHabitRequest(
                    name: "Evening check", prompt: "New", schedule: .hourly(minute: 10),
                    triggers: [.stuck, .failed], maxMinutes: 30))

        draft.repeats = .never
        #expect(draft.update(from: habit).clearsSchedule)
        #expect(draft.update(from: habit).schedule == nil)

        let hourly = HabitDraft(habit: Self.habit(schedule: #"{"kind": "hourly", "minute": 20}"#))
        #expect(hourly.repeats == .hourly)
        #expect(hourly.hourlyMinute == 20)
        #expect(hourly.time == "09:00")
        let bareHourly = HabitDraft(habit: Self.habit(schedule: #"{"kind": "hourly"}"#))
        #expect(bareHourly.hourlyMinute == 0)
        let bareWeekly = HabitDraft(
            habit: Self.habit(schedule: #"{"kind": "weekly", "time": "08:15"}"#))
        #expect(bareWeekly.weekday == 0)
        #expect(bareWeekly.time == "08:15")
        let none = HabitDraft(habit: Self.habit(schedule: "null"))
        #expect(none.repeats == .never)
        let odd = HabitDraft(habit: Self.habit(schedule: #"{"kind": "daily", "time": "late"}"#))
        #expect(odd.time == "09:00")
        let strange = HabitDraft(habit: Self.habit(schedule: #"{"kind": "yearly"}"#))
        #expect(strange.repeats == .daily)
    }

    @Test func aDraftMakesTheCreateRequest() {
        var draft = HabitDraft()
        draft.name = " Check "
        draft.prompt = " Look \n"
        draft.triggers = [.ciFailed, .stuck]
        #expect(
            draft.create
                == CreateHabitRequest(
                    name: "Check", prompt: "Look", schedule: .daily("09:00"),
                    triggers: [.stuck, .ciFailed], maxMinutes: 20))
    }

    @Test func aDraftTimeIsADateForThePicker() {
        let calendar = Self.utc
        var draft = HabitDraft()
        let base = Fixture.date("2026-10-14T12:34:00Z")
        #expect(draft.date(on: base, calendar: calendar) == Fixture.date("2026-10-14T09:00:00Z"))
        draft.setTime(Fixture.date("2026-10-20T18:25:00Z"), calendar: calendar)
        #expect(draft.hour == 18)
        #expect(draft.minute == 25)
        #expect(draft.time == "18:25")
    }

    @Test func aSuggestionIsADraft() {
        let suggestion = HabitSuggestion(
            name: "PR watch", prompt: "Check PRs", schedule: .hourly(minute: 30),
            triggers: [.ciFailed])
        let draft = HabitDraft(suggestion: suggestion)
        #expect(draft.name == "PR watch")
        #expect(draft.repeats == .hourly)
        #expect(draft.hourlyMinute == 30)
        #expect(draft.triggers == [.ciFailed])
        #expect(
            draft.create
                == CreateHabitRequest(
                    name: "PR watch", prompt: "Check PRs", schedule: .hourly(minute: 30),
                    triggers: [.ciFailed], maxMinutes: 20))
        #expect(suggestion.summary == "Every hour at :30 · When a chat fails CI")
        #expect(suggestion.isStarted(among: nil) == false)
        #expect(suggestion.isStarted(among: [Self.habit()]) == false)
        #expect(suggestion.isStarted(among: [Self.habit(name: "PR watch")]))
    }

    // MARK: Store

    @Test func theStoreLoadsAPixiesHabits() async throws {
        let api = FakeAPI()
        api.set { $0.habits = ["p1": [Self.habit(), Self.habit(id: "h2", name: "Second")]] }
        let store = HabitsStore(api: api)
        #expect(store.habits(of: "p1") == nil)
        try await store.load("p1")
        #expect(store.habits(of: "p1")?.map(\.id) == ["h1", "h2"])
        #expect(store.habit("h2", of: "p1")?.name == "Second")
        #expect(store.habit("h9", of: "p1") == nil)
        #expect(store.habit("h1", of: "p9") == nil)
        #expect(api.calls == ["pixieHabits p1"])
    }

    @Test func theStoreCreatesEditsPausesAndDeletes() async throws {
        let api = FakeAPI()
        api.set { $0.habits = ["p1": [Self.habit()]] }
        let store = HabitsStore(api: api)
        try await store.load("p1")

        let made = try await store.create(
            in: "p1",
            CreateHabitRequest(
                name: "New", prompt: "Look", schedule: nil, triggers: [.failed], maxMinutes: 5))
        #expect(store.habits(of: "p1")?.map(\.id) == ["h1", made.id])

        try await store.update("h1", in: "p1", UpdateHabitRequest(name: "Renamed"))
        #expect(store.habit("h1", of: "p1")?.name == "Renamed")

        try await store.setEnabled("h1", in: "p1", false)
        #expect(store.habit("h1", of: "p1")?.enabled == false)

        try await store.delete("h1", in: "p1")
        #expect(store.habits(of: "p1")?.map(\.id) == [made.id])
        #expect(
            api.calls == [
                "pixieHabits p1", "createHabit p1 New", "updateHabit p1 h1",
                "updateHabit p1 h1", "deleteHabit p1 h1",
            ])
    }

    @Test func runNowAndTheHistory() async throws {
        let api = FakeAPI()
        api.set {
            $0.habits = ["p1": [Self.habit()]]
            $0.habitRuns = ["h1": [Self.run(id: "r2"), Self.run(id: "r1", outcome: "quiet")]]
        }
        let store = HabitsStore(api: api)
        #expect(store.runs(of: "h1") == nil)
        try await store.loadRuns("h1", in: "p1")
        #expect(store.runs(of: "h1")?.map(\.id) == ["r2", "r1"])

        let queued = try await store.runNow("h1", in: "p1")
        #expect(queued.outcome == .queued)
        #expect(store.runs(of: "h1")?.map(\.id) == [queued.id, "r2", "r1"])
        #expect(api.calls == ["habitRuns p1 h1", "runHabit p1 h1"])
    }

    @Test func eventsKeepTheStoreCurrent() async throws {
        let api = FakeAPI()
        api.set {
            $0.habits = ["p1": [Self.habit()]]
            $0.habitRuns = ["h1": [Self.run(id: "r1")]]
        }
        let store = HabitsStore(api: api)
        // Before a pixie's habits are read, its events wait for the read.
        store.apply(
            Fixture.event(
                EventType.habitUpdated, #"{"habit": \#(Self.habitJSON(id: "h5", pixie: "p2"))}"#,
                session: nil))
        #expect(store.habits(of: "p2") == nil)

        try await store.load("p1")
        try await store.loadRuns("h1", in: "p1")
        // A new habit, then a newer copy of one.
        store.apply(
            Fixture.event(
                EventType.habitUpdated, #"{"habit": \#(Self.habitJSON(id: "h2", name: "B"))}"#,
                session: nil))
        store.apply(
            Fixture.event(
                EventType.habitUpdated,
                #"{"habit": \#(Self.habitJSON(name: "Renamed", updated: "2026-10-14T09:00:00Z"))}"#,
                session: nil))
        #expect(store.habits(of: "p1")?.map(\.name) == ["Renamed", "B"])
        // An older copy arriving late is ignored.
        store.apply(
            Fixture.event(
                EventType.habitUpdated,
                #"{"habit": \#(Self.habitJSON(name: "Old", updated: "2026-10-14T07:00:00Z"))}"#,
                session: nil))
        #expect(store.habit("h1", of: "p1")?.name == "Renamed")

        // A run starts, then ends: the history and the habit's last run follow it.
        store.apply(
            Fixture.event(
                EventType.habitRunUpdated,
                #"{"run": \#(Self.runJSON(id: "r2", outcome: "running", ended: "null"))}"#,
                session: nil))
        #expect(store.runs(of: "h1")?.map(\.id) == ["r2", "r1"])
        #expect(store.habit("h1", of: "p1")?.lastRun?.outcome == .running)
        store.apply(
            Fixture.event(
                EventType.habitRunUpdated,
                #"{"run": \#(Self.runJSON(id: "r2", outcome: "quiet"))}"#,
                session: nil))
        #expect(store.runs(of: "h1")?.map(\.outcome) == [.quiet, .reported])
        #expect(store.habit("h1", of: "p1")?.lastRun?.outcome == .quiet)
        // A queued run joins the history but is not the last run yet.
        store.apply(
            Fixture.event(
                EventType.habitRunUpdated,
                #"{"run": \#(Self.runJSON(id: "r3", outcome: "queued", started: "null", ended: "null"))}"#,
                session: nil))
        #expect(store.runs(of: "h1")?.first?.id == "r3")
        #expect(store.habit("h1", of: "p1")?.lastRun?.id == "r2")
        // Runs of habits whose history is not open change only the habit.
        store.apply(
            Fixture.event(
                EventType.habitRunUpdated, #"{"run": \#(Self.runJSON(id: "r7", habit: "h2"))}"#,
                session: nil))
        #expect(store.runs(of: "h2") == nil)
        #expect(store.habit("h2", of: "p1")?.lastRun?.id == "r7")
        // A run of an unknown habit changes nothing.
        store.apply(
            Fixture.event(
                EventType.habitRunUpdated, #"{"run": \#(Self.runJSON(id: "r8", habit: "h9"))}"#,
                session: nil))

        store.apply(
            Fixture.event(
                EventType.habitDeleted, #"{"id": "h1", "pixie_id": "p1"}"#, session: nil))
        #expect(store.habits(of: "p1")?.map(\.id) == ["h2"])
        #expect(store.runs(of: "h1") == nil)
        store.apply(Fixture.event(EventType.sessionNotice, #"{"text": "x"}"#))
        #expect(store.habits(of: "p1")?.count == 1)
    }

    @Test func aDeletedPixieTakesItsHabits() async throws {
        let api = FakeAPI()
        api.set { $0.habits = ["p1": [Self.habit()]] }
        let store = HabitsStore(api: api)
        try await store.load("p1")
        store.apply(Fixture.event(EventType.pixieDeleted, #"{"pixie_id": "p1"}"#, session: nil))
        #expect(store.habits(of: "p1") == nil)
    }
}
