import Foundation
import Testing

@testable import NestKit

/// B96: the branch map of a project, as `GET /api/repos/{name}/branch-map` answers it: main,
/// wip (where the project folder is) with three worktrees, and two worktrees from main.
enum BranchMapFixture {
    static let json = """
        {"default_branch": "main", "current_branch": "wip", "branches": [
          {"name": "main", "parent": null, "worktree": null, "here": false},
          {"name": "b94-codex-settings", "parent": "main",
           "worktree": {"path": "/r/.claude/worktrees/nest-b94", "owner": "nest"}, "here": false},
          {"name": "lazy-scroll", "parent": "main",
           "worktree": {"path": "/r/.claude/worktrees/lazy", "owner": "claude"}, "here": false},
          {"name": "wip", "parent": "main", "worktree": null, "here": true},
          {"name": "pixie-search", "parent": "wip",
           "worktree": {"path": "/r/.claude/worktrees/nest-pixie", "owner": "nest"}, "here": false},
          {"name": "wip-icons", "parent": "wip",
           "worktree": {"path": "/elsewhere/icons", "owner": "other"}, "here": false},
          {"name": "wip-limits", "parent": "wip",
           "worktree": {"path": "/r/.claude/worktrees/nest-limits", "owner": "pixie"}, "here": false}
        ]}
        """

    static var map: BranchMap { Fixture.decode(BranchMap.self, json: json) }

    static func branch(
        _ name: String, parent: String?, worktree: String? = nil, here: Bool = false
    ) -> BranchMap.Branch {
        BranchMap.Branch(
            name: name, parent: parent,
            worktree: worktree.map { BranchMap.Worktree(path: $0, owner: .nest) }, here: here)
    }

    static func map(_ branches: [BranchMap.Branch], default: String = "main") -> BranchMap {
        BranchMap(defaultBranch: `default`, currentBranch: nil, branches: branches)
    }
}

@Suite struct BranchMapDecodingTests {
    /// B96: the map decodes with its worktrees and their owners; an owner a newer daemon
    /// adds reads as unknown.
    @Test func decodesTheMap() throws {
        let map = BranchMapFixture.map
        #expect(map.defaultBranch == "main")
        #expect(map.currentBranch == "wip")
        #expect(map.branches.map(\.name).count == 7)
        let pixie = try #require(map.branch("pixie-search"))
        #expect(pixie.parent == "wip")
        #expect(
            pixie.worktree
                == BranchMap.Worktree(path: "/r/.claude/worktrees/nest-pixie", owner: .nest))
        #expect(map.branch("lazy-scroll")?.worktree?.owner == .claude)
        #expect(map.branch("wip-icons")?.worktree?.owner == .other)
        #expect(map.branch("wip-limits")?.worktree?.owner == .unknown)
        #expect(map.branch("wip")?.here == true)
        #expect(map.branch("wip")?.id == "wip")
        #expect(map.branch("nope") == nil)
        #expect(map.children(of: "wip").map(\.name) == ["pixie-search", "wip-icons", "wip-limits"])

        let detached = Fixture.decode(
            BranchMap.self,
            json: #"{"default_branch": "main", "current_branch": null, "branches": []}"#)
        #expect(detached.currentBranch == nil)
        #expect(detached.branches.isEmpty)
    }

    /// B96: a chat's place names its branch: a worktree by its folder first, else by name;
    /// the project folder by the branch checked out there.
    @Test func findsTheBranchOfAChatsPlace() {
        let map = BranchMapFixture.map
        #expect(
            map.branch(for: .worktree(name: "renamed", folder: "/elsewhere/icons"))?.name
                == "wip-icons")
        #expect(map.branch(for: .worktree(name: "wip-limits", folder: nil))?.name == "wip-limits")
        #expect(map.branch(for: .worktree(name: "gone", folder: "/gone")) == nil)
        #expect(map.branch(for: .projectFolder(branch: "wip", folder: "/r"))?.name == "wip")
        #expect(map.branch(for: .projectFolder(branch: nil, folder: "/r")) == nil)
    }
}

@Suite struct BranchLanesTests {
    /// B96: all branches, depth first from the default branch; each parent's line runs from
    /// its node down through the rows to its last child, which its curve joins.
    @Test func laysOutEveryBranch() {
        let lanes = BranchLanes(map: BranchMapFixture.map)
        #expect(
            lanes.rows.map(\.id) == [
                "main", "b94-codex-settings", "lazy-scroll", "wip", "pixie-search", "wip-icons",
                "wip-limits",
            ])
        #expect(lanes.rows.map(\.depth) == [0, 1, 1, 1, 2, 2, 2])
        #expect(lanes.rows.map(\.parentDepth) == [nil, 0, 0, 0, 1, 1, 1])
        let main = BranchLaneLine(depth: 0, lane: "main", fromMiddle: false)
        let wip = BranchLaneLine(depth: 1, lane: "wip", fromMiddle: false)
        #expect(
            lanes.rows.map(\.lines) == [
                [BranchLaneLine(depth: 0, lane: "main", fromMiddle: true)],
                [main], [main],
                [BranchLaneLine(depth: 1, lane: "wip", fromMiddle: true)],
                [wip], [wip], [],
            ])
        #expect(lanes.rows.map(\.label) == [nil, nil, nil, "here", nil, nil, nil])
        #expect(lanes.worktrees == 5)
        #expect(lanes.count == "5 worktrees")
        #expect(lanes.width == 56)
    }

    /// B96: lanes sit 14 points apart from 14.
    @Test func lanesAreFourteenPointsApart() {
        #expect(BranchLaneRow.x(0) == 14)
        #expect(BranchLaneRow.x(2) == 42)
    }

    /// B96: one worktree is counted in the singular.
    @Test func oneWorktreeIsSingular() {
        let map = BranchMapFixture.map([
            BranchMapFixture.branch("main", parent: nil),
            BranchMapFixture.branch("feature-a", parent: "main", worktree: "/a"),
        ])
        #expect(BranchLanes(map: map).count == "1 worktree")
    }

    /// B96: branches deeper than two keep their lanes: a line passes the deeper rows on
    /// its way to a later child, and the graph widens.
    @Test func deeperBranchesKeepTheirLanes() {
        let map = BranchMapFixture.map([
            BranchMapFixture.branch("main", parent: nil),
            BranchMapFixture.branch("a", parent: "main"),
            BranchMapFixture.branch("b", parent: "a"),
            BranchMapFixture.branch("c", parent: "b", worktree: "/c"),
            BranchMapFixture.branch("d", parent: "a", worktree: "/d"),
        ])
        let lanes = BranchLanes(map: map)
        #expect(lanes.rows.map(\.id) == ["main", "a", "b", "c", "d"])
        #expect(lanes.rows.map(\.depth) == [0, 1, 2, 3, 2])
        #expect(
            lanes.rows.map(\.lines) == [
                [BranchLaneLine(depth: 0, lane: "main", fromMiddle: true)],
                [BranchLaneLine(depth: 1, lane: "a", fromMiddle: true)],
                [
                    BranchLaneLine(depth: 1, lane: "a", fromMiddle: false),
                    BranchLaneLine(depth: 2, lane: "b", fromMiddle: true),
                ],
                [BranchLaneLine(depth: 1, lane: "a", fromMiddle: false)],
                [],
            ])
        #expect(lanes.width == 70)
    }

    /// B96: a branch whose parent is not shown, or a loop the daemon should never send,
    /// still gets a row of its own, as a root.
    @Test func orphansAndLoopsStillShow() {
        let map = BranchMapFixture.map([
            BranchMapFixture.branch("main", parent: nil),
            BranchMapFixture.branch("orphan", parent: "missing"),
            BranchMapFixture.branch("x", parent: "y"),
            BranchMapFixture.branch("y", parent: "x"),
        ])
        let lanes = BranchLanes(map: map)
        #expect(lanes.rows.map(\.id) == ["main", "orphan", "x", "y"])
        #expect(lanes.rows.map(\.depth) == [0, 0, 0, 1])
        #expect(BranchLanes(map: BranchMapFixture.map([])).rows.isEmpty)
        #expect(BranchLanes(map: BranchMapFixture.map([])).width == 28)
    }
}

@Suite struct LaneColorsTests {
    /// B96: the default branch is always grey; the others take the lane colours in order.
    @Test func theDefaultBranchIsGreyAndTheRestTakeColoursInOrder() {
        var colors = LaneColors()
        let map = BranchMapFixture.map
        colors.assign(map)
        let indexes = map.branches.map { colors.index(of: $0.name, in: map) }
        #expect(indexes == [0, 1, 2, 3, 4, 5, 6])
        #expect(colors.index(of: "unknown", in: map) == nil)
        #expect(LaneColors.color(0) == DesignTokens.Colors.Lane.root)
        #expect(LaneColors.color(1) == DesignTokens.Colors.Lane.violet)
        #expect(LaneColors.color(7) == DesignTokens.Colors.Lane.yellow)
    }

    /// B96: a branch keeps its colour while the app runs, even after it went away; a new
    /// branch takes the first colour no shown branch uses.
    @Test func coloursAreSticky() {
        var colors = LaneColors()
        let main = BranchMapFixture.branch("main", parent: nil)
        let a = BranchMapFixture.branch("a", parent: "main")
        let b = BranchMapFixture.branch("b", parent: "main")
        let c = BranchMapFixture.branch("c", parent: "main")
        let first = BranchMapFixture.map([main, a, b])
        colors.assign(first)
        #expect(colors.index(of: "b", in: first) == 2)

        // a is gone: c takes its free colour.
        let second = BranchMapFixture.map([main, b, c])
        colors.assign(second)
        #expect(colors.index(of: "b", in: second) == 2)
        #expect(colors.index(of: "c", in: second) == 1)

        // a is back: it keeps its own colour, though c has it too.
        let third = BranchMapFixture.map([main, a, b, c])
        colors.assign(third)
        #expect(colors.index(of: "a", in: third) == 1)

        // A new default branch is grey whatever it had before.
        let renamed = BranchMapFixture.map([a, b], default: "a")
        #expect(colors.index(of: "a", in: renamed) == 0)
    }

    /// B96: with every colour in use, new branches cycle through them.
    @Test func newBranchesCycleWhenEveryColourIsInUse() {
        var colors = LaneColors()
        let branches =
            [BranchMapFixture.branch("main", parent: nil)]
            + (1...10).map { BranchMapFixture.branch("b\($0)", parent: "main") }
        let map = BranchMapFixture.map(branches)
        colors.assign(map)
        #expect(
            (1...10).map { colors.index(of: "b\($0)", in: map) } == [1, 2, 3, 4, 5, 6, 7, 1, 2, 3])
    }
}

@Suite struct BranchChatTests {
    let map = BranchMapFixture.map
    var repo: Repo {
        var repo = Fixture.repos[0]
        repo.currentBranch = "wip"
        return repo
    }

    func session(
        _ id: String, worktree: String? = nil, branch: String? = nil,
        state: SessionState = .idle, updated: Double = 1_000, archived: Bool = false
    ) -> Session {
        var session = Fixture.session(
            id, state: state, archived: archived, updatedAt: Date(timeIntervalSince1970: updated))
        session.mode = worktree == nil && branch == nil ? .inPlace : .worktree
        session.worktreePath = worktree
        session.branch = branch
        session.cwd = worktree ?? "/r"
        return session
    }

    func chat(_ id: String, cwd: String, worktree: String?, lastActivity: Double = 1_000)
        -> ClaudeChat
    {
        ClaudeChat(
            id: id, repo: "cv-page", title: id, cwd: cwd, worktree: worktree,
            createdAt: Date(timeIntervalSince1970: 0),
            lastActivityAt: Date(timeIntervalSince1970: lastActivity), messageCount: 1)
    }

    func links(_ sessions: [Session], _ chats: [ClaudeChat] = []) -> [String: BranchChatStatus] {
        map.chats(sessions: sessions, claudeChats: chats, repo: repo) {
            StatusTone.of($0.state, hasReview: false)
        }
    }

    /// B96: a row's dot follows every Nest chat in its worktree folder or on its branch by
    /// name; a row with none has no dot.
    @Test func followsNestChatsByFolderAndBranch() {
        let found = links([
            session("by-name", branch: "pixie-search", updated: 5_000),
            session("old", worktree: "/r/.claude/worktrees/nest-pixie", updated: 1_000),
            session("new", worktree: "/r/.claude/worktrees/nest-pixie", updated: 2_000),
            session("icons", branch: "wip-icons", state: .running),
        ])
        #expect(found["pixie-search"] == .idle)
        #expect(found["wip-icons"] == .running)
        #expect(found["main"] == nil)
    }

    /// B96: a chat in the project folder belongs to the branch checked out there.
    @Test func inPlaceChatsBelongToTheHereBranch() {
        #expect(
            links([session("here", state: .waiting)])["wip"]
                == .needsYou)
        let two = links([session("a"), session("b", state: .running)])
        #expect(two["wip"] == .running)
    }

    /// B96: with several chats the dot shows the most urgent: needs you, then running.
    @Test func severalChatsShowTheMostUrgentStatus() {
        let found = links([
            session("run", branch: "wip-icons", state: .running, updated: 9_000),
            session("ask", branch: "wip-icons", state: .waiting, updated: 1_000),
            session("idle", branch: "wip-icons", updated: 5_000),
        ])
        #expect(found["wip-icons"] == .needsYou)
    }

    /// B96: Claude Code chats count by their worktree folder, with the Nest chats there, as
    /// idle; archived chats never count.
    @Test func claudeCodeChatsCountByWorktree() {
        let found = links(
            [
                session("archived", worktree: "/r/.claude/worktrees/lazy", archived: true),
                session("nest", branch: "b94-codex-settings", state: .failed),
            ],
            [
                chat(
                    "lazy-old", cwd: "/r/.claude/worktrees/lazy", worktree: "lazy",
                    lastActivity: 1),
                chat(
                    "lazy-new", cwd: "/r/.claude/worktrees/lazy", worktree: "lazy",
                    lastActivity: 9),
                chat("folder", cwd: "/r", worktree: nil),
                chat("b94", cwd: "/r/.claude/worktrees/nest-b94", worktree: "b94"),
                chat("solo", cwd: "/r/.claude/worktrees/nest-limits", worktree: "limits"),
                {
                    var archived = chat(
                        "gone", cwd: "/r/.claude/worktrees/nest-limits", worktree: "limits")
                    archived.archived = true
                    return archived
                }(),
            ])
        #expect(found["lazy-scroll"] == .idle)
        #expect(found["b94-codex-settings"] == .idle)
        #expect(
            found["wip-limits"] == .idle)
        #expect(found["wip"] == nil)
    }

    /// B96: a row's status dot: running, needs you, or idle for anything else.
    @Test func statusFollowsTheChatsTone() {
        #expect(BranchChatStatus(.running) == .running)
        #expect(BranchChatStatus(.waiting) == .needsYou)
        for tone in [StatusTone.review, .failed, .interrupted, .done] {
            #expect(BranchChatStatus(tone) == .idle)
        }
    }
}

@MainActor
@Suite struct BranchMapStoreTests {
    let api = FakeAPI()
    let store: BranchMapStore

    init() {
        api.set { $0.branchMaps = ["cv-page": BranchMapFixture.map] }
        store = BranchMapStore(api: api)
    }

    /// B96: showing a project loads its map and gives its branches their colours.
    @Test func showingAProjectLoadsItsMap() async {
        #expect(store.map("cv-page") == nil)
        #expect(store.lanes("cv-page") == nil)
        await store.show("cv-page")
        #expect(store.shown == "cv-page")
        #expect(store.map("cv-page")?.branches.count == 7)
        #expect(store.color(of: "main", in: "cv-page") == DesignTokens.Colors.Lane.root)
        #expect(
            store.color(of: "b94-codex-settings", in: "cv-page")
                == DesignTokens.Colors.Lane.violet)
        #expect(store.color(of: "nope", in: "cv-page") == nil)
        #expect(store.color(of: "main", in: "other") == nil)
        #expect(
            store.color(of: .worktree(name: "x", folder: "/elsewhere/icons"), in: "cv-page")
                == LaneColors.color(5))
        #expect(store.color(of: .projectFolder(branch: nil, folder: "/r"), in: "cv-page") == nil)
        #expect(store.color(of: .projectFolder(branch: "wip", folder: "/r"), in: "other") == nil)
        #expect(store.lanes("cv-page")?.rows.count == 7)

        await store.show(nil)
        #expect(store.shown == nil)
        #expect(api.calls == ["repoBranchMap cv-page"])
    }

    /// B96: a failed load keeps the map it had; the next event or connect reads it again.
    @Test func aFailedLoadKeepsTheMap() async {
        await store.show("cv-page")
        api.fail("repoBranchMap")
        await store.load("cv-page")
        #expect(store.map("cv-page")?.branches.count == 7)
    }

    /// B96: a branches event reads the map of a loaded or shown project again, and of no
    /// other; the repo name is in the event.
    @Test func branchEventsRefreshLoadedMaps() async {
        await store.show("cv-page")
        api.set {
            $0.branchMaps["cv-page"] = BranchMapFixture.map([
                BranchMapFixture.branch("main", parent: nil)
            ])
        }
        store.apply(
            Fixture.event(
                EventType.repoBranchesChanged, #"{"name": "cv-page"}"#, id: nil, session: nil))
        store.apply(
            Fixture.event(
                EventType.repoBranchesChanged, #"{"name": "nest"}"#, id: nil, session: nil))
        store.apply(Fixture.event(EventType.sessionDelta, #"{"text": "x"}"#))
        await store.refreshing?.value
        #expect(store.map("cv-page")?.branches.count == 1)
        #expect(api.calls == ["repoBranchMap cv-page", "repoBranchMap cv-page"])
    }

    /// B96: on reconnect every loaded map is read again.
    @Test func reloadReadsEveryLoadedMap() async {
        api.set { $0.branchMaps["nest"] = BranchMapFixture.map([]) }
        await store.load("nest")
        await store.show("cv-page")
        await store.reload()
        #expect(
            api.calls.sorted() == [
                "repoBranchMap cv-page", "repoBranchMap cv-page", "repoBranchMap nest",
                "repoBranchMap nest",
            ])
    }

    /// B96: the panel opens and closes per project.
    @Test func openStateIsPerProject() async {
        await store.show("cv-page")
        #expect(!store.isOpen("cv-page"))
        store.toggle("cv-page")
        #expect(store.isOpen("cv-page"))
        #expect(!store.isOpen("nest"))
        store.toggle("cv-page")
        #expect(!store.isOpen("cv-page"))
    }

    /// B96: the store links the map's rows to the project's chats.
    @Test func linksChats() async {
        var session = Fixture.session("s", state: .running)
        session.worktreePath = "/r/.claude/worktrees/nest-pixie"
        let none = store.chats(in: "cv-page", sessions: [session], claudeChats: [], repo: nil) {
            _ in .running
        }
        #expect(none.isEmpty)
        await store.show("cv-page")
        let found = store.chats(in: "cv-page", sessions: [session], claudeChats: [], repo: nil) {
            _ in .running
        }
        #expect(found["pixie-search"] == .running)
    }
}
