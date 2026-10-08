import Foundation
import Testing

@testable import HarnessKit

@Suite struct PlainFolderTests {
    @Test func reposWithoutTheGitKeyAreGitRepos() {
        #expect(Fixture.repos.map(\.git) == [true, true])
        let plain = Fixture.plainRepo
        #expect(!plain.git)
        #expect(plain.defaultBranch == nil)
        #expect(plain.name == "notes")
    }

    @Test func encodingKeepsTheGitFlag() throws {
        let json = Fixture.json(Fixture.plainRepo)
        #expect(json.contains(#""git":false"#))
        #expect(Fixture.decode(Repo.self, json: json) == Fixture.plainRepo)
    }

    @Test func theToolbarShowsTheBranchOrInit() {
        #expect(Fixture.repos[1].badge == .branch("develop"))
        #expect(Fixture.plainRepo.badge == .initGit)
        var unborn = Fixture.repos[0]
        unborn.defaultBranch = nil
        #expect(unborn.badge == nil)
    }

    @Test func plainFoldersAlwaysWorkInPlace() {
        let repo = Fixture.repos[0]
        #expect(repo.mode(for: .worktree) == .worktree)
        #expect(repo.mode(for: nil) == nil)
        #expect(Fixture.plainRepo.mode(for: .worktree) == .inPlace)
        #expect(Fixture.plainRepo.mode(for: nil) == .inPlace)
    }

    @Test func theInitPromptAsksForGitInitWithoutACommit() {
        #expect(
            GitInit.prompt
                == "Initialize this folder as a git repository: run git init with main as the default branch and add a .gitignore that fits what is in this folder. Do not commit; harness handles commits."
        )
    }

    @Test func registeringChangingAndRemovingARepoAreRead() {
        for type in [EventType.repoAdded, EventType.repoUpdated, EventType.repoRemoved] {
            let event = Fixture.event(type, #"{"name": "notes"}"#, session: nil)
            #expect(event.body == .reposChanged)
        }
    }
}

@MainActor
@Suite struct PlainFolderLiveSyncTests {
    let api = FakeAPI()
    let model: AppModel

    init() {
        api.set {
            $0.repos.append(Fixture.plainRepo)
            $0.sessions = [
                Fixture.session("init", repo: "notes"), Fixture.session("other", repo: "todo-ui"),
            ]
        }
        model = AppModel(api: api, events: ManualEventSource(), preferences: MemoryStore())
    }

    static let result =
        #"{"is_error": false, "subtype": "success", "duration_ms": 5, "num_turns": 1, "errors": []}"#

    @Test func aRepoUpdateListsTheReposAgain() async throws {
        await model.live.refresh()
        #expect(model.app.repo("notes")?.badge == .initGit)
        api.set {
            $0.repos[2].git = true
            $0.repos[2].defaultBranch = "main"
        }

        model.live.route(Fixture.event(EventType.repoUpdated, "{}", session: nil))
        await model.app.reloadingRepos?.value

        #expect(model.app.repo("notes")?.badge == .branch("main"))
    }

    @Test func projectsAddedOrRemovedElsewhereAppear() async throws {
        await model.live.refresh()
        var added = Fixture.repos[0]
        added.name = "added"
        api.set { $0.repos.append(added) }
        model.live.route(Fixture.event(EventType.repoAdded, #"{"name": "added"}"#, session: nil))
        await model.app.reloadingRepos?.value
        #expect(model.app.repo("added") != nil)

        api.set { $0.repos.removeAll { $0.name == "added" } }
        model.live.route(
            Fixture.event(EventType.repoRemoved, #"{"name": "added"}"#, session: nil))
        await model.app.reloadingRepos?.value
        #expect(model.app.repo("added") == nil)
    }

    @Test func aTurnInAPlainFolderChecksForGitAgain() async throws {
        await model.live.refresh()
        let before = api.calls.count { $0 == "repos" }
        guard case .result = Fixture.event(EventType.sessionResult, Self.result).body else {
            Issue.record("the result payload no longer decodes")
            return
        }

        model.live.route(Fixture.event(EventType.sessionResult, Self.result, session: "other"))
        model.live.route(Fixture.event(EventType.sessionResult, Self.result, session: "unknown"))
        #expect(model.app.reloadingRepos == nil)
        model.live.route(Fixture.event(EventType.sessionResult, Self.result, session: "init"))
        model.live.route(Fixture.event(EventType.sessionResult, Self.result, session: "init"))
        await model.app.reloadingRepos?.value

        #expect(api.calls.count { $0 == "repos" } == before + 2)
    }

    @Test func aFailedReloadIsShownAsASyncError() async throws {
        await model.live.refresh()
        api.fail("repos")
        model.app.reloadRepos()
        await model.app.reloadingRepos?.value
        #expect(model.app.syncError == .server(status: 500, detail: "boom"))

        api.fail("repos", with: CancellationError())
        model.app.reloadRepos()
        await model.app.reloadingRepos?.value
        #expect(model.app.syncError == .transport("CancellationError()"))
    }
}
