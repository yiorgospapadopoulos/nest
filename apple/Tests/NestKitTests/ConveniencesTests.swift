import Foundation
import Testing

@testable import NestKit

@Suite struct ConvenienceModelTests {
    @Test func theContextMeterReadsThePercentAndTurnsHighAbove80() {
        let quiet = SessionContext(percent: 41.4, used: 82_400, limit: 200_000)
        #expect(quiet.label == "context 41%")
        #expect(!quiet.isHigh)
        #expect(quiet.detail == "82k of 200k tokens")
        #expect(!SessionContext(percent: 80, used: 1, limit: 2).isHigh)
        #expect(SessionContext(percent: 80.5, used: 1, limit: 2).isHigh)
        #expect(SessionContext(percent: 99.6, used: 1, limit: 2).label == "context 100%")
    }

    @Test func sessionsCarryTheirContextAndTheDetailItsQueue() throws {
        let session = Fixture.decode(
            Session.self,
            json: sessionJSON(
                extra: """
                    , "context": {"percent": 12.5, "used": 25000, "limit": 200000},
                    "queued": [{"id": "q1", "text": "Then the tests", "created_at": "2026-10-07T01:00:00Z",
                     "attachments": [{"id": "a1", "filename": "x.png", "media_type": "image/png", "size": 3}]}]
                    """))
        #expect(session.context == SessionContext(percent: 12.5, used: 25_000, limit: 200_000))
        let queued = try #require(session.queued?.first)
        #expect(queued.text == "Then the tests")
        #expect(queued.attachments.map(\.filename) == ["x.png"])
        #expect(queued.createdAt == Date(timeIntervalSince1970: 1_791_334_800))

        // Sessions encode too (the app keeps none, but the type is Codable): a round trip.
        let again = try NestJSON.decoder.decode(
            Session.self, from: NestJSON.encoder.encode(session))
        #expect(again == session)

        let plain = Fixture.decode(Session.self, json: sessionJSON(extra: ""))
        #expect(plain.context == nil)
        #expect(plain.queued == nil)
    }

    @Test func aSendAnswersTheSessionAndWhatWasQueued() {
        let started = Fixture.decode(SentMessage.self, json: sessionJSON(extra: ""))
        #expect(started.session.id == "s1")
        #expect(started.queuedMessage == nil)

        let queued = Fixture.decode(
            SentMessage.self,
            json: sessionJSON(
                extra: """
                    , "queued_message": {"id": "q2", "text": "More", "attachments": [],
                     "created_at": "2026-10-07T01:00:00Z"}
                    """))
        #expect(queued.queuedMessage?.id == "q2")
        #expect(queued.session.state == .running)
    }

    @Test func decodesCommandLists() {
        let list = Fixture.decode(CommandList.self, json: RouteCase.commandsJSON)
        #expect(list.source == .session)
        #expect(
            list.commands
                == [
                    SlashCommand(
                        name: "compact", description: "Compact", argumentHint: "<instructions>")
                ]
        )
        #expect(list.commands[0].id == "compact")
        #expect(list.agents.map(\.name) == ["Explore"])
        #expect(list.agents[0].description == nil)
        #expect(list.updatedAt != nil)

        let none = Fixture.decode(
            CommandList.self,
            json: #"{"source": "none", "commands": [], "agents": [], "updated_at": null}"#)
        #expect(none.source == .none)
        #expect(none.updatedAt == nil)
        #expect(CommandList(source: .repo, commands: []).agents.isEmpty)
    }

    @Test func planApprovalsReadTheirPlan() throws {
        var approval = Fixture.approval("ap-perm")
        approval.kind = .plan
        approval.payload = .object([
            "plan": .string("## Plan\n1. Do it"), "tool_use_id": .string("toolu_9"),
        ])
        let plan = try #require(approval.plan)
        #expect(plan.plan == "## Plan\n1. Do it")
        #expect(plan.toolUseID == "toolu_9")
        #expect(approval.permission == nil)
        #expect(Fixture.approval("ap-perm").plan == nil)
        #expect(
            Fixture.decode(ApprovalKind.self, json: #""plan""#) == .plan)
    }

    @Test func contextAndQueueEventsDecode() {
        let context = Fixture.event(
            EventType.sessionContext, #"{"context": {"percent": 50, "used": 10, "limit": 20}}"#)
        #expect(context.body == .context(SessionContext(percent: 50, used: 10, limit: 20)))
        #expect(
            Fixture.event(EventType.sessionContext, #"{"context": null}"#).body == .context(nil))
        let queued = Fixture.event(
            EventType.sessionQueued,
            #"{"queued": [{"id": "q1", "text": "Next", "attachments": [], "created_at": "2026-10-07T01:00:00Z"}]}"#
        )
        #expect(
            queued.body
                == .queued([
                    QueuedMessage(
                        id: "q1", text: "Next",
                        createdAt: Date(timeIntervalSince1970: 1_791_334_800))
                ]))
    }

    private func sessionJSON(extra: String) -> String {
        """
        {"id": "s1", "repo": "cv-page", "title": "T", "prompt": "P", "mode": "worktree",
         "permission_mode": "default", "provider": "claude", "state": "running",
         "created_at": "2026-10-07T01:00:00Z",
         "updated_at": "2026-10-07T01:00:00Z", "allowed_tools": [], "pinned": false\(extra)}
        """
    }
}

@Suite struct CompletionTriggerTests {
    @Test func aSlashCountsOnlyAtTheStartOfTheMessage() {
        #expect(
            CompletionTrigger.at("/rev", caret: 4)
                == CompletionTrigger(kind: .command, start: 0, end: 4, query: "rev"))
        #expect(
            CompletionTrigger.at("/", caret: 1)
                == CompletionTrigger(kind: .command, start: 0, end: 1, query: ""))
        // The caret inside the token: the query stops there and the token runs on.
        #expect(
            CompletionTrigger.at("/review now", caret: 3)
                == CompletionTrigger(kind: .command, start: 0, end: 7, query: "re"))
        #expect(CompletionTrigger.at("use /review", caret: 11) == nil)
        #expect(CompletionTrigger.at(" /review", caret: 8) == nil)
        #expect(CompletionTrigger.at("/review ", caret: 8) == nil)
        #expect(CompletionTrigger.at("", caret: 0) == nil)
        #expect(CompletionTrigger.at("plain", caret: 5) == nil)
    }

    @Test func anAtStartsAMentionAnywhere() {
        #expect(
            CompletionTrigger.at("see @src/ap", caret: 11)
                == CompletionTrigger(kind: .file, start: 4, end: 11, query: "src/ap"))
        #expect(
            CompletionTrigger.at("@", caret: 1)
                == CompletionTrigger(kind: .file, start: 0, end: 1, query: ""))
        #expect(
            CompletionTrigger.at("a\n@x and", caret: 4)
                == CompletionTrigger(kind: .file, start: 2, end: 4, query: "x"))
        #expect(CompletionTrigger.at("me@host", caret: 7) == nil)
    }

    @Test func theCaretIsClampedToTheText() {
        #expect(CompletionTrigger.at("/a", caret: 99)?.query == "a")
        #expect(CompletionTrigger.at("/a", caret: -3) == nil)
    }

    @Test func replacingPutsTheChoiceAndOneSpaceInPlaceOfTheToken() {
        let command = CompletionTrigger.at("/rev", caret: 4)!
        #expect(command.replacing(in: "/rev", with: "/review") == ("/review ", 8))

        let mention = CompletionTrigger.at("see @ap now", caret: 7)!
        #expect(mention.replacing(in: "see @ap now", with: "@app.ts") == ("see @app.ts now", 12))

        let last = CompletionTrigger.at("see @ap", caret: 7)!
        #expect(last.replacing(in: "see @ap", with: "@app.ts") == ("see @app.ts ", 12))
        #expect(last.anchor == "file:4")
    }
}

@Suite struct CompletionListTests {
    let commands = [
        SlashCommand(name: "compact", description: "Compact the chat", argumentHint: "<notes>"),
        SlashCommand(name: "context"),
        SlashCommand(name: "security-review"),
        SlashCommand(name: "review"),
    ]

    @Test func commandsStartingWithTheQueryComeFirst() {
        let trigger = CompletionTrigger.at("/rev", caret: 4)!
        let list = CompletionList.commands(commands, for: trigger, in: "/rev")
        #expect(list.items.map(\.label) == ["/review", "/security-review"])
        #expect(list.items[0].text == "/review ")
        #expect(list.items[0].caret == 8)
        #expect(list.title == "Commands")

        let all = CompletionList.commands(
            commands, for: CompletionTrigger.at("/", caret: 1)!, in: "/")
        #expect(all.items.count == 4)
        #expect(all.items[0].hint == "<notes>")
        #expect(all.items[0].detail == "Compact the chat")
        #expect(all.items[0].id == "compact")

        let upper = CompletionList.commands(
            commands, for: CompletionTrigger.at("/CO", caret: 3)!, in: "/CO")
        #expect(upper.items.map(\.id) == ["compact", "context"])
    }

    @Test func filesAreInsertedAsMentions() {
        let trigger = CompletionTrigger.at("fix @nav", caret: 8)!
        let list = CompletionList.files(["components/Nav.tsx"], for: trigger, in: "fix @nav")
        #expect(list.title == "Files")
        #expect(list.items.map(\.label) == ["components/Nav.tsx"])
        #expect(list.items[0].text == "fix @components/Nav.tsx ")
        #expect(list.items[0].hint == nil)
    }

    @Test func theSelectionMovesWrapsAndStartsOverForANewQuery() {
        let first = CompletionList.commands(
            commands, for: CompletionTrigger.at("/", caret: 1)!, in: "/")
        var selection = CompletionSelection()
        #expect(selection.isOpen(first))
        #expect(selection.active(in: first) == 0)
        selection.move(-1, in: first)
        #expect(selection.active(in: first) == 3)
        #expect(selection.chosen(in: first)?.id == "review")
        selection.move(1, in: first)
        #expect(selection.active(in: first) == 0)
        selection.move(5, in: first)
        #expect(selection.active(in: first) == 1)

        let narrower = CompletionList.commands(
            commands, for: CompletionTrigger.at("/c", caret: 2)!, in: "/c")
        #expect(selection.active(in: narrower) == 0)
    }

    @Test func anEmptyListIsClosedAndHasNothingToPick() {
        let empty = CompletionList.files([], for: CompletionTrigger.at("@", caret: 1)!, in: "@")
        var selection = CompletionSelection()
        #expect(!selection.isOpen(empty))
        #expect(!selection.isOpen(nil))
        selection.move(1, in: empty)
        #expect(selection.active(in: empty) == 0)
        #expect(selection.chosen(in: empty) == nil)
    }

    @Test func escClosesTheListUntilItsTokenIsGone() {
        let typing = CompletionList.commands(
            commands, for: CompletionTrigger.at("/c", caret: 2)!, in: "/c")
        var selection = CompletionSelection()
        selection.dismiss(typing)
        #expect(!selection.isOpen(typing))

        // Typing on in the same token keeps it closed.
        let more = CompletionList.commands(
            commands, for: CompletionTrigger.at("/co", caret: 3)!, in: "/co")
        selection.update(for: more.trigger)
        #expect(!selection.isOpen(more))

        // Once the token is gone, the next one opens again.
        selection.update(for: nil)
        #expect(selection.isOpen(more))
        selection.update(for: nil)
        #expect(selection.isOpen(more))
    }
}

@MainActor
@Suite struct CompletionStoreTests {
    let api = FakeAPI()
    let store: CompletionStore

    init() {
        store = CompletionStore(api: api)
    }

    @Test func commandsComeFromTheSessionOnceEach() async {
        api.set {
            $0.commands["session:s1"] = CommandList(
                source: .session, commands: [SlashCommand(name: "compact")])
        }
        #expect(store.suggestions(text: "/", caret: 1, session: "s1", repo: "cv")?.items == [])

        await store.loadCommands(session: "s1", repo: "cv")
        await store.loadCommands(session: "s1", repo: "cv")

        #expect(api.calls == ["sessionCommands s1"])
        let list = store.suggestions(text: "/co", caret: 3, session: "s1", repo: "cv")
        #expect(list?.items.map(\.label) == ["/compact"])
    }

    @Test func aChatsListAddsNestsOwnCommands() async {
        api.set {
            $0.commands["session:s1"] = CommandList(
                source: .session, commands: [SlashCommand(name: "compact")])
        }
        await store.loadCommands(session: "s1", repo: "cv")
        let list = store.suggestions(
            text: "/m", caret: 2, session: "s1", repo: "cv", localCommands: true)
        #expect(
            list?.items.map(\.label) == ["/mcp", "/model", "/compact", "/permissions", "/resume"])
        // Before the chat's own list arrives, Nest's commands are already there.
        let fresh = store.suggestions(
            text: "/re", caret: 3, session: nil, repo: "other", localCommands: true)
        #expect(fresh?.items.map(\.label) == ["/resume"])
    }

    /// An engine without slash commands (Codex, B91) gets no list for `/`; `@` still works.
    @Test func noListForAnEngineWithoutSlashCommands() async {
        await store.loadCommands(session: "s1", repo: "cv")
        #expect(
            store.suggestions(
                text: "/m", caret: 2, session: "s1", repo: "cv", localCommands: true,
                commands: false) == nil)
        #expect(
            store.suggestions(
                text: "@", caret: 1, session: "s1", repo: "cv", commands: false) != nil)
    }

    @Test func aNewChatTakesItsProjectsCommands() async {
        api.set {
            $0.commands["repo:cv"] = CommandList(
                source: .repo, commands: [SlashCommand(name: "init")])
        }
        await store.loadCommands(session: nil, repo: "cv")
        #expect(api.calls == ["repoCommands cv"])
        #expect(
            store.suggestions(text: "/", caret: 1, session: nil, repo: "cv")?.items.map(\.id)
                == ["init"])
        #expect(store.suggestions(text: "/", caret: 1, session: nil, repo: "other")?.items == [])
    }

    @Test func anEmptyListOrAFailureIsAskedForAgain() async {
        await store.loadCommands(session: "s1", repo: "cv")
        api.fail("sessionCommands")
        await store.loadCommands(session: "s1", repo: "cv")
        await store.loadCommands(session: "s1", repo: "cv")
        #expect(api.calls == ["sessionCommands s1", "sessionCommands s1", "sessionCommands s1"])
    }

    @Test func fileSuggestionsFollowTheLatestSearch() async {
        api.set {
            $0.files["ap"] = ["app/page.tsx"]
            $0.files["app"] = ["app/page.tsx", "app/layout.tsx"]
        }
        let (gate, open) = AsyncStream<Void>.makeStream()
        api.set { $0.gates["sessionFiles ap"] = gate }

        let slow = Task { await store.searchFiles(session: "s1", query: "ap") }
        while store.latestSearch == nil {
            await Task.yield()
        }
        await store.searchFiles(session: "s1", query: "app")
        open.finish()
        await slow.value

        let list = store.suggestions(text: "@app", caret: 4, session: "s1", repo: "cv")
        #expect(list?.items.map(\.label) == ["app/page.tsx", "app/layout.tsx"])
        #expect(list?.items[1].text == "@app/layout.tsx ")
    }

    @Test func filesNeedASessionAndFailuresGiveNone() async {
        api.set { $0.files[""] = ["README.md"] }
        await store.searchFiles(session: "s1", query: "")
        #expect(store.suggestions(text: "@", caret: 1, session: nil, repo: "cv") == nil)
        #expect(store.suggestions(text: "@", caret: 1, session: "s2", repo: "cv")?.items == [])
        #expect(
            store.suggestions(text: "@", caret: 1, session: "s1", repo: "cv")?.items.map(\.id)
                == ["README.md"])

        api.fail("sessionFiles", with: APIError.conflict("The folder is missing"))
        await store.searchFiles(session: "s1", query: "x")
        #expect(store.suggestions(text: "@x", caret: 2, session: "s1", repo: "cv")?.items == [])
        #expect(store.suggestions(text: "plain", caret: 5, session: "s1", repo: "cv") == nil)
    }
}

@Suite struct ComposerKeyTests {
    @Test func anOpenListTakesTheNavigationKeys() {
        func action(_ key: ComposerKey) -> ComposerKeyAction {
            ComposerKeyAction.of(key, suggesting: true, isEmpty: false, working: true)
        }
        #expect(action(.up) == .move(-1))
        #expect(action(.down) == .move(1))
        #expect(action(.tab) == .insert)
        #expect(action(.enter(shift: false)) == .insert)
        #expect(action(.enter(shift: true)) == .ignore)
        #expect(action(.escape) == .close)
    }

    @Test func otherwiseReturnSendsEscInterruptsAndUpRecalls() {
        func action(_ key: ComposerKey, isEmpty: Bool = true, working: Bool = false)
            -> ComposerKeyAction
        {
            ComposerKeyAction.of(key, suggesting: false, isEmpty: isEmpty, working: working)
        }
        #expect(action(.enter(shift: false)) == .send)
        #expect(action(.enter(shift: true)) == .ignore)
        #expect(action(.escape, working: true) == .interrupt)
        #expect(action(.escape) == .ignore)
        #expect(action(.up) == .recall)
        #expect(action(.up, isEmpty: false) == .ignore)
        #expect(action(.down) == .ignore)
        #expect(action(.tab) == .ignore)
    }

    @Test func theSendButtonSendsOrInterruptsWhileWorking() {
        #expect(SendButtonMode.of(working: false, hasText: false) == .send)
        #expect(SendButtonMode.of(working: false, hasText: true) == .send)
        #expect(SendButtonMode.of(working: true, hasText: true) == .send)
        #expect(SendButtonMode.of(working: true, hasText: false) == .interrupt)
    }

    @Test func afterASendOnlyTextTypedMeanwhileStays() {
        #expect(SentDraft.remainder(of: "First part", after: "First part") == "")
        #expect(
            SentDraft.remainder(of: "First part and a follow-up", after: "First part")
                == "and a follow-up")
        #expect(SentDraft.remainder(of: "First part\n\nNext ", after: "First part") == "Next ")
        // An edit inside the sent text keeps all of it, so nothing typed is lost.
        #expect(SentDraft.remainder(of: "Fixed part", after: "First part") == "Fixed part")
        #expect(SentDraft.remainder(of: "", after: "First part") == "")
    }

    @MainActor @Test func upArrowRecallsTheLastSentOrTheTranscriptsLastMessage() {
        let sent = SentMessages()
        let transcript = [
            TranscriptItem(id: "1", content: .user(text: "First", attachments: [])),
            TranscriptItem(id: "2", content: .user(text: "", attachments: [])),
            TranscriptItem(id: "3", content: .assistant("Reply", streaming: false)),
        ]
        #expect(sent.last(chat: "c1", transcript: transcript) == "First")
        #expect(sent.last(chat: "c1", transcript: []) == nil)
        sent.record("Second", chat: "c1")
        #expect(sent.last(chat: "c1", transcript: transcript) == "Second")
        #expect(sent.last(chat: "c2", transcript: []) == nil)
    }
}

@Suite struct ShellCommandTests {
    @Test func shellBlocksAreCommands() {
        #expect(ShellCommand.command(language: "bash", code: "npm run dev") == "npm run dev")
        #expect(ShellCommand.command(language: "ZSH", code: "a\n\nb\n") == "a\nb")
        #expect(
            ShellCommand.command(language: "sh", code: "$ make\n$ make test") == "make\nmake test")
        #expect(ShellCommand.command(language: "shell", code: "  \n") == nil)
    }

    @Test func anUnmarkedBlockIsOneOnlyAsOneLineStartingWithACommonCommand() {
        #expect(ShellCommand.command(language: nil, code: "git status") == "git status")
        #expect(ShellCommand.command(language: nil, code: "$ uv run pytest") == "uv run pytest")
        #expect(ShellCommand.command(language: nil, code: "./scripts/run.sh") == "./scripts/run.sh")
        #expect(ShellCommand.command(language: nil, code: "git add\ngit commit") == nil)
        #expect(ShellCommand.command(language: nil, code: "let x = 1") == nil)
        #expect(ShellCommand.command(language: "ts", code: "npm test") == nil)
    }

    @Test func messagesSplitAroundTheirCommands() {
        let message = """
            Start it:

            ```bash
            npm run dev
            ```
            Then the code:
            ```ts
            const x = 1
            ```
            ```
            git status
            ```
            """
        #expect(
            ShellCommand.segments(message) == [
                .markdown("Start it:\n"),
                .command("npm run dev"),
                .markdown("Then the code:\n```ts\nconst x = 1\n```"),
                .command("git status"),
            ])
    }

    @Test func plainAndStreamingMessagesStayMarkdown() {
        #expect(ShellCommand.segments("Just text") == [.markdown("Just text")])
        #expect(ShellCommand.segments("") == [])
        #expect(
            ShellCommand.segments("Run:\n```bash\nnpm i") == [.markdown("Run:\n```bash\nnpm i")])
    }
}

@MainActor
@Suite struct ConvenienceStoreTests {
    let api = FakeAPI()
    let approvals: ApprovalsStore
    let sessions: SessionsStore
    let activity: ActivityStore

    init() {
        approvals = ApprovalsStore(api: api)
        sessions = SessionsStore(api: api, approvals: approvals)
        activity = ActivityStore(api: api)
        api.set { $0.sessions = [Fixture.session("s1", state: .running)] }
    }

    @Test func aSendWhileWorkingReturnsTheQueuedMessage() async throws {
        try await sessions.load()
        #expect(try await sessions.send("s1", text: "Now") == nil)
        api.set { $0.queueSends = true }
        let queued = try await sessions.send("s1", text: "Later")
        #expect(queued?.text == "Later")
        try await sessions.compact("s1")
        #expect(
            api.calls.suffix(3) == [
                "sendMessage s1 Now []", "sendMessage s1 Later []", "sendMessage s1 /compact []",
            ])
    }

    @Test func contextEventsUpdateTheSession() async throws {
        try await sessions.load()
        sessions.apply(
            Fixture.event(
                EventType.sessionContext, #"{"context": {"percent": 85, "used": 1, "limit": 2}}"#))
        #expect(sessions.session("s1")?.context?.isHigh == true)
        sessions.apply(
            Fixture.event(EventType.sessionContext, #"{"context": null}"#, session: nil))
        #expect(sessions.session("s1")?.context?.percent == 85)
    }

    @Test func aPendingPlanReadsAsPlanReady() async throws {
        var plan = Fixture.approval("ap-question")
        plan.kind = .plan
        plan.sessionID = "s1"
        api.set {
            $0.sessions = [Fixture.session("s1", state: .waiting)]
            $0.approvals = [plan]
        }
        try await approvals.load()
        try await sessions.load()
        #expect(sessions.statusLabel(of: sessions.session("s1")!) == "Plan ready")
    }

    @Test func queuedMessagesLoadArriveAndCancel() async throws {
        var detail = Fixture.session("s1", state: .running)
        detail.queued = [QueuedMessage(id: "q1", text: "One", createdAt: .distantPast)]
        api.set { $0.details["s1"] = detail }
        try await activity.load(session: "s1")
        #expect(activity.queued(session: "s1").map(\.id) == ["q1"])

        let two = QueuedMessage(id: "q2", text: "Two", createdAt: .distantPast)
        activity.enqueue(two, session: "s1")
        activity.enqueue(two, session: "s1")
        #expect(activity.queued(session: "s1").map(\.id) == ["q1", "q2"])

        try await activity.remove("q1", session: "s1")
        #expect(activity.queued(session: "s1").map(\.id) == ["q2"])

        // Already delivered: it leaves the list without an error.
        api.fail("cancelQueued", with: APIError.notFound("No queued message q2"))
        try await activity.remove("q2", session: "s1")
        #expect(activity.queued(session: "s1").isEmpty)
        #expect(api.calls.suffix(2) == ["cancelQueued s1 q1", "cancelQueued s1 q2"])

        activity.apply(
            Fixture.event(
                EventType.sessionQueued,
                #"{"queued": [{"id": "q3", "text": "Three", "attachments": [], "created_at": "2026-10-07T01:00:00Z"}]}"#
            ))
        #expect(activity.queued(session: "s1").map(\.text) == ["Three"])
        activity.apply(Fixture.event(EventType.sessionQueued, #"{"queued": []}"#, session: nil))
        #expect(activity.queued(session: "s1").count == 1)
        activity.apply(Fixture.event(EventType.sessionDeleted, #"{"session_id": "s1"}"#))
        #expect(activity.queued(session: "s1").isEmpty)
    }

    @Test func otherCancelFailuresAreReported() async throws {
        activity.enqueue(
            QueuedMessage(id: "q1", text: "One", createdAt: .distantPast), session: "s1")
        api.fail("cancelQueued")
        await #expect(throws: APIError.self) {
            try await activity.remove("q1", session: "s1")
        }
        #expect(activity.queued(session: "s1").count == 1)
    }

    @Test func plansAreApprovedOrSentBackWithANote() async throws {
        var plan = Fixture.approval("ap-question")
        plan.kind = .plan
        var second = plan
        second.id = "ap-plan-2"
        api.set { $0.approvals = [plan, second] }
        try await approvals.load()

        #expect(approvals.planNote(for: plan) == "")
        approvals.setPlanNote("Keep it smaller", for: plan)
        #expect(approvals.planNote(for: plan) == "Keep it smaller")
        try await approvals.keepPlanning(plan)
        #expect(approvals.planNote(for: plan) == "")

        #expect(approvals.planMode(for: second) == .acceptEdits)
        #expect(try await approvals.approvePlan(second) == .acceptEdits)
        #expect(approvals.pending.isEmpty)
        #expect(
            api.calls.suffix(2) == [
                #"resolveApproval ap-question {"always":false,"decision":"keep_planning","dismiss":false,"message":"Keep it smaller"}"#,
                #"resolveApproval ap-plan-2 {"always":false,"decision":"approve","dismiss":false,"mode":"acceptEdits"}"#,
            ])
    }

    /// Approving a plan can go on asking for each edit, or in Auto (IMP-06).
    @Test func approvingAPlanSendsTheChosenMode() async throws {
        var plan = Fixture.approval("ap-question")
        plan.kind = .plan
        var other = plan
        other.id = "ap-plan-2"
        api.set { $0.approvals = [plan, other] }
        try await approvals.load()

        approvals.setPlanMode(.auto, for: plan)
        #expect(approvals.planMode(for: plan) == .auto)
        #expect(approvals.planMode(for: other) == .acceptEdits)
        #expect(try await approvals.approvePlan(plan) == .auto)
        #expect(api.calls.last?.hasSuffix(#""mode":"auto"}"#) == true)
        // The choice is forgotten with the approval.
        #expect(approvals.planMode(for: plan) == .acceptEdits)

        approvals.setPlanMode(.default, for: other)
        try await approvals.approvePlan(other)
        #expect(api.calls.last?.hasSuffix(#""mode":"default"}"#) == true)
        #expect(
            PermissionMode.planChoices(supportsAuto: true).map(\.planChoiceLabel) == [
                "Auto-accept edits", "Approve edits manually", "Auto",
            ])
        #expect(PermissionMode.planChoices(supportsAuto: false) == [.acceptEdits, .default])
    }
}
