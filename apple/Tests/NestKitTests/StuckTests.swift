import Foundation
import Testing

@testable import NestKit

enum StuckFixture {
    static let flagJSON = """
        {"reason": "repeating", "since": "2026-10-06T09:00:00Z",
         "details": "Called Bash 5 times in a row with the same input"}
        """

    static var flag: StuckFlag { Fixture.decode(StuckFlag.self, json: flagJSON) }

    static func session(_ id: String, stuck: Bool = true, archived: Bool = false) -> Session {
        var session = Fixture.session(id, state: .running, archived: archived)
        session.stuck = stuck ? flag : nil
        return session
    }
}

@Suite struct StuckModelTests {
    @Test func decodesTheFlagOnSessionsAndEvents() throws {
        let flag = StuckFixture.flag
        #expect(flag.reason == .repeating)
        #expect(flag.since == Date(timeIntervalSince1970: 1_791_277_200))
        #expect(flag.details == "Called Bash 5 times in a row with the same input")
        #expect(Fixture.sessions[0].stuck == nil)

        let json = Fixture.json(Fixture.sessions[0]).dropLast()
        let flagged = Fixture.decode(
            Session.self, json: json + #","stuck":\#(StuckFixture.flagJSON)}"#)
        #expect(flagged.stuck == flag)

        let stuck = Fixture.event(EventType.sessionStuck, StuckFixture.flagJSON)
        #expect(stuck.body == .stuck(flag))
        let unstuck = Fixture.event(EventType.sessionUnstuck, #"{"reason": "long_turn"}"#)
        #expect(unstuck.body == .unstuck(reason: .longTurn))
        let notice = Fixture.event(
            EventType.notify,
            #"{"kind": "stuck", "session_id": "s1", "repo": "todo-ui", "title": "T", "text": "x"}"#)
        guard case .notify(let read) = notice.body else { throw Unexpected(notice.body) }
        #expect(read.kind == .stuck)
    }

    @Test func reasonsHaveLabels() {
        let reasons: [StuckReason] = [.waiting, .silent, .repeating, .longTurn, .unknown]
        #expect(
            reasons.map(\.label) == [
                "Waiting too long", "No new output", "Repeating a call", "Very long turn",
                "Looks stuck",
            ])
        #expect(StuckReason(rawValue: "long_turn") == .longTurn)
    }

    @Test func theNudgeQuotesTheDetailsInTheSentence() {
        let flag = StuckFixture.flag
        #expect(flag.help == "Repeating a call: Called Bash 5 times in a row with the same input")
        #expect(
            flag.nudge
                == "You seem stuck: called Bash 5 times in a row with the same input. Step back and try a different approach."
        )
        let silent = StuckFlag(
            reason: .silent, since: Date(timeIntervalSince1970: 0),
            details: "No new output for 12 minutes")
        #expect(silent.nudge.hasPrefix("You seem stuck: no new output for 12 minutes. Step back"))
        let empty = StuckFlag(reason: .silent, since: .now, details: "")
        #expect(empty.nudge.hasPrefix("You seem stuck: . "))
    }

    @Test func thresholdsReadAndWriteTheirSetting() {
        var settings = StuckSettings(
            waitingMinutes: 15, silentMinutes: 10, repeatedCalls: 4, turnMinutes: 60)
        #expect(
            StuckThreshold.allCases.map { settings[keyPath: $0.keyPath] } == [15, 10, 4, 60])
        settings[keyPath: StuckThreshold.turn.keyPath] = 90
        #expect(settings.turnMinutes == 90)
        #expect(
            StuckThreshold.allCases.map(\.title) == [
                "Waiting on a prompt", "No new output", "Same call repeated", "One turn running",
            ])
    }

    @Test func choicesIncludeOffAndTheCurrentValue() {
        #expect(StuckThreshold.waiting.choices(including: 15) == [0, 5, 10, 15, 20, 30, 45, 60])
        #expect(StuckThreshold.silent.choices(including: 7) == [0, 5, 7, 10, 15, 20, 30, 45, 60])
        #expect(StuckThreshold.repeated.choices(including: 4) == [0, 3, 4, 5, 6, 8, 10])
        #expect(StuckThreshold.turn.choices(including: 240).last == 240)
        #expect(StuckThreshold.turn.choices(including: 60).first == 0)
    }

    @Test func labelsReadAsDurationsOrCounts() {
        let turn = StuckThreshold.turn
        #expect(turn.label(0) == "Off")
        #expect(turn.label(1) == "1 minute")
        #expect(turn.label(45) == "45 minutes")
        #expect(turn.label(60) == "1 hour")
        #expect(turn.label(61) == "1 hour 1 minute")
        #expect(turn.label(90) == "1 hour 30 minutes")
        #expect(turn.label(180) == "3 hours")
        #expect(StuckThreshold.repeated.label(4) == "More than 4 times")
        #expect(StuckThreshold.repeated.label(0) == "Off")
    }

    @Test @MainActor func notificationsForStuckChatsAreOnByDefault() {
        var preferences = NotificationPreferences()
        #expect(preferences.wants(.stuck))
        preferences.stuck = false
        #expect(!preferences.wants(.stuck))
        let store = MemoryStore()
        let settings = SettingsStore(store: store)
        settings.notifications.stuck = false
        #expect(store.values["notifications.stuck"] == "off")
        #expect(!SettingsStore(store: store).notifications.stuck)
    }
}

@MainActor
@Suite struct StuckSessionsTests {
    let api = FakeAPI()
    let approvals: ApprovalsStore
    let store: SessionsStore

    init() {
        approvals = ApprovalsStore(api: api)
        store = SessionsStore(api: api, approvals: approvals)
    }

    @Test func stuckEventsSetAndClearTheFlagWithoutMovingTheChat() async throws {
        api.set { $0.sessions = [StuckFixture.session("s1", stuck: false)] }
        try await store.load()
        let updated = store.session("s1")!.updatedAt

        store.apply(Fixture.event(EventType.sessionStuck, StuckFixture.flagJSON))
        #expect(store.session("s1")?.stuck == StuckFixture.flag)
        #expect(store.session("s1")?.updatedAt == updated)
        #expect(store.group(of: store.session("s1")!) == .needsYou)

        store.apply(Fixture.event(EventType.sessionUnstuck, #"{"reason": "repeating"}"#))
        #expect(store.session("s1")?.stuck == nil)
        #expect(store.group(of: store.session("s1")!) == .running)

        store.apply(Fixture.event(EventType.sessionStuck, StuckFixture.flagJSON, session: nil))
        store.apply(Fixture.event(EventType.sessionUnstuck, #"{"reason": "x"}"#, session: nil))
        store.apply(Fixture.event(EventType.sessionStuck, StuckFixture.flagJSON, session: "gone"))
        #expect(store.session("s1")?.stuck == nil)
        #expect(store.session("gone") == nil)
    }

    @Test func stuckChatsNeedYouUnlessArchived() async throws {
        api.set {
            $0.sessions = [
                StuckFixture.session("a"), StuckFixture.session("b", stuck: false),
                StuckFixture.session("c", archived: true),
            ]
        }
        try await store.load()
        #expect(store.stuck(in: "todo-ui").map(\.id) == ["a"])
        #expect(store.stuck(in: "other").isEmpty)
        #expect(store.needsYou(store.session("a")!))
        #expect(!store.needsYou(store.session("b")!))
    }

    @Test func aNudgeInterruptsWithTheReason() async throws {
        api.set {
            $0.sessions = [StuckFixture.session("s1")]
            $0.queueSends = true
        }
        try await store.load()

        let queued = try await store.nudge("s1")

        let text = StuckFixture.flag.nudge
        #expect(queued?.text == text)
        #expect(api.calls.last == "sendMessage s1 \(text) [] interrupt")
    }

    @Test func noNudgeOnceTheChatIsNoLongerStuck() async throws {
        api.set { $0.sessions = [StuckFixture.session("s1", stuck: false)] }
        try await store.load()
        #expect(try await store.nudge("s1") == nil)
        #expect(try await store.nudge("missing") == nil)
        #expect(!api.calls.contains { $0.hasPrefix("sendMessage") })
    }

    @Test func aFailedNudgeThrows() async throws {
        api.set { $0.sessions = [StuckFixture.session("s1")] }
        try await store.load()
        api.fail("sendMessage")
        await #expect(throws: APIError.self) { try await store.nudge("s1") }
    }
}

@MainActor
@Suite struct StuckSettingsStoreTests {
    let api = FakeAPI()

    @Test func loadsAndChangesAThreshold() async throws {
        let store = StuckSettingsStore(api: api)
        #expect(store.settings == nil)
        try await store.set(.repeated, to: 8)
        #expect(api.calls.isEmpty)

        try await store.load()
        #expect(store.settings?.waitingMinutes == 15)
        try await store.set(.repeated, to: 8)
        #expect(store.settings?.repeatedCalls == 8)
        #expect(api.calls == ["stuckSettings", "updateStuckSettings 8"])
        #expect(api.state.withLock { $0.stuckSettings.repeatedCalls } == 8)
    }

    @Test func aRefusedChangeRestoresTheOldValue() async throws {
        let store = StuckSettingsStore(api: api)
        try await store.load()
        api.fail("updateStuckSettings")
        await #expect(throws: APIError.self) { try await store.set(.silent, to: 0) }
        #expect(store.settings?.silentMinutes == 10)
    }
}
