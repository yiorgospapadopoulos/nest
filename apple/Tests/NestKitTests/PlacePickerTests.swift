import Foundation
import Testing

@testable import NestKit

/// B96: the "Work on" picker of a new chat (P1), built from the project's branch map: a
/// block per branch that is not a worktree, the folder's first, each with its "New
/// worktree from" row and the worktrees that come from it.
@Suite struct PlacePickerTests {
    typealias Line = PlacePickerLine

    /// B96: the folder's branch leads, selectable as in place, then the others in map
    /// order, each selectable to work on that branch itself, followed by its new worktree
    /// row and its worktrees.
    @Test func blocksStartWithTheFoldersBranch() {
        let picker = PlacePicker(map: BranchMapFixture.map)
        #expect(picker.blocks.map(\.id) == ["wip", "main"])
        let wip = picker.blocks[0].rows
        #expect(wip.map(\.id) == ["wip", "new:wip", "pixie-search", "wip-icons", "wip-limits"])
        #expect(wip.map(\.kind) == [.folder, .newWorktree, .worktree, .worktree, .worktree])
        #expect(wip.map(\.depth) == [0, 0, 1, 1, 1])
        #expect(wip.map(\.parentDepth) == [nil, nil, 0, 0, 0])
        #expect(
            wip.map(\.choice) == [
                .inPlace, .newWorktree(from: "wip"),
                .worktree(path: "/r/.claude/worktrees/nest-pixie", branch: "pixie-search"),
                .worktree(path: "/elsewhere/icons", branch: "wip-icons"),
                .worktree(path: "/r/.claude/worktrees/nest-limits", branch: "wip-limits"),
            ])
        #expect(
            wip.map(\.title) == [
                "wip", "New worktree from wip", "pixie-search", "wip-icons", "wip-limits",
            ])
        #expect(wip.map(\.detail) == ["project folder", nil, nil, nil, nil])
        // The branch's lane runs from its node through the rows to its last worktree.
        let trunk = Line(depth: 0, lane: "wip", fromTop: true, toBottom: true)
        #expect(
            wip.map(\.lines) == [
                [Line(depth: 0, lane: "wip", fromTop: false, toBottom: true)],
                [trunk], [trunk], [trunk], [],
            ])

        let main = picker.blocks[1].rows
        #expect(main.map(\.id) == ["main", "new:main", "b94-codex-settings", "lazy-scroll"])
        #expect(main[0].kind == .branch)
        #expect(main[0].choice == .onBranch("main"))
        #expect(main[0].title == "main")
        #expect(main[0].detail == "branch")
        #expect(main[1].choice == .newWorktree(from: "main"))
        #expect(picker.width == 40)
    }

    /// B96: a worktree made from another worktree's branch sits one level further in, in
    /// the same block; a branch without worktrees still offers a new one; a worktree whose
    /// parent is not shown gets a block of its own; with the folder detached, every block
    /// follows the map's order.
    @Test func nestsWorktreesAndKeepsOrphans() {
        let map = BranchMapFixture.map([
            BranchMapFixture.branch("main", parent: nil),
            BranchMapFixture.branch("a", parent: "main", worktree: "/a"),
            BranchMapFixture.branch("a2", parent: "a", worktree: "/a2"),
            BranchMapFixture.branch("b", parent: "main"),
            BranchMapFixture.branch("c", parent: "main", worktree: "/c"),
            BranchMapFixture.branch("x", parent: "missing", worktree: "/x"),
        ])
        let picker = PlacePicker(map: map)
        #expect(picker.blocks.map(\.id) == ["main", "b", "x"])

        let main = picker.blocks[0].rows
        #expect(main.map(\.id) == ["main", "new:main", "a", "a2", "c"])
        #expect(main.map(\.depth) == [0, 0, 1, 2, 1])
        #expect(main.map(\.parentDepth) == [nil, nil, 0, 1, 0])
        let trunk = Line(depth: 0, lane: "main", fromTop: true, toBottom: true)
        #expect(
            main.map(\.lines) == [
                [Line(depth: 0, lane: "main", fromTop: false, toBottom: true)],
                [trunk],
                [trunk, Line(depth: 1, lane: "a", fromTop: false, toBottom: true)],
                [trunk],
                [],
            ])

        let b = picker.blocks[1].rows
        #expect(b.map(\.id) == ["b", "new:b"])
        // The lane stops at the new worktree row when nothing follows.
        #expect(
            b.map(\.lines) == [
                [Line(depth: 0, lane: "b", fromTop: false, toBottom: true)],
                [Line(depth: 0, lane: "b", fromTop: true, toBottom: false)],
            ])

        let x = picker.blocks[2].rows
        #expect(x.map(\.id) == ["x"])
        #expect(x[0].depth == 0)
        #expect(x[0].parentDepth == nil)
        #expect(x[0].choice == .worktree(path: "/x", branch: "x"))
        #expect(picker.width == 54)
    }

    /// B96: worktrees in a loop the daemon should never send still show, once each.
    @Test func loopsShowOnce() {
        let map = BranchMapFixture.map([
            BranchMapFixture.branch("main", parent: nil),
            BranchMapFixture.branch("p", parent: "q", worktree: "/p"),
            BranchMapFixture.branch("q", parent: "p", worktree: "/q"),
        ])
        let picker = PlacePicker(map: map)
        #expect(picker.blocks.map(\.id) == ["main", "p"])
        #expect(picker.blocks[1].rows.map(\.id) == ["p", "q"])
        #expect(picker.blocks[1].rows.map(\.depth) == [0, 1])
        let empty = PlacePicker(map: BranchMapFixture.map([]))
        #expect(empty.blocks.isEmpty)
        #expect(empty.width == 26)
        #expect(empty.height == 0)
    }

    /// B96: the list is as tall as its rows and dividers, up to about eleven rows, then
    /// scrolls.
    @Test func theListStopsGrowingAtElevenRows() {
        let picker = PlacePicker(map: BranchMapFixture.map)
        #expect(PlacePickerRow.height == 30)
        #expect(PlacePicker.dividerHeight == 9)
        #expect(picker.height == 9 * 30 + 9)
        let many = BranchMapFixture.map(
            [BranchMapFixture.branch("main", parent: nil)]
                + (1...20).map {
                    BranchMapFixture.branch("w\($0)", parent: "main", worktree: "/w\($0)")
                })
        #expect(PlacePicker(map: many).height == 330)
        #expect(PlacePicker.maxHeight == 330)
    }

    /// B96: lanes sit 14 points apart from 12, as P1 draws them.
    @Test func lanesAreFourteenPointsApart() {
        #expect(PlacePickerRow.x(0) == 12)
        #expect(PlacePickerRow.x(1) == 26)
    }

    /// B96: each row tells VoiceOver what choosing it does.
    @Test func rowsHaveAccessibilityLabels() {
        let picker = PlacePicker(map: BranchMapFixture.map)
        #expect(
            picker.blocks[0].rows.map(\.accessibilityLabel) == [
                "Work on wip in the project folder", "New worktree from wip",
                "Work in worktree pixie-search", "Work in worktree wip-icons",
                "Work in worktree wip-limits",
            ])
        #expect(picker.blocks[1].rows[0].accessibilityLabel == "Work on main, branch")
    }

    /// B96 (A8): a click on a branch map row starts a chat there: in place on the folder's
    /// branch, in a worktree's folder, or on any other branch itself.
    @Test func aMapRowStartsAChatThere() throws {
        let map = BranchMapFixture.map
        #expect(try #require(map.branch("wip")).newChatChoice == .inPlace)
        #expect(
            try #require(map.branch("wip-icons")).newChatChoice
                == .worktree(path: "/elsewhere/icons", branch: "wip-icons"))
        #expect(try #require(map.branch("main")).newChatChoice == .onBranch("main"))
    }

    /// B96 (A8): each map row says where its click starts the chat, with the chat dot's
    /// state for VoiceOver.
    @Test func mapRowsSayWhereTheChatStarts() {
        let rows = BranchLanes(map: BranchMapFixture.map).rows
        let byName = Dictionary(uniqueKeysWithValues: rows.map { ($0.id, $0) })
        #expect(byName["wip"]?.newChatHelp == "New chat in the project folder")
        #expect(byName["wip-icons"]?.newChatHelp == "New chat in this worktree")
        #expect(byName["main"]?.newChatHelp == "New chat working on main")
        #expect(
            byName["wip"]?.accessibilityLabel(status: nil)
                == "wip, here, new chat in the project folder")
        #expect(
            byName["main"]?.accessibilityLabel(status: .running)
                == "main, new chat working on main, chat running")
        #expect(
            byName["wip-icons"]?.accessibilityLabel(status: .needsYou)
                == "wip-icons, new chat in this worktree, chat needs you")
        #expect(
            byName["wip-limits"]?.accessibilityLabel(status: .idle)
                == "wip-limits, new chat in this worktree, chat idle")
    }
}

@MainActor
@Suite struct PlacePickerStoreTests {
    /// B96: the store builds a loaded project's picker; none before its map loads.
    @Test func theStoreBuildsThePicker() async {
        let api = FakeAPI()
        api.set { $0.branchMaps = ["cv-page": BranchMapFixture.map] }
        let store = BranchMapStore(api: api)
        #expect(store.picker("cv-page") == nil)
        await store.show("cv-page")
        #expect(store.picker("cv-page")?.blocks.count == 2)
    }
}
