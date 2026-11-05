import Foundation
import Testing

@testable import NestKit

/// B41: a pixie's Nest tools as the app shows them: its limits and autonomy notes, its
/// activity log, the chats it started, the messages it sent, the report when they finish
/// and the cards in its chat.
@MainActor @Suite struct PixieToolsTests {
    private static func userMessage(
        _ text: String, fromPixie: String? = nil, origin: String? = nil, id: Int
    ) -> Event {
        let from = fromPixie.map { "\"\($0)\"" } ?? "null"
        let originJSON = origin.map { "\"\($0)\"" } ?? "null"
        return Fixture.event(
            EventType.sessionUserMessage,
            #"{"text": "\#(text)", "attachments": [], "from_pixie": \#(from), "origin": \#(originJSON)}"#,
            id: id)
    }

    private static func card(_ kind: String, _ session: String, id: Int) -> Event {
        Fixture.event(
            EventType.pixieCard, #"{"kind": "\#(kind)", "session_id": "\#(session)"}"#, id: id,
            session: "chat-p1")
    }

    // MARK: Limits and autonomy

    @Test func aPixieCarriesItsLimits() throws {
        let pixie = Fixture.decode(Pixie.self, "pixie")
        #expect(pixie.maxRunning == 2)
        #expect(pixie.maxPerDay == 5)

        let changed = pixie.applying(UpdatePixieRequest(maxRunning: 4, maxPerDay: 12))
        #expect(changed.maxRunning == 4)
        #expect(changed.maxPerDay == 12)
        let kept = pixie.applying(UpdatePixieRequest(name: "X"))
        #expect(kept.maxRunning == 2)
        #expect(kept.maxPerDay == 5)

        #expect(
            Fixture.json(UpdatePixieRequest(maxRunning: 3, maxPerDay: 9))
                == #"{"max_per_day":9,"max_running":3}"#)
        #expect(Fixture.json(UpdatePixieRequest(name: "A")) == #"{"name":"A"}"#)
    }

    @Test func limitsStayInTheirRanges() {
        #expect(PixieLimits.running == 1...20)
        #expect(PixieLimits.perDay == 1...100)
        #expect(PixieLimits.clamp(0, to: PixieLimits.running) == 1)
        #expect(PixieLimits.clamp(21, to: PixieLimits.running) == 20)
        #expect(PixieLimits.clamp(7, to: PixieLimits.perDay) == 7)
        #expect(PixieLimits.runningTitle == "Running chats at once")
        #expect(PixieLimits.perDayTitle == "New chats per day")
    }

    // MARK: Started by and from

    @Test func aStartedChatNamesItsPixie() throws {
        var session = Fixture.session("s9")
        #expect(session.startedByPixie == nil)
        let pixie = Fixture.decode(Pixie.self, "pixie")
        #expect(PixieLabels.startedBy(session, pixies: [pixie]) == nil)

        session = Fixture.decode(
            Session.self,
            json: #"{"started_by_pixie": "p1", "# + Fixture.json(session).dropFirst())
        #expect(session.startedByPixie == "p1")
        let label = try #require(PixieLabels.startedBy(session, pixies: [pixie]))
        #expect(label.text == "Started by Tester")
        #expect(label.pixie?.id == "p1")

        session.startedByPixie = "gone"
        let unknown = try #require(PixieLabels.startedBy(session, pixies: [pixie]))
        #expect(unknown.text == "Started by a pixie")
        #expect(unknown.pixie == nil)
    }

    @Test func aMessageNamesThePixieThatSentIt() {
        let pixie = Fixture.decode(Pixie.self, "pixie")
        let label = PixieLabels.from("p1", pixies: [pixie])
        #expect(label.text == "from Tester")
        #expect(label.pixie == pixie)
        #expect(PixieLabels.from("gone", pixies: [pixie]).text == "from a pixie")
    }

    // MARK: Events and the transcript

    @Test func userMessagesCarryTheirSenderAndOrigin() throws {
        guard case .userMessage(let sent) = Self.userMessage("hi", fromPixie: "p1", id: 1).body
        else { throw Unexpected("not a user message") }
        #expect(sent.fromPixie == "p1")
        #expect(sent.origin == nil)

        guard
            case .userMessage(let report) = Self.userMessage(
                "done", origin: "report_back", id: 2
            ).body
        else { throw Unexpected("not a user message") }
        #expect(report.origin == .reportBack)

        // Older daemons send neither field.
        let plain = Fixture.event(
            EventType.sessionUserMessage, #"{"text": "x", "attachments": []}"#)
        guard case .userMessage(let old) = plain.body else { throw Unexpected("plain") }
        #expect(old.fromPixie == nil)
        #expect(old.origin == nil)

        guard
            case .userMessage(let odd) = Self.userMessage("x", origin: "habit", id: 3).body
        else { throw Unexpected("odd") }
        #expect(odd.origin == .unknown)
    }

    @Test func cardsDecode() throws {
        guard case .pixieCard(let session) = Self.card("session", "s2", id: 1).body else {
            throw Unexpected("not a card")
        }
        #expect(session == PixieCard(kind: .session, sessionID: "s2"))
        guard case .pixieCard(let pr) = Self.card("pr", "s3", id: 2).body else {
            throw Unexpected("not a card")
        }
        #expect(pr.kind == .pr)
        guard case .pixieCard(let odd) = Self.card("poll", "s3", id: 3).body else {
            throw Unexpected("not a card")
        }
        #expect(odd.kind == .unknown)
    }

    // MARK: Cards

    @Test func aSessionCardShowsTheChatsLiveState() async throws {
        let api = FakeAPI()
        let approvals = ApprovalsStore(api: api)
        let store = SessionsStore(api: api, approvals: approvals)
        let review = Fixture.approval("ap-review")
        api.set {
            $0.sessions = [
                Fixture.session("run", state: .running),
                Fixture.session("wait", state: .waiting),
                Fixture.session(review.sessionID, state: .idle),
                Fixture.session("bad", state: .failed),
                Fixture.session("stop", state: .interrupted),
                Fixture.session("idle", state: .idle),
                Fixture.session("shut", state: .closed),
                Fixture.session("new", state: .starting),
            ]
        }
        try await store.load()
        approvals.apply(.approvalCreated(review))

        let states = ["run", "wait", review.sessionID, "bad", "stop", "idle", "shut", "new"].map {
            store.cardState(of: store.session($0)!)
        }
        #expect(
            states == [
                "Running", "Needs you", "Ready for review", "Failed", "Interrupted", "Idle",
                "Closed", "Running",
            ])
    }

    @Test func aPRCardSaysTheReviewState() {
        #expect(PRBadge.reviewLabel("APPROVED") == "Approved")
        #expect(PRBadge.reviewLabel("CHANGES_REQUESTED") == "Changes requested")
        #expect(PRBadge.reviewLabel("REVIEW_REQUIRED") == "Review required")
        #expect(PRBadge.reviewLabel(nil) == "No review")
        #expect(PRBadge.reviewLabel("") == "No review")
        #expect(PRBadge.reviewLabel("SOMETHING_NEW") == "No review")
    }

    // MARK: Activity

    @Test func theActivityLogLoadsNewestFirst() async throws {
        let api = FakeAPI()
        let entries = [
            Fixture.decode(
                PixieActivityEntry.self,
                json:
                    #"{"id": 2, "ts": "2026-10-14T21:05:00Z", "tool": "start_session", "session_id": "s2", "summary": "Fix the nav"}"#
            ),
            Fixture.decode(
                PixieActivityEntry.self,
                json:
                    #"{"id": 1, "ts": "2026-10-14T21:00:00Z", "tool": "card", "session_id": null, "summary": "PR card"}"#
            ),
        ]
        api.set { $0.pixieActivity = entries }
        let store = PixiesStore(api: api)

        let loaded = try await store.activity("p1")
        #expect(loaded == entries)
        #expect(api.calls == ["pixieActivity p1"])
        #expect(loaded[0].sessionID == "s2")
        #expect(loaded[0].id == 2)
        #expect(loaded[1].sessionID == nil)
    }

    @Test func activityRowsReadPlainly() {
        #expect(PixieActivityText.tool("start_session") == "Start session")
        #expect(PixieActivityText.tool("answer_permission") == "Answer permission")
        #expect(PixieActivityText.tool("card") == "Card")
        #expect(PixieActivityText.tool("") == "")

        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        let now = Fixture.date("2026-10-14T22:00:00Z")
        #expect(
            PixieActivityText.time(
                Fixture.date("2026-10-14T09:05:00Z"), now: now, calendar: calendar)
                == "09:05")
        #expect(
            PixieActivityText.time(
                Fixture.date("2026-10-12T17:30:00Z"), now: now, calendar: calendar)
                == "12 Oct 17:30")

        let session = Fixture.session("s2", title: "Fix the nav")
        #expect(PixieActivityText.chat("s2", find: { $0 == "s2" ? session : nil }) == "Fix the nav")
        #expect(PixieActivityText.chat("gone", find: { _ in nil }) == "A removed chat")
        #expect(PixieActivityText.chat(nil, find: { _ in session }) == nil)
        #expect(
            PixieActivityText.empty == "Nothing yet. What this pixie does in your chats shows here."
        )
    }
}
