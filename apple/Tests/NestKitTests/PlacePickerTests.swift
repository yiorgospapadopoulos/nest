import Foundation
import Testing

@testable import NestKit

/// B131: the "Work on" picker of a new chat (P1), built from the project's branch map: the
/// top row pinned, every other branch in its lane, each offering a new worktree.
@Suite struct PlacePickerTests {
    /// B131: every branch has one row, under the pinned top row, with the same indent cap as
    /// the small map.
    @Test func everyBranchHasOneRowUnderThePinnedTop() {
        let picker = PlacePicker(map: BranchMapFixture.map)
        #expect(picker.top?.id == "main")
        #expect(
            picker.rows.map(\.id) == [
                "b94-codex-settings", "lazy-scroll", "wip", "pixie-search", "wip-icons",
                "wip-limits",
            ])
        #expect(PlacePicker.visibleRows == 8)
        #expect(PlacePickerRow.height == 30)

        let deep = PlacePicker(
            map: BranchMapFixture.map([
                BranchMapFixture.branch("main", parent: nil),
                BranchMapFixture.branch("a", parent: "main"),
                BranchMapFixture.branch("b", parent: "a"),
                BranchMapFixture.branch("c", parent: "b"),
                BranchMapFixture.branch("d", parent: "c"),
            ]))
        #expect(deep.rows.map(\.lane.depth) == [1, 2, 3, 3])
        #expect(deep.rows.last?.lane.fromParent == "c")
    }

    /// B131: "New worktree from" is offered on every branch and worktree, the folder's and
    /// the top row's too, and not on a branch only a remote has.
    @Test func everyBranchAndWorktreeOffersANewWorktree() {
        let picker = PlacePicker(map: BranchMapFixture.map)
        for row in picker.rows + [picker.top].compactMap({ $0 }) {
            #expect(row.newWorktree == .newWorktree(from: row.id))
        }
        let remote = PlacePicker(
            map: BranchMapFixture.map([
                BranchMapFixture.branch("main", parent: nil, remote: "origin")
            ]))
        #expect(remote.top?.newWorktree == nil)
    }

    /// B96: a row's click works in place on the folder's branch, in a worktree's folder, or
    /// on any other branch itself.
    @Test func aRowWorksWhereItIs() throws {
        let map = BranchMapFixture.map
        #expect(try #require(map.branch("wip")).newChatChoice == .inPlace)
        #expect(
            try #require(map.branch("wip-icons")).newChatChoice
                == .worktree(path: "/elsewhere/icons", branch: "wip-icons"))
        #expect(try #require(map.branch("main")).newChatChoice == .onBranch("main"))
    }

    /// B96: each row tells VoiceOver what choosing it does.
    @Test func rowsHaveAccessibilityLabels() throws {
        let picker = PlacePicker(map: BranchMapFixture.map)
        #expect(picker.top?.accessibilityLabel == "Work on main, branch")
        let wip = try #require(picker.rows.first { $0.id == "wip" })
        #expect(wip.accessibilityLabel == "Work on wip in the project folder")
        let icons = try #require(picker.rows.first { $0.id == "wip-icons" })
        #expect(icons.accessibilityLabel == "Work in worktree wip-icons")
    }

    /// B131: a map row says its name, "here", its remote, its note and its chat's state.
    @Test func mapRowsSayWhatTheyAre() throws {
        let map = BranchMapFixture.map([
            BranchMapFixture.branch("main", parent: nil, behind: 2, remote: "origin"),
            BranchMapFixture.branch("wip", parent: "main", here: true, behind: 3),
        ])
        let rows = BranchLanes(map: map).rows
        #expect(rows[0].accessibilityLabel(status: nil) == "main, only on origin")
        #expect(
            rows[1].accessibilityLabel(status: .running) == "wip, here, 3 behind, chat running")
    }
}

/// B131: the table in the plan's answer 2: where a new chat starts with no pick of its own.
@Suite struct SelectedPlaceChoiceTests {
    let branch = SelectedPlace(branch: "wip")
    let worktree = SelectedPlace(branch: "feat", worktreePath: "/r/w")

    @Test func nothingSelectedFollowsTheMode() {
        #expect(NewChatChoice(selected: nil, mode: .inPlace) == .inPlace)
        #expect(NewChatChoice(selected: nil, mode: nil) == .inPlace)
        #expect(NewChatChoice(selected: nil, mode: .worktree) == .newWorktree(from: nil))
    }

    @Test func aSelectedBranchIsWorkedOnOrStartsAWorktree() {
        #expect(NewChatChoice(selected: branch, mode: .inPlace) == .onBranch("wip"))
        #expect(NewChatChoice(selected: branch, mode: nil) == .onBranch("wip"))
        #expect(NewChatChoice(selected: branch, mode: .worktree) == .newWorktree(from: "wip"))
    }

    @Test func aSelectedWorktreeIsJoinedInEitherMode() {
        let joined = NewChatChoice.worktree(path: "/r/w", branch: "feat")
        #expect(NewChatChoice(selected: worktree, mode: .inPlace) == joined)
        #expect(NewChatChoice(selected: worktree, mode: .worktree) == joined)
    }

    /// Autopilot counts as worktree mode; a pick for this one chat wins over all of it.
    @Test func autopilotCountsAsWorktreeAndAPickWins() {
        let on = AutopilotChoice(on: true)
        #expect(on.place(chosen: nil, selected: nil, mode: .inPlace) == .newWorktree(from: nil))
        #expect(
            on.place(chosen: nil, selected: branch, mode: .inPlace) == .newWorktree(from: "wip"))
        #expect(
            on.place(chosen: nil, selected: worktree, mode: .inPlace)
                == .worktree(path: "/r/w", branch: "feat"))
        #expect(
            on.place(chosen: .onBranch("x"), selected: branch, mode: .inPlace) == .onBranch("x"))
        #expect(
            AutopilotChoice().place(chosen: nil, selected: branch, mode: .inPlace)
                == .onBranch("wip"))
    }

    /// The request says what the table says. A selected branch is asked for by name even
    /// when it is the folder's, so a folder moved in a terminal is not worked on.
    @Test func theRequestFollowsTheChoice() {
        var repo = Fixture.repos[0]
        repo.currentBranch = "wip"

        let onBranch = NewChatPlace(.onBranch("wip"), typed: "", repo: repo)
        #expect(onBranch.onBranch == "wip")
        #expect(onBranch.mode == nil)

        let fromBranch = NewChatPlace(.newWorktree(from: "feat"), typed: "", repo: repo)
        #expect(fromBranch.mode == .worktree)
        #expect(fromBranch.base == "feat")

        let fromFolder = NewChatPlace(.newWorktree(from: nil), typed: "", repo: repo)
        #expect(fromFolder.base == "wip")

        let joined = NewChatPlace(.worktree(path: "/r/w", branch: "feat"), typed: "", repo: repo)
        #expect(joined.worktreePath == "/r/w")
        #expect(joined.mode == .worktree)
    }

    /// For display only, the folder's own branch shows as the folder.
    @Test func theFoldersBranchShowsAsTheFolderButIsNotSentSo() throws {
        var repo = Fixture.repos[0]
        repo.currentBranch = "wip"
        #expect(NewChatChoice.onBranch("wip").resolved(repo) == .inPlace)
        #expect(NewChatChoice.onBranch("main").resolved(repo) == .onBranch("main"))
        #expect(NewChatChoice.onBranch("wip").marks(try wipRow(), repo: repo))
    }

    private func wipRow() throws -> BranchMap.Branch {
        try #require(BranchMapFixture.map.branch("wip"))
    }

    /// The picker marks the row the choice starts from.
    @Test func thePickerMarksWhereTheChoiceStarts() throws {
        let map = BranchMapFixture.map
        var repo = Fixture.repos[0]
        repo.currentBranch = "wip"
        let main = try #require(map.branch("main"))
        let icons = try #require(map.branch("wip-icons"))
        #expect(NewChatChoice.inPlace.marks(try wipRow(), repo: repo))
        #expect(!NewChatChoice.inPlace.marks(main, repo: repo))
        #expect(NewChatChoice.newWorktree(from: nil).marks(try wipRow(), repo: repo))
        #expect(NewChatChoice.newWorktree(from: "main").marks(main, repo: repo))
        #expect(NewChatChoice.onBranch("main").marks(main, repo: repo))
        #expect(
            NewChatChoice.worktree(path: "/elsewhere/icons", branch: "x").marks(icons, repo: repo))
    }
}

/// B131: selecting moves nothing and is told when it is gone.
@MainActor
@Suite struct SelectedPlaceStoreTests {
    let api = FakeAPI()
    let app: AppStore

    init() async throws {
        api.set { $0.repos = Fixture.repos }
        app = AppStore(api: api, store: MemoryStore())
        try await app.loadRepos()
    }

    @Test func aPickSendsThePUTAndNothingElse() async throws {
        let before = try #require(app.repo("todo-ui"))
        api.set { $0.calls = [] }
        try await app.selectPlace("todo-ui", SelectPlaceRequest(branch: "wip"))
        #expect(api.calls == [#"selectPlace todo-ui {"branch":"wip"}"#])
        let after = try #require(app.repo("todo-ui"))
        #expect(after.selectedPlace == SelectedPlace(branch: "wip"))
        #expect(after.startBranch(map: nil) == "wip")
        // What open chats read does not move.
        #expect(after.currentBranch == before.currentBranch)
        #expect(after.badge == before.badge)
    }

    /// Reports the project's selection gone, as the daemon does until it is cleared.
    private func daemonReportsGone(_ name: String) {
        api.set { state in
            let index = state.repos.firstIndex { $0.name == "todo-ui" }!
            state.repos[index].selectedPlace = nil
            state.repos[index].selectedPlaceGone = name
        }
    }

    private func clears() -> [String] {
        api.calls.filter { $0 == "clearGonePlace todo-ui" }
    }

    /// The first load of a run tells it too: a selection can go while the app is shut.
    @Test func aPlaceGoneAtTheFirstLoadGivesOneNoticeAndOneClear() async throws {
        let fresh = AppStore(api: api, store: MemoryStore())
        var gone: [String] = []
        fresh.onPlaceGone = { gone.append($0) }
        daemonReportsGone("wip")
        try await fresh.loadRepos()
        #expect(gone == ["wip"])
        #expect(fresh.repo("todo-ui")?.selectedPlace == nil)
        await api.untilCalls { $0.contains("clearGonePlace todo-ui") }
        #expect(clears().count == 1)
        // A PUT of nothing could wipe a click made that moment in another client.
        #expect(!api.calls.contains { $0.hasPrefix("selectPlace") })
    }

    /// A list read before the clear landed still says gone, and tells nothing twice.
    @Test func aListCrossingTheClearTellsNothingTwice() async throws {
        var gone: [String] = []
        app.onPlaceGone = { gone.append($0) }
        daemonReportsGone("wip")
        try await app.loadRepos()
        await api.untilCalls { $0.contains("clearGonePlace todo-ui") }
        daemonReportsGone("wip")
        try await app.loadRepos()
        #expect(gone == ["wip"])
        #expect(clears().count == 1)
    }

    /// The name is told again once the project has had a selection since.
    @Test func aNewSelectionThatGoesIsToldAgain() async throws {
        var gone: [String] = []
        app.onPlaceGone = { gone.append($0) }
        daemonReportsGone("wip")
        try await app.loadRepos()
        await api.untilCalls { $0.contains("clearGonePlace todo-ui") }
        try await app.selectPlace("todo-ui", SelectPlaceRequest(branch: "wip"))
        daemonReportsGone("wip")
        try await app.loadRepos()
        #expect(gone == ["wip", "wip"])
        await api.untilCalls { calls in calls.filter { $0 == "clearGonePlace todo-ui" }.count == 2 }
    }

    /// The clear is quiet: a failure shows nothing and is not tried again in this run.
    @Test func aFailedClearIsNotRetried() async throws {
        var gone: [String] = []
        app.onPlaceGone = { gone.append($0) }
        api.fail("clearGonePlace")
        daemonReportsGone("wip")
        try await app.loadRepos()
        await api.untilCalls { $0.contains("clearGonePlace todo-ui") }
        try await app.loadRepos()
        #expect(gone == ["wip"])
        #expect(clears().count == 1)
    }

    /// Going back to the folder from the detached row is a choice, so nothing is told.
    @Test func clearingBySelectingNothingTellsNothing() async throws {
        var gone: [String] = []
        app.onPlaceGone = { gone.append($0) }
        try await app.selectPlace("todo-ui", SelectPlaceRequest(branch: "wip"))
        try await app.selectPlace("todo-ui", SelectPlaceRequest())
        try await app.loadRepos()
        #expect(gone.isEmpty)
        #expect(app.repo("todo-ui")?.selectedPlace == nil)
    }

    /// An older daemon sends no gone name.
    @Test func anOlderDaemonsRepoHasNoGoneName() {
        #expect(Fixture.repos.allSatisfy { $0.selectedPlaceGone == nil })
    }

    /// The header says where new chats start: the selection, the folder's branch, else
    /// "detached" only when the map says so: no map yet, or a branch with no commits, keeps
    /// the default branch's name.
    @Test func theHeaderNamesWhereNewChatsStart() {
        var repo = Fixture.repos[0]
        repo.currentBranch = "main"
        #expect(repo.startBranch(map: nil) == "main")
        repo.selectedPlace = SelectedPlace(branch: "wip")
        #expect(repo.startBranch(map: nil) == "wip")

        repo.selectedPlace = nil
        repo.currentBranch = nil
        repo.defaultBranch = "main"
        var map = BranchMapFixture.map
        map.currentBranch = nil
        map.detached = true
        #expect(repo.startBranch(map: map) == "detached")
        map.detached = false
        #expect(repo.startBranch(map: map) == "main")
        #expect(repo.startBranch(map: nil) == "main")
        repo.selectedPlace = SelectedPlace(branch: "wip")
        map.detached = true
        #expect(repo.startBranch(map: map) == "wip")
        #expect(Fixture.plainRepo.startBranch(map: nil) == nil)
    }

    /// A project's own default decides the mode before the shared one; a plain folder works
    /// in place.
    @Test func theProjectsDefaultDecidesTheMode() {
        var repo = Fixture.repos[0]
        repo.worktree.isDefault = true
        #expect(repo.mode(for: .inPlace) == .worktree)
        repo.worktree.isDefault = false
        #expect(repo.mode(for: .worktree) == .inPlace)
        repo.worktree.isDefault = nil
        #expect(repo.mode(for: .worktree) == .worktree)
        #expect(Fixture.plainRepo.mode(for: .worktree) == .inPlace)
    }
}

@MainActor
@Suite struct PlacePickerStoreTests {
    /// B96: the store builds a loaded project's picker; none before its map loads.
    @Test func theStoreBuildsThePicker() async {
        let api = FakeAPI()
        api.set { $0.branchMaps = ["todo-ui": BranchMapFixture.map] }
        let store = BranchMapStore(api: api, store: MemoryStore())
        #expect(store.picker("todo-ui") == nil)
        await store.show("todo-ui")
        #expect(store.picker("todo-ui")?.rows.count == 6)
    }
}
