import Foundation
import Testing

@testable import NestKit

private var utc: Calendar {
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = TimeZone(identifier: "UTC")!
    return calendar
}

/// 2026-10-06 12:00 UTC, a Tuesday.
private let tuesday = Date(timeIntervalSince1970: 1_791_288_000)

/// A chat paused at the usage limit (B78).
@MainActor
@Suite struct LimitPauseTests {
    let api = FakeAPI()
    let approvals: ApprovalsStore
    let store: SessionsStore

    init() {
        approvals = ApprovalsStore(api: api)
        store = SessionsStore(api: api, approvals: approvals)
    }

    nonisolated static func pause(
        _ window: LimitPauseWindow? = .fiveHour, resets: Date? = tuesday.addingTimeInterval(3600)
    ) -> LimitPause {
        LimitPause(
            window: window, resetsAt: resets,
            resumeAt: (resets ?? tuesday.addingTimeInterval(1800)).addingTimeInterval(30),
            since: tuesday)
    }

    static func paused(_ id: String = "s1", _ pause: LimitPause? = pause()) -> Session {
        var session = Fixture.session(id, state: .idle)
        session.limitPause = pause
        return session
    }

    /// A session's JSON with this `limit_pause`, or without the field.
    func sessionJSON(limitPause: String?) -> String {
        let text = Fixture.json(Fixture.session())
        guard let limitPause else { return text }
        return String(text.dropLast()) + #","limit_pause":\#(limitPause)}"#
    }

    // MARK: Decoding

    @Test func aSessionCarriesItsPause() throws {
        let session = Fixture.decode(
            Session.self,
            json: sessionJSON(
                limitPause:
                    #"{"window": "five_hour", "resets_at": "2026-01-01T14:00:00Z", "resume_at": "2026-01-01T14:00:30Z", "since": "2026-01-01T12:00:00Z"}"#
            ))
        let pause = try #require(session.limitPause)
        #expect(pause.window == .fiveHour)
        #expect(pause.resetsAt == Fixture.date("2026-01-01T14:00:00Z"))
        #expect(pause.resumeAt == Fixture.date("2026-01-01T14:00:30Z"))
        #expect(pause.since == Fixture.date("2026-01-01T12:00:00Z"))
        #expect(session.isLimitPaused)
    }

    @Test func anUnsaidOrUnknownWindowIsReadSafely() {
        let unsaid = Fixture.decode(
            Session.self,
            json: sessionJSON(
                limitPause:
                    #"{"window": null, "resets_at": null, "resume_at": "2026-01-01T12:30:00Z", "since": "2026-01-01T12:00:00Z"}"#
            ))
        #expect(unsaid.limitPause?.window == nil)
        #expect(unsaid.limitPause?.resetsAt == nil)
        let future = Fixture.decode(
            Session.self,
            json: sessionJSON(
                limitPause:
                    #"{"window": "one_day", "resets_at": null, "resume_at": "2026-01-01T12:30:00Z", "since": "2026-01-01T12:00:00Z"}"#
            ))
        #expect(future.limitPause?.window == .unknown)
        let none = Fixture.decode(Session.self, json: sessionJSON(limitPause: "null"))
        #expect(none.limitPause == nil)
        #expect(!none.isLimitPaused)
        let older = Fixture.decode(Session.self, json: sessionJSON(limitPause: nil))
        #expect(older.limitPause == nil)
    }

    @Test func thePauseSurvivesEncoding() throws {
        let session = Self.paused()
        let again = Fixture.decode(Session.self, json: Fixture.json(session))
        #expect(again.limitPause == session.limitPause)
    }

    // MARK: The store

    @Test func sessionUpdatesSetAndClearThePause() async throws {
        api.set { $0.sessions = [Fixture.session("s1", state: .idle)] }
        try await store.load()
        store.apply(
            Fixture.event(
                EventType.sessionUpdated,
                #"{"changes": {}, "session": \#(Fixture.json(Self.paused()))}"#))
        #expect(store.session("s1")?.limitPause == Self.pause())
        store.apply(
            Fixture.event(
                EventType.sessionUpdated,
                #"{"changes": {"limit_pause": null}, "session": \#(Fixture.json(Self.paused("s1", nil)))}"#,
                id: 2))
        #expect(store.session("s1")?.limitPause == nil)
    }

    /// A paused chat reads as paused in the interrupted grey, not failed nor done, and
    /// needs nothing from the user (as on the iPhone).
    @Test func aPausedChatIsPaused() async throws {
        api.set { $0.sessions = [Self.paused("p"), Fixture.session("idle", state: .idle)] }
        try await store.load()
        let paused = try #require(store.session("p"))
        #expect(store.tone(of: paused) == .interrupted)
        #expect(store.statusLabel(of: paused) == "Paused")
        #expect(!store.needsYou(paused))
        #expect(store.group(of: paused) == .idle)
        #expect(store.cardState(of: paused) == "Paused")
        let idle = try #require(store.session("idle"))
        #expect(store.tone(of: idle) == .done)
        #expect(store.statusLabel(of: idle) == "Idle")
        #expect(store.cardState(of: idle) == "Idle")
        // Only an idle chat reads as paused.
        var running = paused
        running.state = .running
        #expect(store.tone(of: running) == .running)
        #expect(store.statusLabel(of: running) == "Running")
    }

    /// Pending reviews, merges and prompts come before the pause.
    @Test func pendingWorkShowsBeforeThePause() async throws {
        api.set { $0.sessions = [Self.paused("s1"), Self.paused("s2")] }
        try await store.load()
        var review = Fixture.approval("ap-review")
        review.sessionID = "s1"
        approvals.apply(.approvalCreated(review))
        let session = try #require(store.session("s1"))
        #expect(store.tone(of: session) == .review)
        #expect(store.statusLabel(of: session) == "Ready for review")
        var merge = Fixture.approval("ap-review")
        merge.id = "m"
        merge.sessionID = "s2"
        merge.kind = .merge
        approvals.apply(.approvalCreated(merge))
        let merging = try #require(store.session("s2"))
        #expect(store.tone(of: merging) == .review)
        #expect(store.statusLabel(of: merging) == "Ready to merge")
        var question = Fixture.approval("ap-perm")
        question.id = "q"
        question.sessionID = "s1"
        question.kind = .question
        approvals.apply(.approvalCreated(question))
        #expect(store.tone(of: session) == .waiting)
        #expect(store.statusLabel(of: session) == "Question")
    }

    @Test func resumeNowEndsThePauseAtOnce() async throws {
        api.set { $0.sessions = [Self.paused("s1")] }
        try await store.load()
        try await store.resumeAfterLimit("s1")
        #expect(api.calls.last == "resumeLimit s1")
        #expect(store.session("s1")?.limitPause == nil)
        #expect(store.resumingLimit.isEmpty)
    }

    @Test func resumeNowIsBusyUntilTheDaemonAnswers() async throws {
        let (gate, open) = AsyncStream<Void>.makeStream()
        api.set {
            $0.sessions = [Self.paused("s1")]
            $0.gates["resumeLimit"] = gate
        }
        try await store.load()
        let resuming = Task { try await store.resumeAfterLimit("s1") }
        while !api.calls.contains("resumeLimit s1") {
            await Task.yield()
        }
        #expect(store.resumingLimit == ["s1"])
        open.finish()
        try await resuming.value
        #expect(store.resumingLimit.isEmpty)
    }

    @Test func aRefusedResumeKeepsThePause() async throws {
        api.set { $0.sessions = [Self.paused("s1")] }
        try await store.load()
        api.fail("resumeLimit", with: APIError.openInClaudeCode("Open in Claude Code"))
        await #expect(throws: APIError.openInClaudeCode("Open in Claude Code")) {
            try await store.resumeAfterLimit("s1")
        }
        #expect(store.session("s1")?.limitPause != nil)
        #expect(store.resumingLimit.isEmpty)
    }

    // MARK: The turn the limit cut off

    @Test func aResultAtTheLimitIsNoFailure() async throws {
        let result = Fixture.decode(
            TurnResult.self,
            json:
                #"{"is_error": true, "subtype": "error_during_execution", "duration_ms": 3000, "num_turns": 1, "errors": ["limit"], "limit": true}"#
        )
        #expect(result.limit)
        #expect(!result.failed)
        let plain = Fixture.decode(
            TurnResult.self,
            json:
                #"{"is_error": true, "subtype": "error_during_execution", "num_turns": 1, "errors": []}"#
        )
        #expect(!plain.limit)
        #expect(plain.failed)

        let transcript = TranscriptStore(sessionID: "s1", api: api)
        try await transcript.load()
        transcript.receive(
            Fixture.event(
                EventType.sessionUserMessage, #"{"text": "go", "attachments": []}"#, id: 1,
                ts: "2026-10-06T09:00:00Z"))
        transcript.receive(
            Fixture.event(
                EventType.sessionResult,
                #"{"is_error": true, "subtype": "error_during_execution", "duration_ms": 3000, "num_turns": 1, "errors": ["limit"], "limit": true}"#,
                id: 2, ts: "2026-10-06T09:00:03Z"))
        transcript.receive(
            Fixture.event(
                EventType.sessionState, #"{"state": "idle", "error": null, "duration_ms": 3000}"#,
                id: 3, ts: "2026-10-06T09:00:04Z"))
        #expect(
            !transcript.visibleItems.contains { item in
                if case .result = item.content { true } else { false }
            })
        #expect(
            transcript.items.contains {
                $0.content == .turnEnd(TurnEnd(durationMS: 3_000, stopped: false))
            })
    }

    /// Nest's continue message shows as Nest's, and starts a turn as a message does.
    @Test func theContinueMessageIsNests() async throws {
        let transcript = TranscriptStore(sessionID: "s1", api: api)
        try await transcript.load()
        transcript.receive(
            Fixture.event(
                EventType.sessionUserMessage,
                #"{"text": "Continue where you left off.", "attachments": [], "from_pixie": null, "origin": "limit_resume"}"#,
                id: 5))
        #expect(transcript.items.map(\.content) == [.limitResume("Continue where you left off.")])
        #expect(transcript.turnStartedAt != nil)
        #expect(LimitResumeNote.title == "Resumed after the usage limit")
        #expect(
            LimitResumeNote.text("Continue where you left off.")
                == "Nest: Continue where you left off.")

        let unknown = Fixture.decode(
            UserMessage.self, json: #"{"text": "x", "attachments": [], "origin": "later"}"#)
        #expect(unknown.origin == .unknown)
    }

    @Test func theContinueMessageEndsTheTurnBeforeIt() {
        let call = TranscriptItem(
            id: "a",
            content: .tool(
                ToolCall(id: "a", name: "Bash", input: .object([:]), result: nil, isError: false)),
            eventID: 1)
        let resume = TranscriptItem(id: "r", content: .limitResume("Continue"), eventID: 2)
        let entries = TranscriptGrouping.entries([call, resume], live: true)
        guard case .item(let first) = entries.first, case .tool(let stopped) = first.content
        else {
            Issue.record("no call")
            return
        }
        #expect(stopped.stopped)
        let end = TranscriptItem(
            id: "end", content: .turnEnd(TurnEnd(durationMS: 1, stopped: false)), eventID: 3)
        let text = TranscriptItem(id: "t", content: .assistant("ok", streaming: false), eventID: 4)
        let ends = TranscriptGrouping.turnEnds(
            TranscriptGrouping.entries([text, end, resume], live: false))
        #expect(ends["r"] == nil)
        #expect(ends["t"] == "end")
    }

    // MARK: Notifications

    @Test func usageLimitNoticesHaveTheirOwnToggle() {
        let notice = Fixture.decode(
            Notice.self,
            json:
                #"{"kind": "usage_limit", "session_id": "s1", "repo": "cv-page", "title": "Fix", "text": "Paused at the 5-hour usage limit."}"#
        )
        #expect(notice.kind == .usageLimit)
        var preferences = NotificationPreferences()
        #expect(preferences.wants(.usageLimit))
        #expect(
            NotificationPolicy.content(for: notice, preferences: preferences, visibleChats: [])?
                .body == "Paused at the 5-hour usage limit.")
        preferences.usageLimit = false
        #expect(!preferences.wants(.usageLimit))
        #expect(
            NotificationPreferences.toggles.contains { $0.title == "Usage limit pauses" })
    }

    @Test func theUsageLimitToggleIsKept() {
        let memory = MemoryStore()
        let settings = SettingsStore(store: memory)
        #expect(settings.notifications.usageLimit)
        settings.notifications.usageLimit = false
        #expect(SettingsStore(store: memory).notifications.usageLimit == false)
    }
}

/// The words of a paused chat's notice above the composer (B78).
@Suite struct LimitPauseTextTests {
    @Test func eachWindowHasItsWord() {
        let windows: [LimitPauseWindow?] = [
            .fiveHour, .sevenDay, .sevenDayOpus, .sevenDaySonnet, .overage, .unknown, nil,
        ]
        #expect(
            windows.map(LimitPauseText.windowLabel) == [
                "5-hour", "weekly", "weekly Opus", "weekly Sonnet", "extra usage", "usage",
                "usage",
            ])
        #expect(
            LimitPauseText.title(LimitPauseTests.pause(.sevenDay))
                == "Paused at the weekly limit")
        #expect(
            LimitPauseText.title(LimitPauseTests.pause(nil)) == "Paused at the usage limit")
    }

    @Test func theCountdownSaysHowLongIsLeft() {
        func left(_ seconds: TimeInterval) -> String {
            LimitPauseText.countdown(to: tuesday.addingTimeInterval(seconds), now: tuesday)
        }
        #expect(left(45) == "in 45 s")
        #expect(left(45.9) == "in 45 s")
        #expect(left(60) == "in 1 min")
        #expect(left(4 * 60 + 12) == "in 4 min 12 s")
        #expect(left(5 * 60 + 12) == "in 5 min")
        #expect(left(45 * 60) == "in 45 min")
        #expect(left(3600) == "in 1 h")
        #expect(left(3600 + 12 * 60 + 30) == "in 1 h 12 min")
        #expect(left(2 * 86_400) == "in 2 d")
        #expect(left(2 * 86_400 + 5 * 3600 + 59) == "in 2 d 5 h")
        #expect(left(0.5) == "any moment now")
        #expect(left(0) == "any moment now")
        #expect(left(-30) == "any moment now")
    }

    @Test func timesAreLocalAndAsShortAsTheyCanBe() {
        func time(_ seconds: TimeInterval) -> String {
            LimitPauseText.time(tuesday.addingTimeInterval(seconds), now: tuesday, calendar: utc)
        }
        #expect(time(2 * 3600 + 5 * 60) == "14:05")
        #expect(time(-3600) == "11:00")
        #expect(time(86_400 - 3600) == "Wed 11:00")
        #expect(time(5 * 86_400) == "Sun 12:00")
        #expect(time(6 * 86_400) == "12 Oct 12:00")
        var athens = utc
        athens.timeZone = TimeZone(identifier: "Europe/Athens")!
        #expect(LimitPauseText.time(tuesday, now: tuesday, calendar: athens) == "15:00")
    }

    @Test func theScheduleSaysWhenItGoesOn() {
        let pause = LimitPauseTests.pause(resets: tuesday.addingTimeInterval(3600))
        #expect(
            LimitPauseText.schedule(pause, now: tuesday, calendar: utc)
                == "Resets 13:00, goes on in 1 h")
        #expect(
            LimitPauseText.schedule(pause, now: tuesday.addingTimeInterval(3630), calendar: utc)
                == "Resets 13:00, goes on any moment now")
        let unsaid = LimitPauseTests.pause(nil, resets: nil)
        #expect(
            LimitPauseText.schedule(unsaid, now: tuesday, calendar: utc)
                == "Reset time not reported, tries again in 30 min")
    }

    @Test func thePlanSaysWhatHappensThen() {
        #expect(LimitPauseText.plan(queued: 0) == "Then it continues where it left off.")
        #expect(LimitPauseText.plan(queued: 1) == "Then your queued message sends.")
        #expect(LimitPauseText.plan(queued: 3) == "Then your 3 queued messages send, in order.")
    }
}
