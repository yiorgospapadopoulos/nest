import Foundation
import Testing

@testable import NestKit

@MainActor
@Suite struct ActivityStoreTests {
    let api = FakeAPI()
    let store: ActivityStore
    let sessionID = Fixture.sessionDetail.id

    init() {
        store = ActivityStore(api: api)
        let detail = Fixture.sessionDetail
        api.set { $0.details[detail.id] = detail }
    }

    @Test func loadsGoalsFromTheSessionDetail() async throws {
        try await store.load(session: sessionID)

        let goals = store.goals(session: sessionID)
        #expect(
            goals.tasks.map(\.subject) == ["Add zod schema", "Show inline errors", "Write tests"])
        #expect((goals.completed, goals.inProgress, goals.pending) == (1, 1, 1))
        #expect(goals.current?.subject == "Show inline errors")
        #expect(goals.progress == 1.0 / 3)
    }

    @Test func goalsOfAnUnknownSessionAreEmpty() {
        let goals = store.goals(session: "none")
        #expect(goals.tasks.isEmpty)
        #expect(goals.progress == 0)
        #expect(goals.current == nil)
        #expect(store.agents(session: "none").isEmpty)
    }

    @Test func aDetailWithoutTrackingLoadsEmpty() async throws {
        api.set { $0.sessions = [Fixture.session("plain")] }
        try await store.load(session: "plain")
        #expect(store.goals(session: "plain").tasks.isEmpty)
        #expect(store.agents(session: "plain").isEmpty)
    }

    @Test func listsTheMainAgentFirstWithItsRecentSteps() async throws {
        let main = Fixture.sessionDetail.agents![0]
        var sub = Fixture.sessionDetail.agents![1]
        sub.status = .running
        sub.steps = (1...7).map {
            AgentStep(id: "t\($0)", tool: "Read", arg: "f\($0)", result: nil)
        }
        store.apply(
            Fixture.event(
                EventType.sessionAgents,
                "{\"agents\": [\(Fixture.json(sub)), \(Fixture.json(main))]}",
                id: nil, session: sessionID))

        let agents = store.agents(session: sessionID)

        #expect(agents.map(\.id) == ["main", "toolu_09"])
        #expect(store.recentSteps(of: agents[1]).map(\.id) == ["t3", "t4", "t5", "t6", "t7"])
        #expect(store.recentSteps(of: agents[0]).count == 2)
        #expect(store.runningAgents(in: [sessionID, "other"]) == 2)
    }

    @Test func followsLiveTaskSnapshotsAndDeletion() async throws {
        try await store.load(session: sessionID)
        store.apply(
            Fixture.event(
                EventType.sessionTasks,
                #"{"tasks": [{"id": "1", "subject": "Only", "description": null, "active_form": null, "status": "completed"}, {"id": "2", "subject": "Dropped", "description": null, "active_form": null, "status": "deleted"}]}"#,
                session: sessionID))
        #expect(store.goals(session: sessionID).tasks.map(\.subject) == ["Only"])
        #expect(store.goals(session: sessionID).progress == 1)

        store.apply(Fixture.event(EventType.sessionTasks, #"{"tasks": []}"#, session: nil))
        store.apply(Fixture.event(EventType.sessionAgents, #"{"agents": []}"#, session: nil))
        store.apply(Fixture.event("daemon.started", "{}"))
        #expect(store.agents(session: sessionID).count == 2)

        store.apply(
            Fixture.event(
                EventType.sessionDeleted, "{\"session_id\": \"\(sessionID)\"}", session: nil))
        #expect(store.goals(session: sessionID).tasks.isEmpty)
        #expect(store.agents(session: sessionID).isEmpty)
    }
}

@MainActor
@Suite struct TranscriptStoreTests {
    let api = FakeAPI()
    let sessionID = Fixture.sessionDetail.id

    init() {
        let events = Fixture.events
        let id = sessionID
        api.set { $0.events[id] = events }
    }

    @Test func buildsTheTranscriptFromHistory() async throws {
        let transcript = TranscriptStore(sessionID: sessionID, api: api)

        try await transcript.load()

        #expect(transcript.isLoaded)
        #expect(transcript.lastEventID == 21)
        let contents = transcript.items.map(\.content)
        #expect(contents.count == 8)
        guard case .user(let text, let attachments) = contents[0] else {
            throw Unexpected(contents[0])
        }
        #expect(text.hasPrefix("Validate the contact form"))
        #expect(attachments.map(\.filename) == ["form.png"])
        #expect(contents[1] == .thinking("The route posts JSON.", durationMS: nil))
        #expect(contents[2] == .assistant("I'll read the route first.", streaming: false))
        #expect(
            contents[3]
                == .tool(
                    ToolCall(
                        id: "toolu_01", name: "Read",
                        input: .object(["file_path": .string("app/api/contact/route.ts")]),
                        result: "export async function POST() {}", isError: false)))
        #expect(contents[4] == .approval(id: "ap-perm", kind: .permission, status: .resolved))
        #expect(contents[5] == .assistant("Validation added.", streaming: false))
        #expect(contents[6] == .turnEnd(TurnEnd(durationMS: 41_250, stopped: false)))
        guard case .result(let result) = contents[7] else { throw Unexpected(contents[7]) }
        #expect(result.durationMS == 41_250)
        #expect(
            transcript.items.map(\.id) == [
                "e12", "e14-0", "e14-1", "toolu_01", "ap-perm", "e19-0", "e20-end", "e20",
            ])
        #expect(api.calls == ["sessionEvents \(sessionID) after=0"])
    }

    @Test func deltasStreamUntilTheFinalMessage() async throws {
        let transcript = TranscriptStore(sessionID: "s1", api: api)
        try await transcript.load()

        transcript.receive(Fixture.event(EventType.sessionDelta, #"{"text": "Hel"}"#, id: nil))
        transcript.receive(Fixture.event(EventType.sessionDelta, #"{"text": "lo"}"#, id: nil))
        #expect(transcript.items.map(\.content) == [.assistant("Hello", streaming: true)])

        transcript.receive(
            Fixture.event(
                EventType.sessionMessage,
                #"{"blocks": [{"type": "text", "text": "Hello there."}, {"type": "image"}], "parent_tool_use_id": null}"#,
                id: 30))
        #expect(transcript.items.map(\.content) == [.assistant("Hello there.", streaming: false)])

        transcript.receive(Fixture.event(EventType.sessionDelta, #"{"text": "Par"}"#, id: nil))
        transcript.receive(
            Fixture.event(
                EventType.sessionResult,
                #"{"is_error": true, "subtype": "error_during_execution", "duration_ms": 5, "num_turns": 1, "cost_usd": 0.01, "errors": ["x"]}"#,
                id: 31))
        #expect(transcript.items.count == 3)
        #expect(transcript.items[1].content == .turnEnd(TurnEnd(durationMS: 5, stopped: true)))
        guard case .result(let result) = transcript.items[2].content else {
            throw Unexpected(transcript.items)
        }
        #expect(result.isError)
    }

    @Test func subagentOutputAndUnpairedResultsStayOut() async throws {
        let transcript = TranscriptStore(sessionID: "s1", api: api)
        try await transcript.load()
        transcript.receive(
            Fixture.event(
                EventType.sessionMessage,
                #"{"blocks": [{"type": "text", "text": "sub"}], "parent_tool_use_id": "toolu_9"}"#,
                id: 1))
        transcript.receive(
            Fixture.event(
                EventType.sessionMessage,
                #"{"blocks": [{"type": "tool_result", "tool_use_id": "nope", "content": "x"}], "parent_tool_use_id": null}"#,
                id: 2))
        transcript.receive(
            Fixture.event(
                EventType.sessionMessage,
                #"{"blocks": [{"type": "text", "text": "a"}, {"type": "tool_result", "tool_use_id": "e3-0", "content": "x"}], "parent_tool_use_id": null}"#,
                id: 3))
        #expect(transcript.items.map(\.content) == [.assistant("a", streaming: false)])
    }

    @Test func noticesForInterruptionsFailuresAndGit() async throws {
        let transcript = TranscriptStore(sessionID: "s1", api: api)
        try await transcript.load()
        let events = [
            Fixture.event(EventType.sessionDelta, #"{"text": "Half"}"#, id: nil),
            Fixture.event(
                EventType.sessionState, #"{"state": "interrupted", "error": null}"#, id: 1),
            Fixture.event(
                EventType.sessionState,
                #"{"state": "failed", "error": "setup command failed: npm ci"}"#, id: 2),
            Fixture.event(EventType.sessionState, #"{"state": "failed", "error": null}"#, id: 3),
            Fixture.event(EventType.gitFailed, #"{"step": "push", "stderr": "denied"}"#, id: 4),
            Fixture.event(EventType.prOpened, #"{"url": "https://example.com/pr/2"}"#, id: 5),
            Fixture.event(EventType.sessionState, #"{"state": "running", "error": null}"#, id: 6),
        ]
        events.forEach(transcript.receive)

        #expect(
            transcript.items.map(\.content) == [
                .notice("Interrupted"), .notice("Failed: setup command failed: npm ci"),
                .notice("Failed"), .notice("git push failed: denied"),
                .notice("Opened pull request https://example.com/pr/2"),
            ])
    }

    @Test func claudeCodeNoticesShowTheirText() async throws {
        let transcript = TranscriptStore(sessionID: "s1", api: api)
        try await transcript.load()
        let notice = Fixture.event(
            EventType.sessionNotice, #"{"kind": "compacted", "text": "Conversation compacted"}"#,
            id: 1)
        #expect(notice.body == .sessionNotice(text: "Conversation compacted"))
        transcript.receive(notice)
        #expect(transcript.items.map(\.content) == [.notice("Conversation compacted")])
    }

    @Test func taskListCallsAreLeftOut() async throws {
        let transcript = TranscriptStore(sessionID: "s1", api: api)
        try await transcript.load()
        let uses = ["TaskCreate", "Bash", "TaskUpdate", "TaskList", "TaskGet", "Read"]
            .enumerated().map { index, name in
                #"{"type": "tool_use", "id": "t\#(index)", "name": "\#(name)", "input": {}}"#
            }
        let results = (0..<uses.count).map { index in
            #"{"type": "tool_result", "tool_use_id": "t\#(index)", "content": "ok"}"#
        }
        for (id, blocks) in [(1, uses), (2, results)] {
            transcript.receive(
                Fixture.event(
                    EventType.sessionMessage,
                    #"{"blocks": [\#(blocks.joined(separator: ", "))], "parent_tool_use_id": null}"#,
                    id: id))
        }

        #expect(transcript.items.map(\.id) == ["t1", "t5"])
        let entries = TranscriptGrouping.entries(transcript.visibleItems, live: false)
        guard case .tools(let group) = entries.first else { throw Unexpected(entries) }
        #expect(group.summary == "Ran 1 command, read 1 file")
    }

    @Test func approvalMarkersUpdateInPlace() async throws {
        let transcript = TranscriptStore(sessionID: "s1", api: api)
        try await transcript.load()
        let review = Fixture.approval("ap-review")
        var resolved = review
        resolved.status = .superseded
        transcript.receive(
            Fixture.event(
                EventType.approvalCreated, "{\"approval\": \(Fixture.json(review))}", id: 1))
        transcript.receive(
            Fixture.event(
                EventType.approvalResolved, "{\"approval\": \(Fixture.json(resolved))}", id: 2))
        #expect(
            transcript.items.map(\.content) == [
                .approval(id: "ap-review", kind: .review, status: .superseded)
            ])
    }

    @Test func aRejectedReviewIsMarkedRejected() async throws {
        // Its transcript line says the changes stay (B54); an approved review's does not.
        let transcript = TranscriptStore(sessionID: "s1", api: api)
        try await transcript.load()
        var rejected = Fixture.approval("ap-review")
        rejected.status = .resolved
        rejected.resolution = .object(["action": .string("rejected")])
        var approved = rejected
        approved.id = "ap-approved"
        approved.resolution = .object(["pr_url": .string("https://github.com/me/x/pull/1")])
        for (id, approval) in [rejected, approved].enumerated() {
            transcript.receive(
                Fixture.event(
                    EventType.approvalResolved, "{\"approval\": \(Fixture.json(approval))}",
                    id: id + 1))
        }
        #expect(
            transcript.items.map(\.content) == [
                .approval(id: "ap-review", kind: .review, status: .resolved, rejected: true),
                .approval(id: "ap-approved", kind: .review, status: .resolved),
            ])
        #expect(RejectConsequence.transcript == "Rejected. Changes kept, nothing committed")
    }

    @Test func liveEventsBeforeTheHistoryWaitAndDuplicatesAreSkipped() async throws {
        let transcript = TranscriptStore(sessionID: sessionID, api: api)
        let replayed = Fixture.events[10]
        let newer = Fixture.event(
            EventType.sessionMessage,
            #"{"blocks": [{"type": "text", "text": "Anything else?"}], "parent_tool_use_id": null}"#,
            id: 22, session: sessionID)

        transcript.receive(Fixture.event(EventType.sessionDelta, #"{"text": "stale"}"#, id: nil))
        transcript.receive(replayed)
        transcript.receive(newer)
        #expect(transcript.items.isEmpty)

        try await transcript.load()

        #expect(transcript.items.count == 9)
        #expect(transcript.items.last?.content == .assistant("Anything else?", streaming: false))
        transcript.receive(newer)
        #expect(transcript.items.count == 9)
        #expect(transcript.lastEventID == 22)
    }

    /// A catch-up that fails leaves a gap: live events wait instead of moving past it,
    /// and the next catch-up loads again even when the stream resumed (audit BUG-79).
    @Test func aFailedCatchUpHoldsLiveEventsAndIsRetried() async throws {
        let transcript = TranscriptStore(sessionID: sessionID, api: api)
        try await transcript.load()
        #expect(!transcript.needsLoad)
        api.fail("sessionEvents")

        await transcript.catchUp(missed: true)

        #expect(transcript.needsLoad)
        #expect(transcript.isLoaded)
        func text(_ value: String, id: Int) -> Event {
            Fixture.event(
                EventType.sessionMessage,
                #"{"blocks": [{"type": "text", "text": "\#(value)"}], "parent_tool_use_id": null}"#,
                id: id, session: sessionID)
        }
        transcript.receive(text("live", id: 31))
        #expect(transcript.lastEventID == 21)
        #expect(transcript.items.count == 8)

        api.set {
            $0.failures["sessionEvents"] = nil
            $0.events[sessionID, default: []] += [text("missed", id: 30), text("live", id: 31)]
        }
        await transcript.catchUp(missed: false)

        #expect(!transcript.needsLoad)
        #expect(transcript.lastEventID == 31)
        #expect(
            transcript.items.suffix(2).map(\.content) == [
                .assistant("missed", streaming: false), .assistant("live", streaming: false),
            ])
    }

    /// A failed catch-up says so in the chat, with Retry, instead of freezing it
    /// silently (audit BUG-101).
    @Test func aFailedCatchUpSaysSoAndCanBeRetried() async throws {
        let transcript = TranscriptStore(sessionID: sessionID, api: api)
        try await transcript.load()
        #expect(transcript.catchUpFailure == nil)
        api.fail("sessionEvents", with: APIError.transport("The daemon is not running"))

        await transcript.catchUp(missed: true)
        #expect(transcript.catchUpFailure == "The daemon is not running")
        #expect(TranscriptStore.catchUpFailedText == "Could not catch up with this chat")

        await transcript.retryCatchUp()
        #expect(transcript.catchUpFailure == "The daemon is not running")
        #expect(transcript.needsLoad)

        api.set {
            $0.failures = [:]
            $0.events[sessionID, default: []].append(
                Fixture.event(
                    EventType.sessionMessage,
                    #"{"blocks": [{"type": "text", "text": "back"}], "parent_tool_use_id": null}"#,
                    id: 40, session: sessionID))
        }
        await transcript.retryCatchUp()
        #expect(transcript.catchUpFailure == nil)
        #expect(!transcript.needsLoad)
        #expect(transcript.lastEventID == 40)
        #expect(transcript.items.last?.content == .assistant("back", streaming: false))
    }

    /// A first load that fails is the view's to report; only a catch-up of a loaded chat
    /// shows the line, and it goes once a load succeeds.
    @Test func onlyACatchUpOfALoadedChatReportsAFailure() async throws {
        let transcript = TranscriptStore(sessionID: sessionID, api: api)
        api.fail("sessionEvents", with: CancellationError())
        await transcript.catchUp(missed: true)
        #expect(transcript.catchUpFailure == nil)
        #expect(!transcript.isLoaded)

        api.set { $0.failures = [:] }
        try await transcript.load()
        api.fail("sessionEvents", with: CancellationError())
        await transcript.catchUp(missed: true)
        #expect(transcript.catchUpFailure == CancellationError().localizedDescription)
        api.set { $0.failures = [:] }
        try await transcript.load()
        #expect(transcript.catchUpFailure == nil)
    }

    /// A transcript that never loaded keeps only the stored events it will apply, not
    /// every streamed delta (audit BUG-80).
    @Test func aTranscriptNotLoadedYetHoldsNoDeltas() {
        let transcript = TranscriptStore(sessionID: sessionID, api: api)
        for _ in 0..<50 {
            transcript.receive(Fixture.event(EventType.sessionDelta, #"{"text": "x"}"#, id: nil))
        }
        transcript.receive(Fixture.events[10])
        #expect(transcript.held.count == 1)
    }

    @Test func reloadingFetchesOnlyNewerEvents() async throws {
        let transcript = TranscriptStore(sessionID: sessionID, api: api)
        try await transcript.load()
        try await transcript.load()
        #expect(api.calls.last == "sessionEvents \(sessionID) after=21")
        #expect(transcript.items.count == 8)
    }

    @Test func transcriptsAreSharedAndFedByEvents() async throws {
        let transcripts = Transcripts(api: api)
        let first = transcripts.transcript(for: "s1")
        #expect(transcripts.transcript(for: "s1") === first)
        try await first.load()

        transcripts.receive(Fixture.event(EventType.sessionDelta, #"{"text": "Hi"}"#, id: nil))
        transcripts.receive(
            Fixture.event(EventType.sessionDelta, #"{"text": "?"}"#, id: nil, session: "other"))
        transcripts.receive(Fixture.event("daemon.started", "{}", session: nil))
        #expect(first.items.map(\.content) == [.assistant("Hi", streaming: true)])

        transcripts.receive(
            Fixture.event(EventType.sessionDeleted, #"{"session_id": "s1"}"#, session: nil))
        #expect(transcripts.transcript(for: "s1") !== first)

        let second = transcripts.transcript(for: "s2")
        transcripts.close("s2")
        #expect(transcripts.transcript(for: "s2") !== second)
    }

    /// Transcripts of panes no workspace shows any more are released (audit BUG-80).
    @Test func onlyTranscriptsOfOpenPanesAreKept() {
        let transcripts = Transcripts(api: api)
        let open = transcripts.transcript(for: "s1")
        let closed = transcripts.transcript(for: "s2")
        transcripts.keep(["s1", "s3"])
        #expect(transcripts.existing("s1") === open)
        #expect(transcripts.existing("s2") == nil)
        #expect(transcripts.transcript(for: "s2") !== closed)
        #expect(transcripts.existing("s3") == nil)
    }
}

/// Paging around a focused event, as a search hit opens a long transcript.
@MainActor
@Suite struct TranscriptPagingTests {
    let api = FakeAPI()

    /// User messages with ids 1 through `count` in session "p".
    init() {
        let events = (1...250).map(Self.message)
        api.set { $0.events["p"] = events }
    }

    static func message(_ id: Int) -> Event {
        Fixture.event(
            EventType.sessionUserMessage, #"{"text": "m\#(id)", "attachments": []}"#, id: id,
            session: "p")
    }

    func ids(_ transcript: TranscriptStore) -> [String] {
        transcript.items.map(\.id)
    }

    @Test func aFocusBeforeTheFirstLoadLoadsOnlyThePageAroundIt() async throws {
        let transcript = TranscriptStore(sessionID: "p", api: api)
        #expect(try await transcript.resolveFocus() == nil)
        transcript.requestFocus(event: 120)
        #expect(try await transcript.resolveFocus() == nil)

        try await transcript.load()

        #expect(
            api.calls == [
                "sessionEvents p after=0 before=121 limit=100",
                "sessionEvents p after=120 limit=100",
                // The latest user message, for the background bar.
                "sessionEvents p after=220 before=\(Int.max) limit=100",
            ])
        #expect(transcript.isLoaded)
        #expect(transcript.hasOlder)
        #expect(transcript.hasNewer)
        #expect(ids(transcript).first == "e21")
        #expect(ids(transcript).last == "e220")
        #expect(transcript.focus?.eventID == 120)
        #expect(try await transcript.resolveFocus() == "e120")
        #expect(transcript.focus == nil)
        #expect(try await transcript.resolveFocus() == nil)
        #expect(api.calls.count == 3)
    }

    @Test func earlierAndNewerPagesLoadOnRequest() async throws {
        let transcript = TranscriptStore(sessionID: "p", api: api)
        transcript.requestFocus(event: 120)
        try await transcript.load()

        try await transcript.loadOlder()
        #expect(api.calls.last == "sessionEvents p after=0 before=21 limit=100")
        #expect(!transcript.hasOlder)
        #expect(ids(transcript).first == "e1")
        #expect(transcript.items.count == 220)
        try await transcript.loadOlder()
        #expect(api.calls.count == 4)

        try await transcript.loadNewer()
        #expect(api.calls.last == "sessionEvents p after=220 limit=100")
        #expect(!transcript.hasNewer)
        #expect(ids(transcript).last == "e250")
        #expect(transcript.lastEventID == 250)
        try await transcript.loadNewer()
        #expect(api.calls.count == 5)
    }

    @Test func liveEventsWaitWhileNewerOnesAreNotLoaded() async throws {
        let transcript = TranscriptStore(sessionID: "p", api: api)
        transcript.receive(Self.message(251))
        transcript.requestFocus(event: 120)
        try await transcript.load()
        #expect(ids(transcript).last == "e220")

        transcript.receive(Self.message(252))
        transcript.receive(Fixture.event(EventType.sessionDelta, #"{"text": "Hi"}"#, id: nil))
        #expect(ids(transcript).last == "e220")

        // A reload reads everything newer, and live events apply again.
        api.set { $0.events["p"]! += [Self.message(251), Self.message(252)] }
        try await transcript.load()
        #expect(api.calls.last == "sessionEvents p after=220")
        #expect(!transcript.hasNewer)
        #expect(ids(transcript).last == "e252")
        transcript.receive(Self.message(253))
        #expect(ids(transcript).last == "e253")
    }

    @Test func aPageThatReachesTheEndKeepsEarlyAndStreamingEvents() async throws {
        let transcript = TranscriptStore(sessionID: "p", api: api)
        transcript.receive(Self.message(251))
        transcript.requestFocus(event: 230)
        try await transcript.load()
        #expect(transcript.hasOlder)
        #expect(!transcript.hasNewer)
        #expect(ids(transcript).last == "e251")

        transcript.receive(Fixture.event(EventType.sessionDelta, #"{"text": "Hi"}"#, id: nil))
        try await transcript.loadOlder()
        #expect(ids(transcript).first == "e31")
        #expect(ids(transcript).suffix(2) == ["e251", "streaming"])
        #expect(transcript.items.last?.eventID == nil)
    }

    @Test func liveEventsDuringTheLastNewerPageApplyAfterIt() async throws {
        let transcript = TranscriptStore(sessionID: "p", api: api)
        transcript.requestFocus(event: 120)
        try await transcript.load()
        let (gate, open) = AsyncStream<Void>.makeStream()
        api.set { $0.gates["sessionEvents"] = gate }

        let paging = Task { try await transcript.loadNewer() }
        try await waitFor { api.calls.count == 4 }
        // Published after the daemon read the page: only the live copies bring them.
        transcript.receive(Self.message(251))
        transcript.receive(Self.message(252))
        open.finish()
        try await paging.value

        #expect(!transcript.hasNewer)
        #expect(ids(transcript).suffix(3) == ["e250", "e251", "e252"])
        #expect(transcript.lastEventID == 252)
    }

    @Test func liveEventsDuringAPageLoadSurviveItsRebuild() async throws {
        let transcript = TranscriptStore(sessionID: "p", api: api)
        transcript.requestFocus(event: 120)
        try await transcript.load()
        _ = try await transcript.resolveFocus()
        let (gate, open) = AsyncStream<Void>.makeStream()
        api.set { $0.gates["sessionEvents"] = gate }

        // The page around 240 reaches the newest event, so live ones apply after it.
        transcript.requestFocus(event: 240)
        let jumping = Task { try await transcript.resolveFocus() }
        try await waitFor { api.calls.count == 4 }
        transcript.receive(Self.message(251))
        open.finish()
        #expect(try await jumping.value == "e240")

        #expect(!transcript.hasNewer)
        #expect(ids(transcript).last == "e251")
    }

    @Test func aReloadAppliesLiveEventsAfterTheFetchedOnes() async throws {
        let transcript = TranscriptStore(sessionID: "p", api: api)
        try await transcript.load()
        api.set { $0.events["p"]! += [Self.message(251)] }
        let (gate, open) = AsyncStream<Void>.makeStream()
        api.set { $0.gates["sessionEvents"] = gate }

        let reloading = Task { try await transcript.load() }
        try await waitFor { api.calls.count == 2 }
        // Arrives live while the reload's answer (event 251) is on its way.
        transcript.receive(Self.message(252))
        transcript.receive(Fixture.event(EventType.sessionDelta, #"{"text": "Hi"}"#, id: nil))
        open.finish()
        try await reloading.value

        #expect(ids(transcript).suffix(2) == ["e251", "e252"])
        transcript.receive(Self.message(253))
        #expect(ids(transcript).last == "e253")
    }

    @Test func catchingUpSkipsWhatNeedsNoLoad() async throws {
        let transcript = TranscriptStore(sessionID: "p", api: api)
        transcript.requestFocus(event: 120)
        try await transcript.load()
        let calls = api.calls.count

        // Newer events still wait for their pages, and a resumed stream missed nothing.
        await transcript.catchUp(missed: true)
        await transcript.catchUp(missed: false)
        #expect(api.calls.count == calls)
    }

    @Test func aFocusOutsideTheLoadedPageLoadsItsOwnPage() async throws {
        let transcript = TranscriptStore(sessionID: "p", api: api)
        transcript.requestFocus(event: 120)
        try await transcript.load()
        _ = try await transcript.resolveFocus()

        transcript.requestFocus(event: 5)
        #expect(try await transcript.resolveFocus() == "e5")
        #expect(
            api.calls.suffix(2) == [
                "sessionEvents p after=0 before=6 limit=100", "sessionEvents p after=5 limit=100",
            ])
        #expect(!transcript.hasOlder)
        #expect(ids(transcript).first == "e1")

        transcript.requestFocus(event: 240)
        #expect(try await transcript.resolveFocus() == "e240")
        #expect(api.calls.last == "sessionEvents p after=240 limit=100")

        transcript.requestFocus(event: 200)
        #expect(try await transcript.resolveFocus() == "e200")
        #expect(api.calls.count == 7)
    }
}

@MainActor
@Suite struct TranscriptFocusTests {
    let api = FakeAPI()
    let sessionID = Fixture.sessionDetail.id

    init() {
        let events = Fixture.events
        let id = sessionID
        api.set { $0.events[id] = events }
    }

    @Test func itemsKnowTheirEventsAndHiddenOnesAreLeftOut() async throws {
        let transcript = TranscriptStore(sessionID: sessionID, api: api)
        try await transcript.load()
        #expect(
            transcript.items.map(\.eventID) == [12, 14, 14, 14, 17, 19, 20, 20])
        #expect(
            transcript.visibleItems.map(\.id) == [
                "e12", "e14-0", "e14-1", "toolu_01", "ap-perm", "e19-0", "e20-end",
            ])
        #expect(!transcript.hasOlder)
        #expect(!transcript.hasNewer)

        transcript.receive(
            Fixture.event(
                EventType.sessionMessage,
                #"{"blocks": [{"type": "thinking", "text": "  "}], "parent_tool_use_id": null}"#,
                id: 30, session: sessionID))
        transcript.receive(
            Fixture.event(
                EventType.sessionResult,
                #"{"is_error": true, "subtype": "error_max_turns", "duration_ms": 5, "num_turns": 1, "cost_usd": null, "errors": []}"#,
                id: 31, session: sessionID))
        #expect(transcript.items.count == 11)
        #expect(transcript.visibleItems.last?.id == "e31")
    }

    @Test func aHitScrollsToTheShownItemAtOrBeforeItsEvent() async throws {
        let transcript = TranscriptStore(sessionID: sessionID, api: api)
        #expect(transcript.itemID(forEvent: 3) == nil)
        try await transcript.load()

        // A tool result shows with its call; a subagent message and a hidden result
        // land on what is shown before them; an event before the first item on it.
        let expected = [15: "toolu_01", 16: "toolu_01", 19: "e19-0", 21: "e20-end", 1: "e12"]
        for (event, item) in expected {
            transcript.requestFocus(event: event)
            #expect(transcript.focus?.eventID == event)
            #expect(try await transcript.resolveFocus() == item)
        }
        #expect(api.calls == ["sessionEvents \(sessionID) after=0"])
    }

    @Test func eachRequestIsNew() {
        let transcript = TranscriptStore(sessionID: sessionID, api: api)
        transcript.requestFocus(event: 4)
        let first = transcript.focus
        transcript.requestFocus(event: 4)
        #expect(transcript.focus != first)
        #expect(transcript.focus?.serial == 2)
    }
}
