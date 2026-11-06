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
        _ name: String, parent: String?, worktree: String? = nil, here: Bool = false,
        behind: Int = 0, remote: String? = nil
    ) -> BranchMap.Branch {
        BranchMap.Branch(
            name: name, parent: parent,
            worktree: worktree.map { BranchMap.Worktree(path: $0, owner: .nest) }, here: here,
            behind: behind, remote: remote)
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

    /// B131: the new fields decode, and an older daemon's map, without them, still reads.
    @Test func decodesTheNewFieldsWithAnOlderDaemonsMapStillReading() throws {
        let older = BranchMapFixture.map
        #expect(older.remoteBranches.isEmpty)
        #expect(!older.detached)
        #expect(older.branches.allSatisfy { $0.behind == 0 && $0.remote == nil })

        let map = Fixture.decode(
            BranchMap.self,
            json: """
                {"default_branch": null, "current_branch": null, "detached": true, "branches": [
                  {"name": "main", "parent": null, "worktree": null, "here": false, "behind": 3,
                   "remote": "origin"}
                ], "remote_branches": [{"remote": "origin", "name": "feat/x"}]}
                """)
        #expect(map.defaultBranch == nil)
        #expect(map.detached)
        let main = try #require(map.top)
        #expect(main.behind == 3)
        #expect(main.remote == "origin")
        #expect(map.remoteBranches == [BranchMap.RemoteBranch(remote: "origin", name: "feat/x")])
        #expect(map.remoteBranches[0].id == "origin/feat/x")
    }

    /// B131: "N behind" is a note on local branches with a count, never on a remote-only
    /// top row.
    @Test func theBehindNoteIsOnLocalBranchesOnly() {
        #expect(BranchMapFixture.branch("a", parent: "m", behind: 3).behindNote == "3 behind")
        #expect(BranchMapFixture.branch("a", parent: "m").behindNote == nil)
        #expect(
            BranchMapFixture.branch("m", parent: nil, behind: 3, remote: "origin").behindNote
                == nil)
    }

    /// B131: selecting a row asks for its worktree when it has one, else its branch.
    @Test func aRowSelectsItsWorktreeOrItsBranch() throws {
        let map = BranchMapFixture.map
        #expect(
            try #require(map.branch("wip-icons")).selection
                == SelectPlaceRequest(worktreePath: "/elsewhere/icons"))
        #expect(try #require(map.branch("main")).selection == SelectPlaceRequest(branch: "main"))
    }

    /// B131: Find ignores case and lists remote branches after local ones.
    @Test func findMatchesAnyCaseOnBothLists() {
        var map = BranchMapFixture.map
        map.remoteBranches = [BranchMap.RemoteBranch(remote: "origin", name: "feat/WIP-x")]
        let found = map.find("WiP")
        #expect(found.branches.map(\.name) == ["wip", "wip-icons", "wip-limits"])
        #expect(found.remotes.map(\.name) == ["feat/WIP-x"])
        #expect(map.find("nothing").isEmpty)
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
        #expect(lanes.width == 56)
    }

    /// B96: lanes sit 14 points apart from 14.
    @Test func lanesAreFourteenPointsApart() {
        #expect(BranchLaneRow.x(0) == 14)
        #expect(BranchLaneRow.x(2) == 42)
    }

    /// B131: rows past the indent cap sit on level 3, name their parent and leave the width
    /// fixed, their lines stopping at the cap's lane; the full tree has no cap.
    @Test func theIndentStopsAtLevelThree() {
        let map = BranchMapFixture.map([
            BranchMapFixture.branch("main", parent: nil),
            BranchMapFixture.branch("a", parent: "main"),
            BranchMapFixture.branch("b", parent: "a"),
            BranchMapFixture.branch("c", parent: "b"),
            BranchMapFixture.branch("d", parent: "c"),
            BranchMapFixture.branch("e", parent: "d"),
            BranchMapFixture.branch("f", parent: "main"),
        ])
        let capped = BranchLanes(map: map, maxDepth: BranchLanes.indentCap)
        #expect(BranchLanes.indentCap == 3)
        #expect(capped.rows.map(\.depth) == [0, 1, 2, 3, 3, 3, 1])
        #expect(capped.rows.map(\.fromParent) == [nil, nil, nil, nil, "c", "d", nil])
        #expect(capped.rows.map(\.parentDepth) == [nil, 0, 1, 2, 3, 3, 0])
        #expect(capped.width == BranchLaneRow.x(3) + 14)
        #expect(capped.rows.flatMap(\.lines).allSatisfy { $0.depth <= 3 })

        let tree = BranchLanes(map: map)
        #expect(tree.rows.map(\.depth) == [0, 1, 2, 3, 4, 5, 1])
        #expect(tree.rows.allSatisfy { $0.fromParent == nil })
        #expect(tree.width == BranchLaneRow.x(5) + 14)
    }

    /// B131: the row with no parent is the top row, kept out of the scrolling rows; rows
    /// lose nothing to it, and an orphan scrolls.
    @Test func theTopRowComesOutOfTheScrollingList() {
        let lanes = BranchLanes(map: BranchMapFixture.map)
        #expect(lanes.top?.id == "main")
        #expect(lanes.rest.count == 6)
        #expect(!lanes.rest.contains { $0.id == "main" })

        let orphan = BranchLanes(
            map: BranchMapFixture.map([
                BranchMapFixture.branch("orphan", parent: "gone"),
                BranchMapFixture.branch("main", parent: nil),
            ]))
        #expect(orphan.top?.id == "main")
        #expect(orphan.rest.map(\.id) == ["orphan"])
        #expect(BranchLanes(map: BranchMapFixture.map([])).top == nil)
    }

    /// B131: a branch with no children and no worktree wears its parent's lane until it is
    /// selected or has a chat.
    @Test func aPlainBranchWearsItsParentsLaneUntilItMeansSomething() throws {
        let map = BranchMapFixture.map([
            BranchMapFixture.branch("main", parent: nil),
            BranchMapFixture.branch("wip", parent: "main"),
            BranchMapFixture.branch("plain", parent: "wip"),
            BranchMapFixture.branch("kept", parent: "wip", worktree: "/k"),
        ])
        let rows = BranchLanes(map: map).rows
        let plain = try #require(rows.first { $0.id == "plain" })
        #expect(plain.plain)
        #expect(plain.lane(selected: false, chat: nil) == "wip")
        #expect(plain.lane(selected: true, chat: nil) == "plain")
        #expect(plain.lane(selected: false, chat: .idle) == "plain")
        #expect(rows.first { $0.id == "kept" }?.plain == false)
        #expect(rows.first { $0.id == "wip" }?.plain == false)
        #expect(rows.first { $0.id == "main" }?.plain == false)
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
    /// B96: the top row is always grey; the others take the lane colours in order.
    @Test func theTopRowIsGreyAndTheRestTakeColoursInOrder() {
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
        let a = BranchMapFixture.branch("a", parent: "main", worktree: "/a")
        let b = BranchMapFixture.branch("b", parent: "main", worktree: "/b")
        let c = BranchMapFixture.branch("c", parent: "main", worktree: "/c")
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

    }

    /// B131: grey goes to the row with no parent, not the project's default branch, so wip
    /// takes a colour when it is the default with main on top; a new top row is grey
    /// whatever it had before.
    @Test func greyFollowsTheTopRowNotTheDefaultBranch() {
        var colors = LaneColors()
        let map = BranchMapFixture.map(
            [
                BranchMapFixture.branch("main", parent: nil),
                BranchMapFixture.branch("wip", parent: "main", worktree: "/w", here: true),
            ], default: "wip")
        colors.assign(map)
        #expect(colors.index(of: "main", in: map) == 0)
        #expect(colors.index(of: "wip", in: map) == 1)

        let moved = BranchMapFixture.map([BranchMapFixture.branch("wip", parent: nil)])
        #expect(colors.index(of: "wip", in: moved) == 0)
    }

    /// B131: a plain branch takes no colour until something asks for it, so it uses none up.
    @Test func aPlainBranchTakesNoColourUntilAsked() {
        var colors = LaneColors()
        let map = BranchMapFixture.map([
            BranchMapFixture.branch("main", parent: nil),
            BranchMapFixture.branch("plain", parent: "main"),
            BranchMapFixture.branch("kept", parent: "main", worktree: "/k"),
        ])
        colors.assign(map)
        #expect(colors.index(of: "kept", in: map) == 1)
        #expect(colors.index(of: "plain", in: map) == 2)
        #expect(colors.index(of: "plain", in: map) == 2)
    }

    /// B96: with every colour in use, new branches cycle through them.
    @Test func newBranchesCycleWhenEveryColourIsInUse() {
        var colors = LaneColors()
        let branches =
            [BranchMapFixture.branch("main", parent: nil)]
            + (1...10).map { BranchMapFixture.branch("b\($0)", parent: "main", worktree: "/b") }
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
            id: id, repo: "todo-ui", title: id, cwd: cwd, worktree: worktree,
            createdAt: Date(timeIntervalSince1970: 0),
            lastActivityAt: Date(timeIntervalSince1970: lastActivity), messageCount: 1)
    }

    func links(_ sessions: [Session], _ chats: [ClaudeChat] = []) -> [String: BranchChatStatus] {
        map.chats(sessions: sessions, claudeChats: chats, repo: repo) {
            StatusTone.of($0.state, hasReview: false)
        }
    }

    /// B119: a chat that left a kept worktree no longer lights its branch, and one back in
    /// place follows the folder's branch.
    @Test func dotsFollowAChatThatMoved() {
        var moved = session("moved", worktree: "/r/.claude/worktrees/nest-b94", state: .running)
        moved.branch = "b94-codex-settings"
        moved.earlierWorktrees = [
            EarlierWorktree(
                path: "/r/.claude/worktrees/lazy", branch: "lazy-scroll", baseRef: nil,
                startedAt: Date(timeIntervalSince1970: 0),
                endedAt: Date(timeIntervalSince1970: 1), state: .kept)
        ]
        var removed = session("removed")
        removed.earlierWorktrees = [
            EarlierWorktree(
                path: "/r/.claude/worktrees/nest-limits", branch: "wip-limits", baseRef: nil,
                startedAt: Date(timeIntervalSince1970: 0),
                endedAt: Date(timeIntervalSince1970: 1), state: .deleted)
        ]

        let found = links([moved, removed])

        #expect(found["lazy-scroll"] == nil)
        #expect(found["wip-limits"] == nil)
        #expect(found["b94-codex-settings"] == .running)
        #expect(found["wip"] == .idle)
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

/// B131: opening the map jumps only when the selected row is off screen, then centres it.
@Suite struct RowRevealTests {
    func offset(_ row: Int, current: Double = 0) -> Double? {
        RowReveal.offset(row: row, height: 34, current: current, viewport: 170, content: 3400)
    }

    @Test func aRowInViewMovesNothing() {
        #expect(offset(0) == nil)
        #expect(offset(4) == nil)
        #expect(offset(10, current: 340) == nil)
    }

    @Test func aRowOffScreenIsCentredInsideTheList() {
        #expect(offset(20) == 612)
        #expect(offset(1, current: 340) == 0)
        #expect(offset(99) == 3230)
    }

    func sideways(_ start: Double, _ end: Double, current: Double = 0) -> Double? {
        RowReveal.sideways(
            start: start, end: end, current: current, viewport: 700, content: 2000)
    }

    /// B131: a name in view moves nothing sideways.
    @Test func aNameInViewStaysSideways() {
        #expect(sideways(100, 600) == nil)
        #expect(sideways(800, 1200, current: 600) == nil)
    }

    /// B131: a name past the right edge shows its end with some room.
    @Test func aNamePastTheRightShowsItsEnd() {
        #expect(sideways(300, 800) == 144)
        #expect(sideways(1900, 1990) == 1300)
    }

    /// B131: a name wider than the view shows its start, never scrolled out.
    @Test func aNameWiderThanTheViewShowsItsStart() {
        #expect(sideways(300, 1500) == 256)
    }

    /// B131: a name left of the view comes back with the same room.
    @Test func aNameLeftOfTheViewComesBack() {
        #expect(sideways(100, 200, current: 500) == 56)
        #expect(sideways(20, 200, current: 500) == 0)
    }
}

@MainActor
@Suite struct BranchMapStoreTests {
    let api = FakeAPI()
    let store: BranchMapStore

    init() {
        api.set { $0.branchMaps = ["todo-ui": BranchMapFixture.map] }
        store = BranchMapStore(api: api, store: MemoryStore())
    }

    /// B96: showing a project loads its map and gives its branches their colours.
    @Test func showingAProjectLoadsItsMap() async {
        #expect(store.map("todo-ui") == nil)
        #expect(store.lanes("todo-ui") == nil)
        await store.show("todo-ui")
        #expect(store.shown == "todo-ui")
        #expect(store.map("todo-ui")?.branches.count == 7)
        #expect(store.color(of: "main", in: "todo-ui") == DesignTokens.Colors.Lane.root)
        #expect(
            store.color(of: "b94-codex-settings", in: "todo-ui")
                == DesignTokens.Colors.Lane.violet)
        #expect(store.color(of: "nope", in: "todo-ui") == nil)
        #expect(store.color(of: "main", in: "other") == nil)
        #expect(
            store.color(of: .worktree(name: "x", folder: "/elsewhere/icons"), in: "todo-ui")
                == LaneColors.color(5))
        #expect(store.color(of: .projectFolder(branch: nil, folder: "/r"), in: "todo-ui") == nil)
        #expect(store.color(of: .projectFolder(branch: "wip", folder: "/r"), in: "other") == nil)
        #expect(store.lanes("todo-ui")?.rows.count == 7)

        await store.show(nil)
        #expect(store.shown == nil)
        #expect(api.calls == ["repoBranchMap todo-ui"])
    }

    /// B96: a failed load keeps the map it had; the next event or connect reads it again.
    @Test func aFailedLoadKeepsTheMap() async {
        await store.show("todo-ui")
        api.fail("repoBranchMap")
        await store.load("todo-ui")
        #expect(store.map("todo-ui")?.branches.count == 7)
    }

    /// B96: a branches event reads the map of a loaded or shown project again, and of no
    /// other; the repo name is in the event.
    @Test func branchEventsRefreshLoadedMaps() async {
        await store.show("todo-ui")
        api.set {
            $0.branchMaps["todo-ui"] = BranchMapFixture.map([
                BranchMapFixture.branch("main", parent: nil)
            ])
        }
        store.apply(
            Fixture.event(
                EventType.repoBranchesChanged, #"{"name": "todo-ui"}"#, id: nil, session: nil))
        store.apply(
            Fixture.event(
                EventType.repoBranchesChanged, #"{"name": "nest"}"#, id: nil, session: nil))
        store.apply(Fixture.event(EventType.sessionDelta, #"{"text": "x"}"#))
        await store.refreshing?.value
        #expect(store.map("todo-ui")?.branches.count == 1)
        #expect(api.calls == ["repoBranchMap todo-ui", "repoBranchMap todo-ui"])
    }

    /// B96: on reconnect every loaded map is read again.
    @Test func reloadReadsEveryLoadedMap() async {
        api.set { $0.branchMaps["nest"] = BranchMapFixture.map([]) }
        await store.load("nest")
        await store.show("todo-ui")
        await store.reload()
        #expect(
            api.calls.sorted() == [
                "repoBranchMap todo-ui", "repoBranchMap todo-ui", "repoBranchMap nest",
                "repoBranchMap nest",
            ])
    }

    /// B131 regression: a default branch changed in Settings announces no branch event, and
    /// a branch made in a terminal may have none either, so a removed main stayed on screen.
    /// Opening the map reads it again; closing it reads nothing.
    @Test func openingTheMapReadsItAgain() async {
        await store.show("todo-ui")
        api.set {
            $0.branchMaps["todo-ui"] = BranchMapFixture.map([
                BranchMapFixture.branch("wip", parent: nil)
            ])
        }
        store.toggle("todo-ui")
        await store.refreshing?.value
        #expect(store.map("todo-ui")?.top?.name == "wip")
        #expect(store.lanes("todo-ui")?.top?.id == "wip")
        #expect(store.tree("todo-ui")?.top?.id == "wip")
        #expect(store.picker("todo-ui")?.top?.id == "wip")
        #expect(api.calls == ["repoBranchMap todo-ui", "repoBranchMap todo-ui"])

        store.toggle("todo-ui")
        await store.refreshing?.value
        #expect(api.calls.count == 2)
    }

    /// B131: reload reads the map at once, fetches, then reads it again; each reason shows
    /// once, naming its remotes.
    @Test func reloadReadsFetchesAndReadsAgain() async throws {
        await store.show("todo-ui")
        api.set {
            $0.remotesRefresh = RemotesRefresh(remotes: [
                .init(name: "origin"), .init(name: "a", error: "refused"),
                .init(name: "b", error: "refused"), .init(name: "c", error: "gone"),
            ])
        }
        api.set { $0.calls = [] }
        try await store.refreshRemotes("todo-ui")
        #expect(
            api.calls == [
                "repoBranchMap todo-ui", "refreshRemotes todo-ui", "repoBranchMap todo-ui",
            ])
        let reload = store.reload(of: "todo-ui")
        #expect(!reload.running)
        #expect(reload.failures.map(\.remotes) == ["a, b", "c"])
        #expect(reload.failures.map(\.reason) == ["refused", "gone"])
        store.dismissFailures(of: "todo-ui")
        #expect(store.reload(of: "todo-ui").failures.isEmpty)
    }

    /// B131: a reload that cannot reach the daemon ends, and leaves the map usable.
    @Test func aFailedReloadEndsAndKeepsTheMap() async {
        await store.show("todo-ui")
        api.fail("refreshRemotes")
        await #expect(throws: (any Error).self) { try await store.refreshRemotes("todo-ui") }
        #expect(!store.reload(of: "todo-ui").running)
        #expect(store.map("todo-ui") != nil)
    }

    /// B131: a remote row makes the local branch, and the map is read with it.
    @Test func trackingARemoteBranchReadsTheMap() async throws {
        await store.show("todo-ui")
        api.set { $0.calls = [] }
        let made = try await store.track(
            BranchMap.RemoteBranch(remote: "origin", name: "feat/x"), in: "todo-ui")
        #expect(made == "feat/x")
        #expect(
            api.calls == ["trackRemoteBranch todo-ui origin feat/x", "repoBranchMap todo-ui"])
    }

    private final class Clock {
        var now = Date(timeIntervalSince1970: 0)
    }

    /// The pick a remote row makes, in a store on `clock`.
    private func track(_ store: BranchMapStore) async throws {
        try await store.holdPicks("todo-ui") {
            _ = try await store.track(
                BranchMap.RemoteBranch(remote: "origin", name: "feat/x"), in: "todo-ui")
        }
    }

    private func posts() -> Int {
        api.calls.filter { $0.hasPrefix("trackRemoteBranch") }.count
    }

    /// B131: a double click on a remote row made the row under the pointer's branch too. The
    /// second click finds picks held, while the pick runs and just after; a later one works.
    @Test func aPickHoldsTheNextUntilItHasEndedAndAPause() async throws {
        let clock = Clock()
        let store = BranchMapStore(api: api, store: MemoryStore(), now: { clock.now })
        let gate = AsyncStream<Void>.makeStream()
        api.set { $0.gates["trackRemoteBranch"] = gate.stream }
        #expect(!store.picksHeld("todo-ui"))
        let first = Task { try await track(store) }
        await api.reached("trackRemoteBranch")
        #expect(store.picksHeld("todo-ui"))
        #expect(!store.picksHeld("nest"))

        // However long it runs.
        clock.now.addTimeInterval(60)
        #expect(store.picksHeld("todo-ui"))
        try await track(store)

        gate.continuation.finish()
        try await first.value
        #expect(posts() == 1)

        clock.now.addTimeInterval(BranchMapStore.pickPause - 0.05)
        #expect(store.picksHeld("todo-ui"))
        try await track(store)
        #expect(posts() == 1)

        clock.now.addTimeInterval(0.1)
        #expect(!store.picksHeld("todo-ui"))
        try await track(store)
        #expect(posts() == 2)
    }

    /// B131: a failed pick ends the hold the same way, and its failure still reaches the user.
    @Test func aFailedPickEndsTheHold() async throws {
        let clock = Clock()
        let store = BranchMapStore(api: api, store: MemoryStore(), now: { clock.now })
        api.fail("trackRemoteBranch")
        await #expect(throws: (any Error).self) { try await track(store) }
        #expect(store.picksHeld("todo-ui"))
        clock.now.addTimeInterval(BranchMapStore.pickPause + 0.05)
        #expect(!store.picksHeld("todo-ui"))
    }

    /// A run of the app, on the same storage.
    private func restarted(_ preferences: MemoryStore) async -> BranchMapStore {
        let store = BranchMapStore(api: api, store: preferences)
        await store.show("todo-ui")
        return store
    }

    /// B131: every colour stays across a restart, whatever appears on the map: a branch sorted
    /// before the others takes a free colour and moves nobody.
    @Test func coloursStayAcrossARestart() async {
        let preferences = MemoryStore()
        let names = ["b94-codex-settings", "lazy-scroll", "wip", "pixie-search", "wip-icons"]
        let first = await restarted(preferences)
        let colours = names.map { first.color(of: $0, in: "todo-ui") }

        var map = BranchMapFixture.map
        map.branches.insert(
            BranchMapFixture.branch("aa-new", parent: "main", worktree: "/aa"), at: 1)
        api.set { $0.branchMaps["todo-ui"] = map }
        let second = await restarted(preferences)
        #expect(names.map { second.color(of: $0, in: "todo-ui") } == colours)
        #expect(second.color(of: "aa-new", in: "todo-ui") == LaneColors.color(7))
        #expect(second.color(of: "main", in: "todo-ui") == DesignTokens.Colors.Lane.root)
    }

    /// B131: a plain branch given a colour keeps it too, and a deleted branch frees its own.
    @Test func aPlainBranchKeepsItsColourAndADeletedOneFreesIt() async {
        let preferences = MemoryStore()
        let main = BranchMapFixture.branch("main", parent: nil)
        let kept = BranchMapFixture.branch("kept", parent: "main", worktree: "/k")
        let plain = BranchMapFixture.branch("plain", parent: "main")
        api.set { $0.branchMaps["todo-ui"] = BranchMapFixture.map([main, kept, plain]) }
        let first = await restarted(preferences)
        let colour = first.color(of: "plain", in: "todo-ui")
        #expect(colour == LaneColors.color(2))
        #expect(await restarted(preferences).color(of: "plain", in: "todo-ui") == colour)

        let new = BranchMapFixture.branch("new", parent: "main", worktree: "/n")
        api.set { $0.branchMaps["todo-ui"] = BranchMapFixture.map([main, plain, new]) }
        #expect(await restarted(preferences).color(of: "new", in: "todo-ui") == LaneColors.color(1))
    }

    /// B131: bad storage only forgets the colours, and a number off the palette is dropped.
    @Test func badStorageForgetsTheColours() async {
        let preferences = MemoryStore()
        let key = BranchMapStore.colorsKey("todo-ui")
        preferences.set("not json", forKey: key)
        #expect(
            await restarted(preferences).color(of: "lazy-scroll", in: "todo-ui")
                == LaneColors.color(2))
        preferences.set(#"{"lazy-scroll": 99, "wip": 0}"#, forKey: key)
        #expect(
            await restarted(preferences).color(of: "lazy-scroll", in: "todo-ui")
                == LaneColors.color(2))
    }

    /// B96: the panel opens and closes per project.
    @Test func openStateIsPerProject() async {
        await store.show("todo-ui")
        #expect(!store.isOpen("todo-ui"))
        store.toggle("todo-ui")
        #expect(store.isOpen("todo-ui"))
        #expect(!store.isOpen("nest"))
        store.toggle("todo-ui")
        #expect(!store.isOpen("todo-ui"))
    }

    /// B96: the store links the map's rows to the project's chats.
    @Test func linksChats() async {
        var session = Fixture.session("s", state: .running)
        session.worktreePath = "/r/.claude/worktrees/nest-pixie"
        let none = store.chats(in: "todo-ui", sessions: [session], claudeChats: [], repo: nil) {
            _ in .running
        }
        #expect(none.isEmpty)
        await store.show("todo-ui")
        let found = store.chats(in: "todo-ui", sessions: [session], claudeChats: [], repo: nil) {
            _ in .running
        }
        #expect(found["pixie-search"] == .running)
    }
}
