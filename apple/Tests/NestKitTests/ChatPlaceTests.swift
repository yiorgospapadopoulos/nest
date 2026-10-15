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
                {"name": "todo-ui", "path": "/p", "default_branch": "main",
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
        let place = ChatPlace.of(inPlaceSession(cwd: "/repo/todo-ui"), repo: current)
        #expect(place == .projectFolder(branch: "dev", folder: "/repo/todo-ui"))
        #expect(place?.name == "dev")
        #expect(place?.isWorktree == false)
        #expect(place?.accessibilityLabel == "on dev")
        #expect(place?.help == "On dev in /repo/todo-ui")
    }

    @Test func anInPlaceChatOnAnUnknownBranchSaysThisFolder() {
        // A detached HEAD (or an older daemon) gives no current branch; the default branch
        // is not named, since the folder may not be on it.
        let place = ChatPlace.of(inPlaceSession(cwd: "/repo/todo-ui"), repo: repo)
        #expect(place == .projectFolder(branch: nil, folder: "/repo/todo-ui"))
        #expect(place?.name == "This folder")
        #expect(place?.accessibilityLabel == "in this folder")
        #expect(place?.help == "In /repo/todo-ui")
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
        chat.cwd = "/repo/todo-ui/.claude/worktrees/pipeline"
        let place = ChatPlace.of(chat, repo: repo)
        #expect(
            place == .worktree(name: "pipeline", folder: "/repo/todo-ui/.claude/worktrees/pipeline")
        )
        #expect(place?.name == "pipeline")
    }

    @Test func aClaudeCodeChatInTheFolderIsNamedByItsBranch() {
        var current = repo
        current.currentBranch = "main"
        let chat = Fixture.claudeChat("cc1")
        let place = ChatPlace.of(chat, repo: current)
        #expect(place == .projectFolder(branch: "main", folder: "/repo/todo-ui"))
        #expect(place?.name == "main")
        #expect(
            ChatPlace.of(chat, repo: repo) == .projectFolder(branch: nil, folder: "/repo/todo-ui"))
    }

    // MARK: A new chat's place

    @Test func anInPlaceChatSendsNoBaseOrBranch() {
        let place = NewChatPlace(mode: .inPlace, typed: "x", repo: repo)
        #expect(place.mode == .inPlace)
        #expect(place.base == nil)
        #expect(place.branch == nil)
    }

    @Test func aNewWorktreeStartsFromTheFoldersCurrentBranch() {
        var current = repo
        current.currentBranch = "feature/nav"
        let place = NewChatPlace(mode: .worktree, typed: "  ", repo: current)
        #expect(place.mode == .worktree)
        #expect(place.base == "feature/nav")
        #expect(place.branch == nil)
    }

    @Test func withoutACurrentBranchANewWorktreeStartsFromTheDefault() {
        let place = NewChatPlace(mode: .worktree, typed: "  fix/login \n", repo: repo)
        #expect(place.base == "main")
        #expect(place.branch == "fix/login")
    }

    @Test func noModeChosenWorksInPlace() {
        // In place is the default (D038): a draft with no mode shows and sends it.
        let place = NewChatPlace(mode: nil, typed: "fix/a", repo: repo)
        #expect(place.mode == .inPlace)
        #expect(place.base == nil)
        #expect(place.branch == nil)
        #expect(NewChatPlace(mode: nil, typed: "", repo: nil).mode == .inPlace)
    }

    @Test func aPlainFolderAlwaysWorksInPlace() {
        let place = NewChatPlace(mode: .worktree, typed: "y", repo: Fixture.plainRepo)
        #expect(place.mode == .inPlace)
        #expect(place.base == nil)
        #expect(place.branch == nil)
    }

    @Test func withoutTheProjectNoBaseIsGuessed() {
        let place = NewChatPlace(mode: .worktree, typed: "", repo: nil)
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
        let place = NewChatPlace(mode: .worktree, typed: "fix/a", repo: current)
        let request = CreateSessionRequest(
            repo: "todo-ui", prompt: "Go", mode: place.mode, base: place.base,
            branch: place.branch)
        let json = Fixture.json(request)
        #expect(json.contains(#""base":"dev""#))
        #expect(json.contains(#""branch":"fix/a""#))
        let plain = Fixture.json(CreateSessionRequest(repo: "todo-ui", prompt: "Go"))
        #expect(!plain.contains("base"))
        #expect(!plain.contains("branch"))
    }
}
