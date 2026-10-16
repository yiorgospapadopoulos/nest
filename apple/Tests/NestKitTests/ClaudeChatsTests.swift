import Foundation
import Testing

@testable import NestKit

@Suite struct ClaudeChatModelTests {
    @Test func decodesTheDaemonsShapeWithAutomatedOptional() throws {
        let chats = Fixture.claudeChats
        #expect(chats.map(\.title) == ["Fix the hero image on mobile", "Try a serif headline"])
        let first = chats[0]
        #expect(first.id == "7c1e9a52-3b4d-4e6f-8a9b-0c1d2e3f4a5b")
        #expect(first.repo == "cv-page")
        #expect(first.cwd == "/Users/example/Personal projects/cv-page")
        #expect(first.worktree == nil)
        #expect(first.messageCount == 14)
        #expect(first.openInClaudeCode)
        #expect(first.lastActivityAt > first.createdAt)
        #expect(chats[1].worktree == "serif")
        // An older daemon leaves `automated` out.
        #expect(chats.map(\.automated) == [false, false])
        let automated = Fixture.decode(
            ClaudeChat.self,
            json: """
                {"id": "x", "repo": "r", "title": "t", "cwd": "/r", "worktree": null,
                 "created_at": "2026-10-06T09:00:00Z", "last_activity_at": "2026-10-06T09:00:00Z",
                 "message_count": 0, "open_in_claude_code": false, "automated": true}
                """)
        #expect(automated.automated)
    }

    @Test func archivedIsReadAndMissingMeansNotArchived() {
        // The fixture's first chat says false and its second leaves the key out.
        #expect(Fixture.claudeChats.map(\.archived) == [false, false])
        let archived = Fixture.decode(ClaudeChat.self, "claude_chat_archived")
        #expect(archived.archived)
        #expect(archived.id == Fixture.claudeChats[0].id)
        #expect(!Fixture.claudeChat("c").archived)
        #expect(Fixture.claudeChat("c", archived: true).archived)
    }

    @Test func paneIDsAreTheirOwnNamespace() {
        let chat = Fixture.claudeChat("abc")
        #expect(chat.paneID == "claude-code:abc")
        #expect(ClaudeChat.chatID(ofPane: chat.paneID) == "abc")
        #expect(ClaudeChat.chatID(ofPane: "abc") == nil)
        #expect(ClaudeChat.chatID(ofPane: "draft-1") == nil)
    }

    @Test func theUpdateEventNamesItsRepos() {
        let event = Fixture.event(
            EventType.claudeChatsUpdated, #"{"repos": ["cv-page", "nest"]}"#, id: nil,
            session: nil)
        #expect(event.body == .claudeChatsUpdated(repos: ["cv-page", "nest"]))
        let broken = Fixture.event(EventType.claudeChatsUpdated, #"{"repos": "cv-page"}"#)
        #expect(broken.body == .other)
    }
}

@MainActor
@Suite struct ClaudeChatsStoreTests {
    let api = FakeAPI()
    let preferences = MemoryStore()
    let settings: SettingsStore
    let store: ClaudeChatsStore

    init() {
        settings = SettingsStore(store: preferences)
        store = ClaudeChatsStore(api: api, settings: settings)
    }

    @Test func listsChatsNewestFirstPerRepo() async throws {
        api.set {
            $0.claudeChats = [
                Fixture.claudeChat("old", lastActivity: 1),
                Fixture.claudeChat("new", lastActivity: 9),
                Fixture.claudeChat("tie-a", lastActivity: 5),
                Fixture.claudeChat("tie-b", lastActivity: 5),
                Fixture.claudeChat("elsewhere", repo: "nest"),
                // A daemon listing a chat twice keeps the first.
                Fixture.claudeChat("new", title: "Duplicate", lastActivity: 9),
            ]
        }

        try await store.load()

        #expect(api.calls == ["claudeChats all automated=false"])
        #expect(store.chats(in: "cv-page").map(\.id) == ["new", "tie-b", "tie-a", "old"])
        #expect(store.chat("new")?.title == "A Claude Code chat")
        #expect(store.chats(in: "nest").map(\.id) == ["elsewhere"])
        #expect(store.chat("missing") == nil)
    }

    @Test func automatedChatsShowOnlyWhenAskedAndTheChoiceIsKept() async throws {
        api.set {
            $0.claudeChats = [
                Fixture.claudeChat("mine"), Fixture.claudeChat("script", automated: true),
            ]
        }
        try await store.load()
        #expect(store.chats(in: "cv-page").map(\.id) == ["mine"])

        try await store.setShowAutomated(true)

        #expect(Set(store.chats(in: "cv-page").map(\.id)) == ["mine", "script"])
        #expect(api.calls.last == "claudeChats all automated=true")
        #expect(SettingsStore(store: preferences).showAutomatedChats)

        try await store.setShowAutomated(false)
        #expect(store.chats(in: "cv-page").map(\.id) == ["mine"])
        #expect(!SettingsStore(store: preferences).showAutomatedChats)
    }

    @Test func reloadingOneRepoLeavesTheOthers() async throws {
        api.set {
            $0.claudeChats = [Fixture.claudeChat("a"), Fixture.claudeChat("h", repo: "nest")]
        }
        try await store.load()
        api.set { $0.claudeChats = [Fixture.claudeChat("b"), Fixture.claudeChat("x", repo: "x")] }

        try await store.load(repo: "cv-page")

        #expect(store.chats(in: "cv-page").map(\.id) == ["b"])
        #expect(store.chats(in: "nest").map(\.id) == ["h"])
        #expect(store.chats(in: "x").isEmpty)
        #expect(api.calls.last == "claudeChats cv-page automated=false")
    }

    @Test func updateEventsListTheNamedReposAgainInOrder() async throws {
        try await store.load()
        #expect(store.chats(in: "cv-page").count == 2)
        api.set { $0.claudeChats = [Fixture.claudeChat("fresh")] }

        store.apply(Fixture.event(EventType.sessionDelta, #"{"text": "x"}"#, id: nil))
        #expect(store.refreshing == nil)
        store.apply(
            Fixture.event(
                EventType.claudeChatsUpdated, #"{"repos": ["cv-page"]}"#, id: nil, session: nil))
        store.apply(
            Fixture.event(
                EventType.claudeChatsUpdated, #"{"repos": ["nest", "cv-page"]}"#, id: nil,
                session: nil))
        await store.refreshing?.value

        #expect(store.chats(in: "cv-page").map(\.id) == ["fresh"])
        #expect(
            Array(api.calls.dropFirst()) == [
                "claudeChats cv-page automated=false", "claudeChats nest automated=false",
                "claudeChats cv-page automated=false",
            ])
    }

    @Test func aFailedRefreshKeepsTheListsUntilTheNextOne() async throws {
        try await store.load()
        let before = store.chats(in: "cv-page").map(\.id)
        api.set { $0.claudeChats = [] }
        api.fail("claudeChats")
        store.apply(
            Fixture.event(
                EventType.claudeChatsUpdated, #"{"repos": ["cv-page", "nest"]}"#, id: nil,
                session: nil))
        await store.refreshing?.value
        #expect(store.chats(in: "cv-page").map(\.id) == before)
        // It stops at the first failure.
        #expect(api.calls.filter { $0.hasPrefix("claudeChats") }.count == 2)

        api.set { $0.failures = [:] }
        store.apply(
            Fixture.event(
                EventType.claudeChatsUpdated, #"{"repos": ["cv-page"]}"#, id: nil, session: nil))
        await store.refreshing?.value
        #expect(store.chats(in: "cv-page").isEmpty)
    }

    @Test func adoptingReturnsTheSessionAndDropsTheChat() async throws {
        try await store.load()
        let chat = store.chats(in: "cv-page")[0]

        let session = try await store.adopt(chat.id)

        #expect(session.providerSessionID == chat.id)
        #expect(session.title == chat.title)
        #expect(store.chat(chat.id) == nil)
        #expect(api.calls.last == "adoptClaudeChat \(chat.id)")
    }

    @Test func archivingMarksTheChatAtOnceAndKeepsTheDaemonsAnswer() async throws {
        try await store.load()
        let id = Fixture.claudeChats[0].id
        let gate = AsyncStream<Void>.makeStream()
        api.set {
            $0.gates["setClaudeChatArchived"] = gate.stream
            // The daemon's copy moved on since the list was read.
            $0.claudeChats[0].messageCount = 15
        }

        let task = Task { try await store.setArchived(id, true) }
        try await waitFor { api.calls.last == "setClaudeChatArchived \(id) true" }
        // Optimistic: the sidebar moves it before the daemon answers.
        #expect(store.chat(id)?.archived == true)
        gate.continuation.finish()
        try await task.value

        var answer = Fixture.claudeChats[0]
        answer.archived = true
        answer.messageCount = 15
        #expect(store.chat(id) == answer)
        // Archived chats stay listed, so Unarchive can find them.
        #expect(store.chats(in: "cv-page").count == 2)

        try await store.setArchived(id, false)
        #expect(store.chat(id)?.archived == false)
        #expect(api.calls.last == "setClaudeChatArchived \(id) false")
    }

    @Test func aFailedArchiveRollsBackAndThrows() async throws {
        try await store.load()
        let id = Fixture.claudeChats[1].id
        api.fail("setClaudeChatArchived")

        await #expect(throws: APIError.server(status: 500, detail: "boom")) {
            try await store.setArchived(id, true)
        }

        #expect(store.chat(id) == Fixture.claudeChats[1])
    }

    @Test func aRollbackKeepsWhatARefreshBroughtMeanwhile() async throws {
        try await store.load()
        let id = Fixture.claudeChats[0].id
        let gate = AsyncStream<Void>.makeStream()
        api.set {
            $0.gates["setClaudeChatArchived"] = gate.stream
            $0.failures["setClaudeChatArchived"] = APIError.notFound("No such chat")
        }
        let task = Task { try await store.setArchived(id, true) }
        try await waitFor { store.chat(id)?.archived == true }
        api.set { $0.claudeChats[0].title = "Renamed in Claude Code" }
        // The refresh still sees the chat archived, as the optimistic update left it.
        api.set { $0.claudeChats[0].archived = true }
        try await store.load(repo: "cv-page")
        gate.continuation.finish()

        await #expect(throws: APIError.notFound("No such chat")) { try await task.value }

        #expect(store.chat(id)?.title == "Renamed in Claude Code")
        #expect(store.chat(id)?.archived == false)
    }

    @Test func archivingAChatAlreadyThereOrUnknownAsksNothing() async throws {
        try await store.load()
        try await store.setArchived(Fixture.claudeChats[0].id, false)
        try await store.setArchived("missing", true)
        #expect(api.calls == ["claudeChats all automated=false"])
    }

    @Test func aFailedAdoptKeepsTheChat() async throws {
        try await store.load()
        api.fail("adoptClaudeChat")
        let id = store.chats(in: "cv-page")[0].id
        await #expect(throws: APIError.self) { _ = try await store.adopt(id) }
        #expect(store.chat(id) != nil)
    }
}

@Suite struct SidebarGroupTests {
    func at(_ seconds: Double) -> Date { Date(timeIntervalSince1970: seconds) }

    /// B77: one list by latest activity whatever each chat's state, Claude Code chats
    /// mixed in; no Pinned group and no titles while nothing is pinned.
    @Test func everyChatIsInOneListNewestFirst() {
        let list = SidebarGroup.list(
            sessions: [
                Fixture.session("waits", state: .waiting, updatedAt: at(300)),
                Fixture.session("runs", state: .running, updatedAt: at(700)),
                Fixture.session("closed", state: .closed, updatedAt: at(900)),
                Fixture.session("idle", state: .idle, updatedAt: at(100)),
            ],
            chats: [Fixture.claudeChat("cc", lastActivity: 500)])

        #expect(list.map(\.kind) == [.chats])
        #expect(list[0].entries.map(\.id) == ["closed", "runs", "claude-code:cc", "waits", "idle"])
        #expect(!list[0].showsTitle)
    }

    @Test func pinnedChatsComeFirstAndBothGroupsShowTheirTitles() {
        let list = SidebarGroup.list(
            sessions: [
                Fixture.session("new", updatedAt: at(900)),
                Fixture.session("pin-old", pinned: true, updatedAt: at(100)),
                Fixture.session("pin-new", state: .running, pinned: true, updatedAt: at(200)),
            ],
            chats: [Fixture.claudeChat("cc", lastActivity: 50)])

        #expect(list.map(\.kind) == [.pinned, .chats])
        #expect(list.map(\.id) == [.pinned, .chats])
        #expect(list[0].entries.map(\.id) == ["pin-new", "pin-old"])
        #expect(list[1].entries.map(\.id) == ["new", "claude-code:cc"])
        #expect(list.allSatisfy { $0.showsTitle })
    }

    @Test func archivedChatsStayApartAtTheEnd() {
        let list = SidebarGroup.list(
            sessions: [
                Fixture.session("old", pinned: true, archived: true, updatedAt: at(500)),
                Fixture.session("live", updatedAt: at(100)),
            ],
            chats: [
                Fixture.claudeChat("gone", lastActivity: 900, archived: true),
                Fixture.claudeChat("older", lastActivity: 100, archived: true),
            ])

        #expect(list.map(\.kind) == [.chats, .archived])
        #expect(list[0].entries.map(\.id) == ["live"])
        #expect(list[1].entries.map(\.id) == ["claude-code:gone", "old", "claude-code:older"])
        #expect(list[1].showsTitle)
    }

    @Test func onlyPinnedOrOnlyArchivedChatsLeaveTheOtherGroupsOut() {
        let pinned = SidebarGroup.list(
            sessions: [Fixture.session("p", pinned: true)], chats: [])
        #expect(pinned.map(\.kind) == [.pinned])

        let archived = SidebarGroup.list(
            sessions: [], chats: [Fixture.claudeChat("a", archived: true)])
        #expect(archived.map(\.kind) == [.archived])

        #expect(SidebarGroup.list(sessions: [], chats: []).isEmpty)
        #expect(SidebarSection.allCases.map(\.title) == ["Pinned", "Chats", "Archived"])
    }

    @Test func entriesReadTheirSessionOrChat() {
        let session = SidebarEntry.session(
            Fixture.session("s", title: "Session", updatedAt: Date(timeIntervalSince1970: 7)))
        let chat = SidebarEntry.claudeChat(
            Fixture.claudeChat("c", title: "Chat", lastActivity: 8))
        #expect(session.title == "Session")
        #expect(chat.title == "Chat")
        #expect(session.lastActivity == Date(timeIntervalSince1970: 7))
        #expect(chat.lastActivity == Date(timeIntervalSince1970: 8))
        #expect([session.id, chat.id] == ["s", "claude-code:c"])
    }
}

@MainActor
@Suite struct ClaudeChatTranscriptTests {
    let api = FakeAPI()

    @Test func aClaudeChatPaneReadsItsHistoryWholeEachTime() async throws {
        let id = Fixture.claudeChats[0].id
        api.set { $0.claudeChatEvents[id] = Fixture.claudeChatEvents }
        let transcripts = Transcripts(api: api)
        let pane = Fixture.claudeChats[0].paneID
        #expect(transcripts.existing(pane) == nil)

        let transcript = transcripts.transcript(for: pane)
        #expect(transcripts.existing(pane) === transcript)
        #expect(transcript.sessionID == id)
        #expect(transcript.source == .claudeChat)
        try await transcript.load()
        #expect(transcript.items.count == 3)

        try await transcript.load()

        #expect(transcript.items.count == 3)
        #expect(api.calls == ["claudeChatEvents \(id)", "claudeChatEvents \(id)"])
        guard case .user(let text, _) = transcript.items[0].content else {
            Issue.record("expected the user's message first")
            return
        }
        #expect(text == "The hero image is cut off on phones")
    }

    @Test func sessionPanesKeepReadingSessionEvents() async throws {
        let transcript = Transcripts(api: api).transcript(for: "s1")
        #expect(transcript.source == .session)
        try await transcript.load()
        #expect(api.calls == ["sessionEvents s1 after=0"])
    }
}

@MainActor
@Suite struct ClaudeChatLiveSyncTests {
    @Test func connectingListsTheChatsAndUpdatesRefreshThem() async throws {
        let api = FakeAPI()
        let model = AppModel(api: api, events: ManualEventSource(), preferences: MemoryStore())
        await model.live.refresh()
        #expect(model.claudeChats.chats(in: "cv-page").count == 2)
        #expect(model.app.syncError == nil)

        api.set { $0.claudeChats = [] }
        model.live.route(
            Fixture.event(
                EventType.claudeChatsUpdated, #"{"repos": ["cv-page"]}"#, id: nil, session: nil))
        await model.claudeChats.refreshing?.value

        #expect(model.claudeChats.chats(in: "cv-page").isEmpty)
    }
}

@MainActor
@Suite struct ContinueInNestTests {
    let workspace = CGSize(width: 1200, height: 800)

    @Test func theAdoptedSessionTakesTheChatsPaneAndSelection() {
        let pane = Fixture.claudeChat("cc").paneID
        var state = ProjectState()
        for id in ["s1", pane, "s2", "s3"] {
            state.openChat(id, in: workspace)
        }
        state.focusPane(pane)
        // The four-pane rule holds for Claude Code chats too: a fifth replaces the last.
        #expect(state.openChat("s4", in: workspace) == .replaced("s3"))
        state.focusPane(pane)
        let before = state.layout.leaves
        #expect(before.count == 4 && before.contains(pane) && !before.contains("s3"))

        state.replaceChat(pane, with: "adopted")

        #expect(state.layout.leaves == before.map { $0 == pane ? "adopted" : $0 })
        #expect(state.layout.focused == "adopted")
        #expect(state.selectedChat == "adopted")
    }

    @Test func insertedSessionsJoinTheSidebar() {
        let api = FakeAPI()
        let sessions = SessionsStore(api: api, approvals: ApprovalsStore(api: api))
        sessions.insert(Fixture.session("adopted", state: .idle))
        #expect(sessions.sessions(in: "cv-page").map(\.id) == ["adopted"])
        #expect(sessions.session("adopted") != nil)
        #expect(api.calls.isEmpty)
    }
}
