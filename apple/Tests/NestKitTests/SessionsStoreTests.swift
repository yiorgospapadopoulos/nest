import Foundation
import Testing

@testable import NestKit

@MainActor
@Suite struct SessionsStoreTests {
    let api = FakeAPI()
    let approvals: ApprovalsStore
    let store: SessionsStore

    init() {
        approvals = ApprovalsStore(api: api)
        store = SessionsStore(api: api, approvals: approvals)
    }

    func seed(_ sessions: [Session]) async throws {
        api.set { $0.sessions = sessions }
        try await store.load()
    }

    @Test func loadsOpenAndArchivedSessions() async throws {
        try await seed(Fixture.sessions + Fixture.archivedSessions)
        #expect(store.sessions.count == 3)
        #expect(api.calls == ["sessions archived=false", "sessions archived=true"])
        #expect(store.session("ffff0000ffff0000ffff0000ffff0000")?.isArchived == true)
        #expect(store.session("missing") == nil)
    }

    @Test func eachChatHasItsChatListGroup() async throws {
        try await seed([
            Fixture.session("done", state: .closed),
            Fixture.session("idle", state: .idle),
            Fixture.session("broken", state: .failed),
            Fixture.session("run", state: .running),
            Fixture.session("setup", state: .starting),
            Fixture.session("wait", state: .waiting),
            Fixture.session("pinned", state: .waiting, pinned: true),
            Fixture.session("old", state: .closed, pinned: true, archived: true),
        ])

        let groups = ["done", "idle", "broken", "run", "setup", "wait", "pinned", "old"].map {
            store.group(of: store.session($0)!)
        }
        #expect(
            groups == [.done, .idle, .idle, .running, .running, .needsYou, .pinned, .archived])
    }

    @Test func aPendingReviewPutsAnIdleSessionUnderNeedsYou() async throws {
        let reviewed = Fixture.approval("ap-review")
        try await seed([Fixture.session(reviewed.sessionID, state: .idle)])
        #expect(store.group(of: store.session(reviewed.sessionID)!) == .idle)

        approvals.apply(.approvalCreated(reviewed))

        #expect(store.group(of: store.session(reviewed.sessionID)!) == .needsYou)
        #expect(store.board(in: "cv-page")[.review]?.map(\.id) == [reviewed.sessionID])
    }

    /// As on the iPhone, a pull request ready to merge needs the user, so the sidebar
    /// group agrees with the tab's count (audit BUG-77).
    @Test func aMergeReadyChatIsUnderNeedsYou() async throws {
        var merge = Fixture.approval("ap-review")
        merge.id = "ap-merge"
        merge.kind = .merge
        try await seed([Fixture.session(merge.sessionID, state: .idle)])

        approvals.apply(.approvalCreated(merge))

        #expect(store.group(of: store.session(merge.sessionID)!) == .needsYou)
        #expect(store.attention(of: "cv-page") == 1)
    }

    @Test func boardColumnsLeaveArchivedOut() async throws {
        try await seed([
            Fixture.session("run", state: .running), Fixture.session("wait", state: .waiting),
            Fixture.session("idle", state: .idle), Fixture.session("closed", state: .closed),
            Fixture.session("gone", state: .idle, archived: true),
        ])
        let board = store.board(in: "cv-page")
        #expect(board[.running]?.map(\.id) == ["run"])
        #expect(board[.waiting]?.map(\.id) == ["wait"])
        #expect(Set(board[.done]?.map(\.id) ?? []) == ["idle", "closed"])
        #expect(board[.review] == nil)
        #expect(
            BoardColumn.allCases.map(\.title) == [
                "Running", "Waiting on you", "Ready for review", "Done",
            ])
    }

    @Test func createsAndSendsMessages() async throws {
        let created = try await store.create(
            CreateSessionRequest(repo: "cv-page", prompt: "Add dark mode", model: "opus"))
        #expect(store.session(created.id)?.state == .starting)
        #expect(created.model == "opus")

        try await store.send(created.id, text: "Also the footer", attachmentIDs: ["a1"])
        try await store.interrupt(created.id)

        #expect(store.session(created.id)?.state == .running)
        #expect(
            api.calls == [
                "createSession Add dark mode", "sendMessage new-0 Also the footer [\"a1\"]",
                "interrupt new-0",
            ])
    }

    @Test func organizesSessions() async throws {
        try await seed([Fixture.session("s1", title: "Old title")])

        try await store.setPinned("s1", true)
        #expect(store.session("s1")?.pinned == true)
        try await store.rename("s1", to: "  New title ")
        #expect(store.session("s1")?.title == "New title")
        try await store.archive("s1")
        #expect(store.session("s1")?.isArchived == true)
        try await store.unarchive("s1")
        #expect(store.session("s1")?.isArchived == false)
        try await store.setModel("s1", "haiku")
        #expect(store.session("s1")?.model == "haiku")
        try await store.setPermissionMode("s1", .plan)
        #expect(store.session("s1")?.permissionMode == .plan)
        try await store.setEffort("s1", .max)
        #expect(store.session("s1")?.effort == .max)
        #expect(try await store.openInClaudeCode("s1").launcher == "/tmp/s1.command")
        try await store.delete("s1")
        #expect(store.session("s1") == nil)
        #expect(api.calls.filter { $0.hasPrefix("updateSession") }.count == 7)
    }

    @Test func renamingToBlankOrTheSameTitleDoesNothing() async throws {
        try await seed([Fixture.session("s1", title: "Same")])
        try await store.rename("s1", to: "   ")
        try await store.rename("s1", to: "Same")
        #expect(!api.calls.contains { $0.hasPrefix("updateSession") })
    }

    @Test func failedActionsThrowTheDaemonsError() async throws {
        try await seed([Fixture.session("s1")])
        api.fail("updateSession", with: APIError.conflict("session 's1' is closed"))
        await #expect(throws: APIError.conflict("session 's1' is closed")) {
            try await store.setModel("s1", "opus")
        }
        #expect(store.session("s1")?.model == "sonnet")
    }

    @Test func liveEventsUpdateSessions() async throws {
        try await seed([
            Fixture.session("s1", state: .running, updatedAt: .init(timeIntervalSince1970: 0))
        ])

        store.apply(
            Fixture.event(EventType.sessionState, #"{"state": "failed", "error": "agent crashed"}"#)
        )
        #expect(store.session("s1")?.state == .failed)
        #expect(store.session("s1")?.lastError == "agent crashed")
        #expect(store.session("s1")?.updatedAt == Fixture.event("x", "{}").ts)

        store.apply(Fixture.event(EventType.sessionState, #"{"state": "idle", "error": null}"#))
        #expect(store.session("s1")?.lastError == "agent crashed")

        store.apply(Fixture.event(EventType.prOpened, #"{"url": "https://example.com/pr/9"}"#))
        #expect(store.session("s1")?.prURL == "https://example.com/pr/9")

        var renamed = Fixture.session("s1", title: "Renamed")
        renamed.pinned = true
        store.apply(
            Fixture.event(
                EventType.sessionUpdated, #"{"changes": {}, "session": \#(Fixture.json(renamed))}"#)
        )
        #expect(store.session("s1")?.title == "Renamed")

        store.apply(
            Fixture.event(
                EventType.sessionCreated, #"{"session": \#(Fixture.json(Fixture.session("s2")))}"#))
        #expect(store.session("s2") != nil)

        store.apply(Fixture.event(EventType.sessionDeleted, #"{"session_id": "s2"}"#, session: nil))
        #expect(store.session("s2") == nil)
    }

    /// A worktree chat learns its folder, branch and base once the worktree exists, so
    /// terminal commands run there and not in the main checkout (audit BUG-55).
    @Test func aWorkspaceEventGivesTheChatItsFolderAndBranch() async throws {
        var session = Fixture.session("s1", state: .starting)
        session.cwd = nil
        session.worktreePath = nil
        session.branch = nil
        session.baseRef = nil
        try await seed([session])

        store.apply(
            Fixture.event(
                EventType.sessionWorkspace,
                #"{"path": "/w/s1", "branch": "agent/s1", "base_ref": "abc", "linked": [], "missing": [], "existing": []}"#
            ))

        let updated = try #require(store.session("s1"))
        #expect(updated.worktreePath == "/w/s1")
        #expect(updated.cwd == "/w/s1")
        #expect(updated.folder == "/w/s1")
        #expect(updated.branch == "agent/s1")
        #expect(updated.baseRef == "abc")
    }

    /// After any 409 from Approve the chat and its diff are read again, so the chat as it
    /// is now and the moved branch show (audit BUG-50).
    @Test func aRefusedApproveReadsTheChatAndItsDiffAgain() async throws {
        let review = Fixture.approval("ap-review")
        let id = review.sessionID
        try await seed([Fixture.session(id)])
        approvals.apply(.approvalCreated(review))
        try await approvals.loadDiff(for: review)
        var flagged = Fixture.session(id)
        flagged.title = "Read again"
        var moved = Fixture.diff
        moved.head = ReviewHead(commit: "4444", branch: "agent/dark-mode-1a2b3c")
        api.set {
            $0.details[id] = flagged
            $0.diff = moved
        }
        let refusal = APIError.approveRefused("The branch moved.", reason: .headChanged)
        api.fail("approve", with: refusal)

        await #expect(throws: refusal) {
            try await store.publish(
                review, approvals.publishForm(for: review, session: store.session(id)))
        }

        let calls = api.calls.suffix(3).map { $0.components(separatedBy: " ")[0] }
        #expect(calls == ["approve", "session", "diff"])
        #expect(store.session(id)?.title == "Read again")
        #expect(approvals.diffs[id] == moved)
        #expect(approvals.isReviewLoaded(review))
    }

    @Test func otherApproveFailuresReadNothingAgain() async throws {
        let review = Fixture.approval("ap-review")
        try await seed([Fixture.session(review.sessionID)])
        approvals.apply(.approvalCreated(review))
        try await approvals.loadDiff(for: review)
        api.fail("approve", with: APIError.gitFailed("push failed", step: "push", stderr: ""))
        await #expect(throws: APIError.self) {
            try await store.publish(review, approvals.publishForm(for: review, session: nil))
        }
        #expect(api.calls.last?.hasPrefix("approve") == true)
    }

    @Test func aPublishedChatIsStored() async throws {
        let review = Fixture.approval("ap-review")
        try await seed([Fixture.session(review.sessionID)])
        approvals.apply(.approvalCreated(review))
        try await approvals.loadDiff(for: review)
        let session = try await store.publish(
            review, approvals.publishForm(for: review, session: nil))
        #expect(session.prURL == "https://example.com/pr/1")
        #expect(store.session(review.sessionID)?.prURL == "https://example.com/pr/1")
    }

    @Test func eventsForUnknownSessionsAreIgnored() async throws {
        try await seed([Fixture.session("s1")])
        let before = store.sessions
        store.apply(
            Fixture.event(
                EventType.sessionState, #"{"state": "running", "error": null}"#, session: "zzz"))
        store.apply(
            Fixture.event(
                EventType.sessionState, #"{"state": "running", "error": null}"#, session: nil))
        store.apply(Fixture.event(EventType.prOpened, #"{"url": "u"}"#, session: nil))
        store.apply(Fixture.event("daemon.started", "{}"))
        #expect(store.sessions == before)
    }

    @Test func statusLabelsAndTones() async throws {
        var question = Fixture.approval("ap-question")
        question.sessionID = "ask"
        var permission = Fixture.approval("ap-perm")
        permission.sessionID = "perm"
        var review = Fixture.approval("ap-review")
        review.sessionID = "review"
        // A question outranks a plan, and a plan a permission prompt.
        func pending(_ kind: ApprovalKind, _ session: String) -> Approval {
            var approval = Fixture.approval("ap-perm")
            approval.id = "\(kind)-\(session)"
            approval.kind = kind
            approval.sessionID = session
            return approval
        }
        api.set {
            $0.approvals = [
                question, permission, review, pending(.plan, "ask"), pending(.plan, "plan"),
                pending(.permission, "plan"), pending(.merge, "merge"),
            ]
        }
        try await approvals.load()
        let states: [(String, SessionState)] = [
            ("setup", .starting), ("run", .running), ("ask", .waiting), ("plan", .waiting),
            ("perm", .waiting), ("stop", .interrupted), ("broken", .failed), ("done", .closed),
            ("idle", .idle), ("review", .idle), ("merge", .idle), ("odd", .unknown),
        ]
        let labels = states.map { store.statusLabel(of: Fixture.session($0.0, state: $0.1)) }
        #expect(
            labels == [
                "Starting", "Running", "Question", "Plan ready", "Needs approval",
                "Interrupted", "Failed", "Done", "Idle", "Ready for review", "Ready to merge",
                "Idle",
            ])
        #expect(store.tone(of: Fixture.session("review", state: .idle)) == .review)
        #expect(store.tone(of: Fixture.session("merge", state: .idle)) == .review)
        #expect(store.tone(of: Fixture.session("idle", state: .idle)) == .done)
        #expect(store.tone(of: Fixture.session("run", state: .running)) == .running)
    }

    @Test func pixieChatsStayOutOfProjectLists() async throws {
        var pixieChat = Fixture.session("pc", repo: "pixie:p1", state: .waiting)
        pixieChat.pixieID = "p1"
        var stuck = Fixture.session("ps", repo: "cv-page", state: .running)
        stuck.pixieID = "p1"
        stuck.stuck = StuckFixture.flag
        try await seed([pixieChat, stuck, Fixture.session("normal")])
        approvals.apply(
            .approvalCreated(
                pixieApproval(session: "pc")))

        #expect(store.session("pc")?.pixieID == "p1")
        #expect(store.sessions(in: "pixie:p1").isEmpty)
        #expect(store.sessions(in: "cv-page").map(\.id) == ["normal"])
        #expect(store.board(in: "cv-page").values.flatMap { $0 }.map(\.id) == ["normal"])
        #expect(store.stuck(in: nil).isEmpty)
        // The pixie's approval reaches the Dock badge, but no project's count.
        #expect(store.attention() == 1)
        #expect(store.attention(of: "cv-page") == 0)
        #expect(store.attention(of: "pixie:p1") == 1)
        #expect(approvals.pending.count == 1)
    }

    @Test func pixieChatsAreReadOneByOneAndOutliveAReload() async throws {
        var pixieChat = Fixture.session("pc", repo: "pixie:p1", state: .idle)
        pixieChat.pixieID = "p1"
        api.set { $0.details["pc"] = pixieChat }
        try await seed([Fixture.session("normal")])
        #expect(store.session("pc") == nil)

        try await store.fetch("pc")
        #expect(store.session("pc")?.pixieID == "p1")
        // The daemon's list has no pixie chats; a reload keeps the one already read.
        try await store.load()
        #expect(Set(store.sessions.keys) == ["normal", "pc"])
    }

    func pixieApproval(session: String) -> Approval {
        var approval = Fixture.approval("ap-perm")
        approval.id = "ap-pixie"
        approval.sessionID = session
        approval.repo = "pixie:p1"
        return approval
    }
}
