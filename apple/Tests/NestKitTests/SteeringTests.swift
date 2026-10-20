import Foundation
import Testing

@testable import NestKit

/// B59 wave 2: messages sent while Claude works reach the running turn; until Claude reads
/// them they wait above the composer with Send now, Remove and Edit.
@MainActor
@Suite struct PendingMessagesTests {
    let api = FakeAPI()
    let activity: ActivityStore

    init() {
        activity = ActivityStore(api: api)
        api.set { $0.sessions = [Fixture.session("s1", state: .running)] }
    }

    func pending(_ id: String, sent: Bool = true) -> QueuedMessage {
        QueuedMessage(id: id, text: "Text \(id)", createdAt: .distantPast, sent: sent)
    }

    @Test func readsWhetherTheMessageIsInTheRunningTurn() {
        let sent = Fixture.decode(
            QueuedMessage.self,
            json: #"""
                {"id": "q1", "text": "also check the tests", "attachments": [],
                 "created_at": "2026-10-15T14:02:11.120000Z", "sent": true}
                """#)
        #expect(sent.sent)
        let older = Fixture.decode(
            QueuedMessage.self,
            json:
                #"{"id": "q2", "text": "x", "attachments": [], "created_at": "2026-10-15T14:02:11Z"}"#
        )
        #expect(!older.sent)
    }

    /// What the line under a pending message says, by where it is.
    @Test func eachPendingMessageSaysWhenTheAgentGetsIt() {
        #expect(
            pending("a").note(working: true, agent: "Claude")
                == "Claude reads this at its next step")
        // A Codex chat names its own engine (B91).
        #expect(
            pending("a").note(working: true, agent: "Codex") == "Codex reads this at its next step")
        #expect(
            pending("a", sent: false).note(working: true, agent: "Codex")
                == "Sends when this turn ends")
        #expect(pending("a", sent: false).note(working: false, agent: "Claude") == "Waiting")
        // Taken back by a Stop, then the chat runs again: it still waits for the turn.
        #expect(pending("a").note(working: false, agent: "Claude") == "Waiting")
    }

    @Test func removeTakesTheMessageOut() async throws {
        activity.enqueue(pending("q1"), session: "s1")
        activity.enqueue(pending("q2"), session: "s1")
        #expect(try await activity.remove("q1", session: "s1") == true)
        #expect(activity.queued(session: "s1").map(\.id) == ["q2"])
        #expect(api.calls.last == "cancelQueued s1 q1")
    }

    /// Too late: Claude already read it. The row stays, saying so, until the next
    /// `session.queued`; the message shows in the transcript.
    @Test func aMessageClaudeAlreadyReadStaysUntilTheNextList() async throws {
        activity.enqueue(pending("q1"), session: "s1")
        api.fail("cancelQueued", with: APIError.messageTaken("Claude already read this message"))
        #expect(try await activity.remove("q1", session: "s1") == false)
        #expect(activity.queued(session: "s1").map(\.id) == ["q1"])
        #expect(activity.isTaken("q1", session: "s1"))
        let message = activity.queued(session: "s1")[0]
        #expect(
            activity.note(for: message, session: "s1", working: true, agent: "Claude")
                == "Claude already read this message")
        #expect(
            activity.note(for: message, session: "s1", working: true, agent: "Codex")
                == "Codex already read this message")

        activity.apply(Fixture.event(EventType.sessionQueued, #"{"queued": []}"#))
        #expect(activity.queued(session: "s1").isEmpty)
        #expect(!activity.isTaken("q1", session: "s1"))
    }

    @Test func aMessageAlreadyGoneLeavesTheList() async throws {
        activity.enqueue(pending("q1"), session: "s1")
        api.fail("cancelQueued", with: APIError.notFound("No queued message"))
        #expect(try await activity.remove("q1", session: "s1") == true)
        #expect(activity.queued(session: "s1").isEmpty)
    }

    @Test func otherRemoveFailuresKeepTheRowAndThrow() async {
        activity.enqueue(pending("q1"), session: "s1")
        api.fail("cancelQueued")
        await #expect(throws: APIError.self) {
            try await activity.remove("q1", session: "s1")
        }
        #expect(activity.queued(session: "s1").count == 1)
        #expect(!activity.isTaken("q1", session: "s1"))
    }

    /// Send now stays off after a tap until the daemon's next list.
    @Test func sendNowWaitsForTheNextList() async throws {
        activity.enqueue(pending("q1"), session: "s1")
        #expect(!activity.isSendingNow("q1", session: "s1"))
        try await activity.sendNow("q1", session: "s1")
        #expect(api.calls.last == "sendQueuedNow s1 q1")
        #expect(activity.isSendingNow("q1", session: "s1"))
        // A second tap meanwhile sends nothing.
        try await activity.sendNow("q1", session: "s1")
        #expect(api.calls.count { $0.hasPrefix("sendQueuedNow") } == 1)

        activity.apply(
            Fixture.event(
                EventType.sessionQueued,
                #"{"queued": [{"id": "q1", "text": "x", "attachments": [], "created_at": "2026-10-15T14:02:11Z", "sent": false}]}"#
            ))
        #expect(!activity.isSendingNow("q1", session: "s1"))
    }

    @Test func sendNowOfAMessageAlreadyReadDropsIt() async throws {
        activity.enqueue(pending("q1"), session: "s1")
        api.fail("sendQueuedNow", with: APIError.notFound("no queued message"))
        try await activity.sendNow("q1", session: "s1")
        #expect(activity.queued(session: "s1").isEmpty)
        #expect(!activity.isSendingNow("q1", session: "s1"))
    }

    @Test func otherSendNowFailuresLetItBeTappedAgain() async {
        activity.enqueue(pending("q1"), session: "s1")
        api.fail("sendQueuedNow", with: APIError.conflict("closed"))
        await #expect(throws: APIError.self) {
            try await activity.sendNow("q1", session: "s1")
        }
        #expect(!activity.isSendingNow("q1", session: "s1"))
        #expect(activity.queued(session: "s1").count == 1)
    }

    @Test func aDeletedChatForgetsItsPendingState() async throws {
        activity.enqueue(pending("q1"), session: "s1")
        try await activity.sendNow("q1", session: "s1")
        activity.apply(Fixture.event(EventType.sessionDeleted, #"{"session_id": "s1"}"#))
        #expect(!activity.isSendingNow("q1", session: "s1"))
        #expect(activity.queued(session: "s1").isEmpty)
    }

    /// The message Claude read appears once, where it read it: a user bubble between the
    /// agent's messages of the same turn, without a second turn opening.
    @Test func aSteeredMessageShowsWhereClaudeReadIt() async throws {
        let transcript = TranscriptStore(sessionID: "s1", api: api)
        try await transcript.load()
        transcript.receive(
            Fixture.event(
                EventType.sessionState, #"{"state": "running", "turn_start": true}"#, id: 1))
        transcript.receive(
            Fixture.event(
                EventType.sessionUserMessage, #"{"text": "Go", "attachments": []}"#, id: 2))
        transcript.receive(
            Fixture.event(
                EventType.sessionMessage, #"{"blocks": [{"type": "text", "text": "Working"}]}"#,
                id: 3))
        transcript.receive(
            Fixture.event(
                EventType.sessionUserMessage, #"{"text": "also the tests", "attachments": []}"#,
                id: 4))
        transcript.receive(
            Fixture.event(
                EventType.sessionMessage, #"{"blocks": [{"type": "text", "text": "Done"}]}"#,
                id: 5))
        #expect(
            transcript.items.map(\.content) == [
                .user(text: "Go", attachments: []), .assistant("Working", streaming: false),
                .user(text: "also the tests", attachments: []),
                .assistant("Done", streaming: false),
            ])
        #expect(transcript.turnStartedAt != nil)
    }
}

@MainActor
@Suite struct RewoundTranscriptTests {
    let api = FakeAPI()

    func events() -> [Event] {
        [
            Fixture.event(
                EventType.sessionUserMessage, #"{"text": "First", "attachments": []}"#, id: 1),
            Fixture.event(
                EventType.sessionMessage,
                #"{"blocks": [{"type": "text", "text": "One"}, {"type": "tool_use", "id": "toolu_2", "name": "Bash", "input": {}}]}"#,
                id: 2),
            Fixture.event(
                EventType.sessionResult,
                #"{"is_error": false, "subtype": "success", "duration_ms": 1000, "num_turns": 1, "errors": []}"#,
                id: 3),
            Fixture.event(
                EventType.sessionUserMessage, #"{"text": "Second", "attachments": []}"#, id: 4),
            Fixture.event(
                EventType.sessionMessage,
                #"{"blocks": [{"type": "text", "text": "Two"}, {"type": "tool_use", "id": "toolu_5", "name": "Bash", "input": {}}]}"#,
                id: 5),
            Fixture.event(
                EventType.sessionAgentTask,
                #"{"task_id": "t5", "phase": "finished", "tool_use_id": "toolu_5", "status": "completed"}"#,
                id: 6),
            Fixture.event(
                EventType.sessionResult,
                #"{"is_error": false, "subtype": "success", "duration_ms": 2000, "num_turns": 1, "errors": []}"#,
                id: 7),
        ]
    }

    @Test func decodesTheRewoundRange() {
        let event = Fixture.event(
            EventType.sessionRewound,
            #"{"message": 812, "through": 925, "text": "Make the button blue", "attachments": [{"id": "a1", "filename": "shot.png", "media_type": "image/png", "size": 2048}]}"#,
            id: 930)
        guard case .rewound(let rewind) = event.body else {
            Issue.record("not a rewind: \(event.body)")
            return
        }
        #expect(rewind.message == 812)
        #expect(rewind.through == 925)
        #expect(rewind.text == "Make the button blue")
        #expect(rewind.attachments.map(\.filename) == ["shot.png"])
        #expect(rewind.contains(812) && rewind.contains(925))
        #expect(!rewind.contains(811) && !rewind.contains(926))
    }

    /// The message and everything after it through `through` leave; later events stay.
    @Test func theRewoundMessageAndWhatFollowedLeave() async throws {
        api.set { $0.events["s1"] = events() }
        let transcript = TranscriptStore(sessionID: "s1", api: api)
        try await transcript.load()
        #expect(transcript.items.count { if case .user = $0.content { true } else { false } } == 2)
        #expect(transcript.lastUserMessage == 4)

        transcript.receive(
            Fixture.event(
                EventType.sessionRewound,
                #"{"message": 4, "through": 7, "text": "Second", "attachments": []}"#, id: 8))
        transcript.receive(
            Fixture.event(
                EventType.sessionNotice,
                #"{"kind": "files_restored", "text": "Restored 2 files to before your message"}"#,
                id: 9))
        let contents = transcript.visibleItems.map(\.content)
        #expect(contents.first == .user(text: "First", attachments: []))
        #expect(contents.contains(.assistant("One", streaming: false)))
        #expect(!contents.contains(.user(text: "Second", attachments: [])))
        #expect(!contents.contains(.assistant("Two", streaming: false)))
        #expect(contents.last == .notice("Restored 2 files to before your message"))
        #expect(transcript.turnStartedAt == nil)
        #expect(transcript.lastEventID == 9)
        #expect(transcript.lastUserMessage == 1)
        #expect(TranscriptStore(sessionID: "s2", api: api).lastUserMessage == nil)
    }

    /// A range the loaded page does not hold changes nothing it shows.
    @Test func aRewindOfOlderEventsKeepsTheLoadedOnes() async throws {
        api.set { $0.events["s1"] = Array(events().suffix(4)) }
        let transcript = TranscriptStore(sessionID: "s1", api: api)
        try await transcript.load()
        let before = transcript.items
        transcript.receive(
            Fixture.event(
                EventType.sessionRewound,
                #"{"message": 1, "through": 2, "text": "", "attachments": []}"#,
                id: 9))
        #expect(transcript.items == before)
        #expect(transcript.lastEventID == 9)
    }
}

@MainActor
@Suite struct ForkTests {
    let api = FakeAPI()
    let sessions: SessionsStore

    init() {
        sessions = SessionsStore(api: api, approvals: ApprovalsStore(api: api))
        api.set { $0.sessions = [Fixture.session("s1", title: "Fix the bug")] }
    }

    @Test func decodesTheNewChatAndItsMessage() {
        let fork = Fixture.decode(
            ForkedChat.self,
            json: """
                {"session": \(Fixture.json(Fixture.session("s2", title: "Fix the bug (fork)"))),
                 "text": "Make the button blue",
                 "attachments": [{"id": "c9", "filename": "shot.png", "media_type": "image/png", "size": 2048}]}
                """)
        #expect(fork.session.id == "s2")
        #expect(fork.message.text == "Make the button blue")
        #expect(fork.message.attachments.map(\.id) == ["c9"])
    }

    @Test func forkingAddsTheNewChat() async throws {
        try await sessions.load()
        let fork = try await sessions.fork("s1", message: 12)
        #expect(api.calls.last == "fork s1 12")
        #expect(fork.session.title == "Fix the bug (fork)")
        #expect(sessions.session(fork.session.id)?.title == "Fix the bug (fork)")
        #expect(fork.message.text == "message 12")
    }

    @Test func onlyAChatWithNoTurnRunningForks() {
        #expect(SessionsStore.canFork(Fixture.session(state: .idle)))
        #expect(SessionsStore.canFork(Fixture.session(state: .interrupted)))
        #expect(!SessionsStore.canFork(Fixture.session(state: .running)))
        #expect(!SessionsStore.canFork(Fixture.session(state: .idle, archived: true)))
        var pixie = Fixture.session(state: .idle)
        pixie.pixieID = "p1"
        #expect(!SessionsStore.canFork(pixie))
        #expect(!SessionsStore.canFork(nil))
    }
}

@Suite struct RestoredMessageTests {
    @Test func fillsAnEmptyComposerAndKeepsBothOtherwise() {
        let restored = RestoredMessage(text: "Make it blue", attachments: [])
        #expect(restored.needsAsking(draft: "  \n") == false)
        #expect(restored.needsAsking(draft: "half typed"))
        #expect(restored.combined(with: "half typed") == "Make it blue\n\nhalf typed")
        #expect(restored.combined(with: "") == "Make it blue")
    }
}

@Suite struct EscapeEscapeTests {
    /// Esc Esc in an idle chat opens Rewind, as in Claude Code; Esc still stops a turn.
    @Test func aSecondEscapeSoonAfterRewinds() {
        var escape = EscapeRepeat()
        let start = Date(timeIntervalSince1970: 100)
        let presses = [0, 0.3, 0.5, 2].map { escape.press(at: start.addingTimeInterval($0)) }
        // The pair is used up: a third press starts a new one, and a slow one does too.
        #expect(presses == [false, true, false, false])

        #expect(
            ComposerKeyAction.of(
                .escape, suggesting: false, isEmpty: true, working: false, repeated: true)
                == .rewind)
        #expect(
            ComposerKeyAction.of(
                .escape, suggesting: false, isEmpty: true, working: true, repeated: true)
                == .interrupt)
        #expect(
            ComposerKeyAction.of(.escape, suggesting: false, isEmpty: true, working: false)
                == .ignore)
        #expect(
            ComposerKeyAction.of(
                .escape, suggesting: true, isEmpty: true, working: false, repeated: true)
                == .close)
    }
}
