import Foundation
import Testing

@testable import NestKit

/// B55: where each chat works, as the sidebar and the pane header say it, the project
/// folder's current branch, and a new chat's choice, base and branch name.
@Suite struct ChatPlaceTests {
    let repo = Fixture.repos[0]

    func worktreeSession(branch: String?, path: String?) -> Session {
        var session = Fixture.session()
        session.mode = .worktree
        session.branch = branch
        session.worktreePath = path
        return session
    }

    func inPlaceSession(cwd: String?) -> Session {
        var session = Fixture.session()
        session.mode = .inPlace
        session.branch = nil
        session.worktreePath = nil
        session.cwd = cwd
        return session
    }

    // MARK: The project folder's branch

    @Test func aRepoReadsTheBranchCheckedOutNow() {
        let repo = Fixture.decode(
            Repo.self,
            json: """
                {"name": "cv-page", "path": "/p", "default_branch": "main",
                 "current_branch": "feature/nav", "worktree": {"default": null, "link": [],
                 "setup": [], "setup_timeout_seconds": 900}}
                """)
        #expect(repo.currentBranch == "feature/nav")
        #expect(repo.checkoutBranch == "feature/nav")
        #expect(repo.badge == .branch("feature/nav"))
        #expect(Fixture.json(repo).contains(#""current_branch":"feature/nav""#))
    }

    @Test func withoutACurrentBranchTheDefaultBranchStandsIn() {
        // Older daemons send no current branch; a detached HEAD sends null.
        #expect(repo.currentBranch == nil)
        #expect(repo.checkoutBranch == "main")
        #expect(repo.badge == .branch("main"))
        #expect(Fixture.plainRepo.checkoutBranch == nil)
    }

    // MARK: Nest chats

    @Test func aWorktreeChatIsNamedByItsBranch() {
        let session = worktreeSession(branch: "agent/nav", path: "/wt/nav-3f2a")
        let place = ChatPlace.of(session, repo: repo)
        #expect(place == .worktree(name: "agent/nav", folder: "/wt/nav-3f2a"))
        #expect(place?.name == "agent/nav")
        #expect(place?.isWorktree == true)
        #expect(place?.accessibilityLabel == "worktree agent/nav")
        #expect(place?.help == "Worktree agent/nav in /wt/nav-3f2a")
    }

    @Test func aWorktreeWithoutABranchIsNamedByItsFolder() {
        let session = worktreeSession(branch: nil, path: "/wt/nav-3f2a")
        #expect(
            ChatPlace.of(session, repo: repo) == .worktree(name: "nav-3f2a", folder: "/wt/nav-3f2a")
        )
    }

    @Test func aWorktreeStillBeingMadeHasNoFolderYet() {
        let place = ChatPlace.of(worktreeSession(branch: nil, path: nil), repo: repo)
        #expect(place == .worktree(name: "New worktree", folder: nil))
        #expect(place?.help == "Worktree New worktree")
    }

    @Test func anInPlaceChatIsNamedByTheFoldersCurrentBranch() {
        var current = repo
        current.currentBranch = "dev"
        let place = ChatPlace.of(inPlaceSession(cwd: "/repo/cv-page"), repo: current)
        #expect(place == .projectFolder(branch: "dev", folder: "/repo/cv-page"))
        #expect(place?.name == "dev")
        #expect(place?.isWorktree == false)
        #expect(place?.accessibilityLabel == "on dev")
        #expect(place?.help == "On dev in /repo/cv-page")
    }

    @Test func anInPlaceChatOnAnUnknownBranchSaysThisFolder() {
        // A detached HEAD (or an older daemon) gives no current branch; the default branch
        // is not named, since the folder may not be on it.
        let place = ChatPlace.of(inPlaceSession(cwd: "/repo/cv-page"), repo: repo)
        #expect(place == .projectFolder(branch: nil, folder: "/repo/cv-page"))
        #expect(place?.name == "This folder")
        #expect(place?.accessibilityLabel == "in this folder")
        #expect(place?.help == "In /repo/cv-page")
    }

    @Test func anInPlaceChatWithoutItsFolderUsesTheProjects() {
        let place = ChatPlace.of(inPlaceSession(cwd: nil), repo: repo)
        #expect(place == .projectFolder(branch: nil, folder: repo.path))
        #expect(ChatPlace.of(inPlaceSession(cwd: nil), repo: nil) == nil)
    }

    @Test func aPlainFolderHasNoBranchToName() {
        #expect(ChatPlace.of(inPlaceSession(cwd: "/notes"), repo: Fixture.plainRepo) == nil)
        let chat = Fixture.claudeChat("cc1")
        #expect(ChatPlace.of(chat, repo: Fixture.plainRepo) == nil)
    }

    @Test func aChatOfAnUnknownProjectStillSaysWhereItWorks() {
        let session = worktreeSession(branch: "agent/x", path: "/wt/x")
        #expect(ChatPlace.of(session, repo: nil) == .worktree(name: "agent/x", folder: "/wt/x"))
        #expect(
            ChatPlace.of(inPlaceSession(cwd: "/p"), repo: nil)
                == .projectFolder(branch: nil, folder: "/p"))
    }

    // MARK: Claude Code chats

    @Test func aClaudeCodeChatInAWorktreeShowsIt() {
        var chat = Fixture.claudeChat("cc1")
        chat.worktree = "pipeline"
        chat.cwd = "/repo/cv-page/.claude/worktrees/pipeline"
        let place = ChatPlace.of(chat, repo: repo)
        #expect(
            place == .worktree(name: "pipeline", folder: "/repo/cv-page/.claude/worktrees/pipeline")
        )
        #expect(place?.name == "pipeline")
    }

    @Test func aClaudeCodeChatInTheFolderIsNamedByItsBranch() {
        var current = repo
        current.currentBranch = "main"
        let chat = Fixture.claudeChat("cc1")
        let place = ChatPlace.of(chat, repo: current)
        #expect(place == .projectFolder(branch: "main", folder: "/repo/cv-page"))
        #expect(place?.name == "main")
        #expect(
            ChatPlace.of(chat, repo: repo) == .projectFolder(branch: nil, folder: "/repo/cv-page"))
    }

    // MARK: A new chat's place

    @Test func anInPlaceChatSendsNoBaseOrBranch() {
        let place = NewChatPlace(NewChatChoice(mode: .inPlace), typed: "x", repo: repo)
        #expect(place.mode == .inPlace)
        #expect(place.base == nil)
        #expect(place.branch == nil)
    }

    @Test func aNewWorktreeStartsFromTheFoldersCurrentBranch() {
        var current = repo
        current.currentBranch = "feature/nav"
        let place = NewChatPlace(NewChatChoice(mode: .worktree), typed: "  ", repo: current)
        #expect(place.mode == .worktree)
        #expect(place.base == "feature/nav")
        #expect(place.branch == nil)
    }

    @Test func withoutACurrentBranchANewWorktreeStartsFromTheDefault() {
        let place = NewChatPlace(
            NewChatChoice(mode: .worktree), typed: "  fix/login \n", repo: repo)
        #expect(place.base == "main")
        #expect(place.branch == "fix/login")
    }

    @Test func noModeChosenWorksInPlace() {
        // In place is the default (D038): a draft with no mode shows and sends it.
        let place = NewChatPlace(NewChatChoice(mode: nil), typed: "fix/a", repo: repo)
        #expect(place.mode == .inPlace)
        #expect(place.base == nil)
        #expect(place.branch == nil)
        #expect(NewChatPlace(NewChatChoice(mode: nil), typed: "", repo: nil).mode == .inPlace)
    }

    @Test func aPlainFolderAlwaysWorksInPlace() {
        let place = NewChatPlace(
            NewChatChoice(mode: .worktree), typed: "y", repo: Fixture.plainRepo)
        #expect(place.mode == .inPlace)
        #expect(place.base == nil)
        #expect(place.branch == nil)
    }

    @Test func withoutTheProjectNoBaseIsGuessed() {
        let place = NewChatPlace(NewChatChoice(mode: .worktree), typed: "", repo: nil)
        #expect(place.mode == .worktree)
        #expect(place.base == nil)
    }

    @Test func theSelectorNamesTheFoldersCurrentBranch() {
        var current = repo
        current.currentBranch = "dev"
        #expect(NewChatPlace.inPlaceTitle(current) == "Work on dev")
        #expect(NewChatPlace.inPlaceDetail(current) == "Edits the project folder, on dev")
        #expect(NewChatPlace.inPlaceTitle(repo) == "Work in this folder")
        #expect(NewChatPlace.inPlaceDetail(repo) == "Edits the project folder")
        #expect(NewChatPlace.inPlaceTitle(nil) == "Work in this folder")
        #expect(NewChatPlace.worktreeTitle == "New worktree")
        #expect(
            NewChatPlace.worktreeDetail == "A separate copy of the project on its own new branch")
    }

    @Test func theRequestCarriesBaseAndBranchOnlyWhenSet() {
        var current = repo
        current.currentBranch = "dev"
        let place = NewChatPlace(NewChatChoice(mode: .worktree), typed: "fix/a", repo: current)
        let request = CreateSessionRequest(
            repo: "cv-page", prompt: "Go", mode: place.mode, base: place.base,
            branch: place.branch)
        let json = Fixture.json(request)
        #expect(json.contains(#""base":"dev""#))
        #expect(json.contains(#""branch":"fix/a""#))
        let plain = Fixture.json(CreateSessionRequest(repo: "cv-page", prompt: "Go"))
        #expect(!plain.contains("base"))
        #expect(!plain.contains("branch"))
    }

    // MARK: B96: a new worktree from any branch, or an existing worktree

    /// B96: a choice reads back the mode the defaults and the menus set.
    @Test func aChoiceHasAMode() {
        #expect(NewChatChoice(mode: .worktree) == .newWorktree(from: nil))
        #expect(NewChatChoice(mode: .inPlace) == .inPlace)
        #expect(NewChatChoice(mode: nil) == .inPlace)
        #expect(NewChatChoice.inPlace.mode == .inPlace)
        #expect(NewChatChoice.newWorktree(from: "main").mode == .worktree)
        #expect(NewChatChoice.worktree(path: "/wt/a", branch: "a").mode == .worktree)
        // The daemon decides: in place on the folder's branch, else a worktree on it.
        #expect(NewChatChoice.onBranch("main").mode == nil)
    }

    /// B96: the picker marks a new worktree with no branch chosen as from the folder's.
    @Test func aChoiceResolvesTheFoldersBranch() {
        var current = repo
        current.currentBranch = "wip"
        #expect(NewChatChoice.newWorktree(from: nil).resolved(current) == .newWorktree(from: "wip"))
        #expect(NewChatChoice.newWorktree(from: nil).resolved(nil) == .newWorktree(from: nil))
        #expect(NewChatChoice.newWorktree(from: "a").resolved(current) == .newWorktree(from: "a"))
        #expect(NewChatChoice.inPlace.resolved(current) == .inPlace)
        #expect(NewChatChoice.onBranch("main").resolved(current) == .onBranch("main"))
    }

    /// B96: a new worktree from a chosen branch starts there, with the typed name.
    @Test func aNewWorktreeStartsFromTheChosenBranch() {
        var current = repo
        current.currentBranch = "wip"
        let place = NewChatPlace(.newWorktree(from: "main"), typed: " fix/a ", repo: current)
        #expect(place.mode == .worktree)
        #expect(place.base == "main")
        #expect(place.branch == "fix/a")
        #expect(place.worktreePath == nil)
        #expect(place.onBranch == nil)
    }

    /// B96 round 3: working on a branch sends that branch only: no mode, base, branch name
    /// or worktree; a plain folder has no branches and works in place.
    @Test func workingOnABranchSendsTheBranchOnly() {
        let place = NewChatPlace(.onBranch("main"), typed: "ignored", repo: repo)
        #expect(place.onBranch == "main")
        #expect(place.mode == nil)
        #expect(place.base == nil)
        #expect(place.branch == nil)
        #expect(place.worktreePath == nil)
        #expect(NewChatPlace(.inPlace, typed: "", repo: repo).onBranch == nil)
        let plain = NewChatPlace(.onBranch("main"), typed: "", repo: Fixture.plainRepo)
        #expect(plain.mode == .inPlace)
        #expect(plain.onBranch == nil)
    }

    /// B96: joining a worktree sends its folder only: no base and no branch name.
    @Test func joiningAWorktreeSendsItsFolderOnly() {
        let place = NewChatPlace(
            .worktree(path: "/r/.claude/worktrees/nest-1", branch: "agent/icons"),
            typed: "ignored", repo: repo)
        #expect(place.mode == .worktree)
        #expect(place.worktreePath == "/r/.claude/worktrees/nest-1")
        #expect(place.base == nil)
        #expect(place.branch == nil)
        #expect(place.onBranch == nil)
        #expect(NewChatPlace(.inPlace, typed: "", repo: repo).worktreePath == nil)
        // A plain folder has no worktrees to join.
        let plain = NewChatPlace(
            .worktree(path: "/w", branch: "w"), typed: "", repo: Fixture.plainRepo)
        #expect(plain.mode == .inPlace)
        #expect(plain.worktreePath == nil)
    }

    /// B96: the composer button says where the chat works: "Work on" the folder's branch,
    /// "New worktree from" a branch, or the worktree's branch.
    @Test func theButtonNamesTheChoice() {
        var current = repo
        current.currentBranch = "wip"
        #expect(NewChatPlace.title(.inPlace, repo: current) == "Work on wip")
        #expect(
            NewChatPlace.title(.newWorktree(from: "main"), repo: current)
                == "New worktree from main")
        #expect(
            NewChatPlace.title(.newWorktree(from: nil), repo: current)
                == "New worktree from wip")
        #expect(NewChatPlace.title(.newWorktree(from: nil), repo: nil) == "New worktree")
        #expect(
            NewChatPlace.title(.worktree(path: "/w", branch: "agent/x"), repo: current)
                == "agent/x")
        #expect(NewChatPlace.title(.onBranch("main"), repo: current) == "Work on main")
    }

    /// B96: the request names the worktree to join as `worktree_path`, only when set.
    @Test func theRequestCarriesTheWorktreePathOnlyWhenSet() {
        let request = CreateSessionRequest(
            repo: "cv-page", prompt: "Go", mode: .worktree, worktreePath: "/wt/a")
        #expect(Fixture.json(request).contains(#""worktree_path":"/wt/a""#))
        #expect(
            !Fixture.json(CreateSessionRequest(repo: "cv-page", prompt: "Go"))
                .contains("worktree_path"))
    }

    /// B96 round 3: the request names the branch to work on as `on_branch`, only when set.
    @Test func theRequestCarriesTheBranchOnlyWhenSet() {
        let request = CreateSessionRequest(repo: "cv-page", prompt: "Go", onBranch: "main")
        #expect(Fixture.json(request).contains(#""on_branch":"main""#))
        #expect(
            !Fixture.json(CreateSessionRequest(repo: "cv-page", prompt: "Go"))
                .contains("on_branch"))
    }
}
