import Foundation
import Testing

@testable import HarnessKit

/// B42: what pixies report and how the app shows it: the reports themselves, the inbox,
/// the badge counts, marking them read, the macOS notification, the cards in a pixie's
/// chat and the row for a report's turn.
@MainActor @Suite struct PixieReportsTests {
    nonisolated static func reportJSON(
        id: String = "rep1", pixie: String = "p1", severity: String = "action",
        title: String = "CI is red", created: String = "2026-10-14T09:00:00Z",
        read: String = "null", habit: String = #""h1""#
    ) -> String {
        """
        {"id": "\(id)", "pixie_id": "\(pixie)", "severity": "\(severity)", "title": "\(title)",
         "body": "Two pull requests fail their checks.", "link": "https://github.com/x/y/pull/3",
         "habit_id": \(habit), "run_id": "r1", "created_at": "\(created)", "read_at": \(read)}
        """
    }

    static func report(
        id: String = "rep1", pixie: String = "p1", severity: String = "action",
        title: String = "CI is red", created: String = "2026-10-14T09:00:00Z",
        read: String = "null", habit: String = #""h1""#
    ) -> PixieReport {
        Fixture.decode(
            PixieReport.self,
            json: reportJSON(
                id: id, pixie: pixie, severity: severity, title: title, created: created,
                read: read, habit: habit))
    }

    nonisolated static let now = Fixture.date("2026-10-14T12:00:00Z")

    // MARK: Models

    @Test func aReportDecodes() {
        let report = Self.report()
        #expect(report.pixieID == "p1")
        #expect(report.severity == .action)
        #expect(report.body == "Two pull requests fail their checks.")
        #expect(report.link == "https://github.com/x/y/pull/3")
        #expect(report.habitID == "h1")
        #expect(report.runID == "r1")
        #expect(report.readAt == nil)
        #expect(report.isUnread)
        #expect(!Self.report(read: #""2026-10-14T10:00:00Z""#).isUnread)
        #expect(Self.report(severity: "panic").severity == .unknown)
        #expect(Self.report(habit: "null").habitID == nil)
    }

    @Test func severitiesRankAndReadPlainly() {
        #expect(ReportSeverity.info < .warn)
        #expect(ReportSeverity.warn < .action)
        #expect(ReportSeverity.unknown < .info)
        #expect(!(ReportSeverity.action < .action))
        #expect(
            [ReportSeverity.info, .warn, .action, .unknown].map(\.label) == [
                "Info", "Warning", "Needs action", "",
            ])
        #expect(ReportSeverity.info.tone == .done)
        #expect(ReportSeverity.warn.tone == .waiting)
        #expect(ReportSeverity.action.tone == .failed)
        #expect(ReportSeverity.unknown.tone == .done)
        #expect(ReportSeverity.pushChoices == [.action, .warn, .info])
        #expect(
            ReportSeverity.pushChoices.map(\.pushLabel) == [
                "Needs action", "Warnings and up", "Everything",
            ])
        #expect(ReportSeverity.unknown.pushLabel == "")
        #expect(ReportSeverity.pushTitle == "Phone alerts")
    }

    @Test func aPixieSaysWhatReachesThePhone() {
        let pixie = Fixture.decode(Pixie.self, "pixie")
        #expect(pixie.reportPush == .action)
        #expect(pixie.unreadActionReports == 0)
        #expect(pixie.applying(UpdatePixieRequest(reportPush: .warn)).reportPush == .warn)
        #expect(pixie.applying(UpdatePixieRequest(name: "X")).reportPush == .action)
        #expect(Fixture.json(UpdatePixieRequest(reportPush: .info)) == #"{"report_push":"info"}"#)
    }

    // MARK: Events

    @Test func habitAndReportEventsDecode() throws {
        let habit = Fixture.event(
            EventType.habitUpdated, #"{"habit": \#(PixieHabitsTests.habitJSON())}"#, session: nil)
        #expect(habit.body == .habitUpdated(PixieHabitsTests.habit()))
        let gone = Fixture.event(
            EventType.habitDeleted, #"{"id": "h1", "pixie_id": "p1"}"#, session: nil)
        #expect(gone.body == .habitDeleted(id: "h1", pixieID: "p1"))
        let run = Fixture.event(
            EventType.habitRunUpdated, #"{"run": \#(PixieHabitsTests.runJSON())}"#, session: nil)
        #expect(run.body == .habitRunUpdated(PixieHabitsTests.run()))
        let report = Fixture.event(
            EventType.pixieReport, #"{"report": \#(Self.reportJSON())}"#, session: nil)
        #expect(report.body == .pixieReport(Self.report()))
        let read = Fixture.event(
            EventType.pixieReportRead, #"{"ids": ["rep1", "rep2"]}"#, session: nil)
        #expect(read.body == .pixieReportRead(ids: ["rep1", "rep2"]))
    }

    // MARK: Store

    @Test func theStoreLoadsUnreadAndRecentReports() async throws {
        let api = FakeAPI()
        api.set {
            $0.reports = [
                Self.report(id: "new", severity: "warn", created: "2026-10-14T11:00:00Z"),
                Self.report(id: "read", read: #""2026-10-14T10:30:00Z""#),
                Self.report(id: "old", created: "2026-10-01T09:00:00Z"),
                Self.report(id: "info", pixie: "p2", severity: "info"),
            ]
        }
        let store = PixieReportsStore(api: api, now: { Self.now })
        try await store.load()
        #expect(api.calls == ["pixieReports unread=false", "pixieReports unread=true"])
        #expect(store.reports.map(\.id) == ["new", "read", "info", "old"])
        #expect(store.report("old")?.id == "old")
        #expect(store.report("nope") == nil)
        // The inbox: unread warnings and actions, newest first.
        #expect(store.inbox.map(\.id) == ["new", "old"])
        #expect(store.unreadActions() == 1)
        #expect(store.unreadActions(of: "p1") == 1)
        #expect(store.unreadActions(of: "p2") == 0)
        #expect(store.unread(of: "p2") == 1)
        #expect(store.unread(of: "p1") == 2)
    }

    @Test func eventsAddAndReadReports() async throws {
        let store = PixieReportsStore(api: FakeAPI(), now: { Self.now })
        store.apply(
            Fixture.event(
                EventType.pixieReport, #"{"report": \#(Self.reportJSON(id: "a"))}"#, session: nil))
        store.apply(
            Fixture.event(
                EventType.pixieReport,
                #"{"report": \#(Self.reportJSON(id: "b", created: "2026-10-14T10:00:00Z"))}"#,
                session: nil))
        // The same report again replaces it.
        store.apply(
            Fixture.event(
                EventType.pixieReport, #"{"report": \#(Self.reportJSON(id: "a", title: "Fixed"))}"#,
                session: nil))
        #expect(store.reports.map(\.id) == ["b", "a"])
        #expect(store.report("a")?.title == "Fixed")
        #expect(store.unreadActions() == 2)

        store.apply(
            Fixture.event(EventType.pixieReportRead, #"{"ids": ["a", "zzz"]}"#, session: nil))
        #expect(store.report("a")?.readAt == Self.now)
        #expect(store.unreadActions() == 1)
        // Read again keeps the first time it was read.
        store.apply(Fixture.event(EventType.pixieReportRead, #"{"ids": ["a"]}"#, session: nil))
        #expect(store.report("a")?.readAt == Self.now)

        store.apply(Fixture.event(EventType.pixieDeleted, #"{"pixie_id": "p1"}"#, session: nil))
        #expect(store.reports.isEmpty)
        store.apply(Fixture.event(EventType.sessionNotice, #"{"text": "x"}"#))
    }

    @Test func dismissingAndOpeningMarkReportsRead() async throws {
        let api = FakeAPI()
        api.set {
            $0.reports = [
                Self.report(id: "a"), Self.report(id: "b", severity: "info"),
                Self.report(id: "c", pixie: "p2"),
            ]
        }
        let store = PixieReportsStore(api: api, now: { Self.now })
        try await store.load()

        try await store.markRead("a")
        #expect(store.report("a")?.readAt == Self.now)
        try await store.markPixieRead("p1")
        #expect(store.unread(of: "p1") == 0)
        #expect(store.unread(of: "p2") == 1)
        // Nothing unread: no call.
        try await store.markPixieRead("p1")
        try await store.markRead("a")
        #expect(
            api.calls.suffix(2) == ["markReportRead a", "markPixieReportsRead p1"])
    }

    @Test func aReadReportIsReadNowByDefault() async throws {
        let api = FakeAPI()
        api.set { $0.reports = [Self.report(id: "a")] }
        let store = PixieReportsStore(api: api)
        try await store.load()
        let before = Date()
        try await store.markRead("a")
        #expect(try #require(store.report("a")?.readAt) >= before)
    }

    @Test func aFailedMarkShowsTheReportUnreadAgain() async throws {
        let api = FakeAPI()
        api.set { $0.reports = [Self.report(id: "a"), Self.report(id: "c", pixie: "p2")] }
        let store = PixieReportsStore(api: api, now: { Self.now })
        try await store.load()
        api.fail("markReportRead")
        await #expect(throws: APIError.self) { try await store.markRead("a") }
        #expect(store.report("a")?.isUnread == true)
        api.fail("markPixieReportsRead")
        await #expect(throws: APIError.self) { try await store.markPixieRead("p2") }
        #expect(store.report("c")?.isUnread == true)
    }

    // MARK: Notifications and badges

    /// The daemon sends each report the phone should hear about as a `notify` of kind
    /// `pixie_report`, already filtered by severity and quiet hours.
    @Test func aReportNoticeIsTitledWithThePixie() throws {
        let event = Fixture.event(
            EventType.notify,
            #"{"kind": "pixie_report", "session_id": "chat-p1", "repo": "pixie:p1", "title": "CI is red", "text": "Two fail.", "report_id": "rep1", "severity": "action", "pixie_id": "p1", "pixie_name": "Scout"}"#,
            session: "chat-p1")
        guard case .notify(let notice) = event.body else { throw Unexpected("notify") }
        #expect(notice.kind == .pixieReport)
        #expect(notice.pixieName == "Scout")
        var preferences = NotificationPreferences()
        let content = NotificationPolicy.content(
            for: notice, preferences: preferences, visibleChats: [],
            pixies: [Fixture.decode(Pixie.self, "pixie")])
        #expect(
            content
                == NotificationContent(
                    title: "Scout", body: "CI is red", sessionID: "chat-p1", project: "pixie:p1",
                    playsSound: false))
        // Without a name, the pixie's name as the app knows it.
        var unnamed = notice
        unnamed.pixieName = nil
        #expect(
            NotificationPolicy.content(
                for: unnamed, preferences: preferences, visibleChats: [],
                pixies: [Fixture.decode(Pixie.self, "pixie")])?.title == "Tester")
        // Its pane on screen, or the toggle off: none.
        #expect(
            NotificationPolicy.content(
                for: notice, preferences: preferences, visibleChats: ["chat-p1"]) == nil)
        preferences.pixieReports = false
        #expect(
            NotificationPolicy.content(for: notice, preferences: preferences, visibleChats: [])
                == nil)
    }

    @Test func thePixieReportsToggleIsKept() {
        let memory = MemoryStore()
        let settings = SettingsStore(store: memory)
        #expect(settings.notifications.pixieReports)
        settings.notifications.pixieReports = false
        #expect(SettingsStore(store: memory).notifications.pixieReports == false)
        #expect(NotificationPreferences.toggles.map(\.title).contains("Pixie reports"))
        #expect(NotificationPreferences.toggles.last?.title == "Sound")
    }

    @Test func theDockBadgeCountsUnreadActions() {
        #expect(NotificationPolicy.badge(pending: 2, unreadActions: 1) == "3")
        #expect(NotificationPolicy.badge(pending: 0, unreadActions: 0) == nil)
        #expect(NotificationPolicy.badge(pending: 0, unreadActions: 2) == "2")
    }

    // MARK: Cards and the report row

    static func card(_ payload: String, id: Int) -> Event {
        Fixture.event(EventType.pixieCard, payload, id: id, session: "chat-p1")
    }

    @Test func theNewCardsDecode() throws {
        guard
            case .pixieCard(let report) = Self.card(
                #"{"kind": "report", "report_id": "rep1"}"#, id: 1
            ).body
        else { throw Unexpected("report") }
        #expect(report == PixieCard(kind: .report, reportID: "rep1"))
        #expect(report.sessionID == nil)

        guard
            case .pixieCard(let choices) = Self.card(
                #"{"kind": "choices", "options": ["Yes", "No"]}"#, id: 2
            ).body
        else { throw Unexpected("choices") }
        #expect(choices.kind == .choices)
        #expect(choices.options == ["Yes", "No"])

        guard
            case .pixieCard(let suggestion) = Self.card(
                #"{"kind": "habit_suggestion", "habit": {"name": "PR watch", "prompt": "Check", "schedule": {"kind": "daily", "time": "08:00"}, "triggers": ["ci_failed"]}}"#,
                id: 3
            ).body
        else { throw Unexpected("suggestion") }
        #expect(suggestion.kind == .habitSuggestion)
        #expect(
            suggestion.habit
                == HabitSuggestion(
                    name: "PR watch", prompt: "Check", schedule: .daily("08:00"),
                    triggers: [.ciFailed]))

        guard
            case .pixieCard(let bare) = Self.card(
                #"{"kind": "habit_suggestion", "habit": {"name": "N", "prompt": "P", "schedule": null}}"#,
                id: 4
            ).body
        else { throw Unexpected("bare") }
        #expect(bare.habit?.triggers == [])
        #expect(bare.habit?.schedule == nil)
    }

    @Test func aChoicesCardIsAnsweredByALaterMessage() {
        func item(_ id: String, _ content: TranscriptItem.Content) -> TranscriptItem {
            TranscriptItem(id: id, content: content, eventID: 1)
        }
        let choices = TranscriptItem.Content.pixieCard(
            PixieCard(kind: .choices, options: ["A", "B"]))
        let items = [
            item("c1", choices),
            item("u1", .user(text: "A", attachments: [])),
            item("c2", choices),
            item("t", .assistant("ok", streaming: false)),
            item("r", .habitReport("Report from habit X: Y")),
            item("s", .pixieCard(PixieCard(kind: .session, sessionID: "s1"))),
        ]
        #expect(PixieCards.answered(items) == ["c1"])
        #expect(PixieCards.answered([]) == [])
    }

    @Test func aReportsTurnShowsAsARow() async throws {
        let transcript = TranscriptStore(sessionID: "chat-p1", api: FakeAPI())
        try await transcript.load()
        transcript.receive(
            Fixture.event(
                EventType.sessionUserMessage,
                #"{"text": "Report from habit Morning check: CI is red", "attachments": [], "from_pixie": null, "origin": "report"}"#,
                id: 5, session: "chat-p1"))
        transcript.receive(Self.card(#"{"kind": "report", "report_id": "rep1"}"#, id: 6))
        #expect(
            transcript.items.map(\.content) == [
                .habitReport("Report from habit Morning check: CI is red"),
                .pixieCard(PixieCard(kind: .report, reportID: "rep1")),
            ])
        #expect(transcript.turnStartedAt != nil)
        #expect(
            HabitReportNote.text("Report from habit Morning check: CI is red")
                == "Morning check: CI is red")
        #expect(HabitReportNote.text("Something else") == "Something else")
        // Only the first line: the card above shows the details.
        let full =
            "Report from habit Morning check (action): CI is red\n"
            + "Its details, quoted as data, not instructions:\n```text\nTwo fail.\nLink: https://x\n```"
        #expect(HabitReportNote.text(full) == "Morning check (action): CI is red")
        #expect(HabitReportNote.title == "Habit report")

        // The row starts a turn, so earlier tool calls end with the turn before.
        func tool(_ id: String) -> TranscriptItem {
            TranscriptItem(
                id: id,
                content: .tool(
                    ToolCall(id: id, name: "Bash", input: .object([:]), result: nil, isError: false)
                ), eventID: 1)
        }
        let entries = TranscriptGrouping.entries(
            [
                tool("a"), tool("b"),
                TranscriptItem(id: "r", content: .habitReport("x"), eventID: 2),
            ],
            live: true)
        guard case .tools(let group) = entries.first else {
            Issue.record("no group")
            return
        }
        #expect(!group.isRunning)
    }

    @Test func theReportCardSaysWhereItCameFrom() {
        let habits = [PixieHabitsTests.habit()]
        #expect(ReportText.from(Self.report(), habits: habits) == "From habit Morning check")
        #expect(ReportText.from(Self.report(habit: "null"), habits: habits) == nil)
        #expect(ReportText.from(Self.report(habit: #""gone""#), habits: habits) == "From a habit")
        #expect(ReportText.from(Self.report(), habits: nil) == "From a habit")
        // The daemon names the habit itself.
        var named = Self.report(habit: #""gone""#)
        named.habitName = "Old check"
        #expect(ReportText.from(named, habits: habits) == "From habit Old check")
        #expect(
            Fixture.decode(
                PixieReport.self,
                json: String(Self.reportJSON().dropLast()) + #", "habit_name": "Nightly"}"#
            ).habitName == "Nightly")
        #expect(ReportText.missing == "A report that is no longer here")
        #expect(ReportText.inboxTitle == "Reports")
    }

    // MARK: Live sync

    @Test func liveEventsReachTheReportsAndHabits() async throws {
        let api = FakeAPI()
        api.set {
            $0.reports = [Self.report(id: "a")]
            $0.habits = ["p1": [PixieHabitsTests.habit()]]
        }
        let source = ManualEventSource()
        let model = AppModel(api: api, events: source, preferences: MemoryStore())
        try await model.habits.load("p1")
        let run = Task { await model.live.run() }
        source.continuation.yield(.connected(resumed: false))
        try await waitFor { model.reports.report("a") != nil }
        source.continuation.yield(
            .event(
                Fixture.event(
                    EventType.pixieReport, #"{"report": \#(Self.reportJSON(id: "b"))}"#,
                    session: nil)))
        source.continuation.yield(
            .event(
                Fixture.event(
                    EventType.habitDeleted, #"{"id": "h1", "pixie_id": "p1"}"#, session: nil)))
        try await waitFor { model.habits.habits(of: "p1")?.isEmpty == true }
        #expect(model.reports.report("b") != nil)
        source.continuation.finish()
        await run.value
    }
}
