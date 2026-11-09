import Foundation
import Testing

@testable import NestKit

/// B148: GitHub triggers as the app reads, shows and edits them.
@MainActor @Suite struct GitHubTriggersTests {
    @Test func aHabitEditKeepsTheGitHubTriggersAPixieAdded() {
        let habit = PixieHabitsTests.habit()
        var withGitHub = habit
        withGitHub.github = [
            GitHubWatch(events: [.ciFailed], branches: ["main"]),
            GitHubWatch(events: [.review]),
        ]
        var draft = HabitDraft(habit: withGitHub)
        draft.github.labels = " bug, ui,bug "
        draft.github.branches = ""

        let request = draft.update(from: withGitHub)

        #expect(
            request.github == [
                GitHubWatch(events: [.ciFailed], labels: ["bug", "ui"]),
                GitHubWatch(events: [.review]),
            ])
        // No events left removes only the first.
        draft.github.events = []
        #expect(draft.update(from: withGitHub).github == [GitHubWatch(events: [.review])])
        #expect(HabitDraft(habit: habit).update(from: habit).github == nil)
    }

    @Test func aProjectReadsItsTriggersAndOlderDaemonsHaveNone() throws {
        let trigger = #"""
            {"id": "t1", "name": "CI", "prompt": "Fix it.", "enabled": true,
             "events": ["ci_failed", "pr_merged"], "labels": [], "branches": ["main"],
             "authors": "humans"}
            """#
        let base = #"""
            "name": "web", "path": "/w",
            "worktree": {"default": null, "link": [], "setup": [], "setup_timeout_seconds": 900}
            """#
        let repo = Fixture.decode(Repo.self, json: "{\(base), \"triggers\": [\(trigger)]}")
        let older = Fixture.decode(Repo.self, json: "{\(base)}")

        let read = try #require(repo.triggers.first)
        // An event this app does not know is kept as unknown, not a failure.
        #expect(read.events == [.ciFailed, .unknown])
        #expect(TriggerText.summary(read) == "When CI fails · on main · anyone but bots")
        #expect(older.triggers.isEmpty)
    }

    @Test func aTriggerIsSentWithItsListsSplit() {
        var draft = TriggerDraft()
        draft.name = " CI "
        draft.prompt = " Fix it. "
        draft.events = [.ciPassed, .ciFailed]
        draft.branches = "main, release/*"
        #expect(draft.canSave)

        #expect(
            draft.body
                == ChatTriggerBody(
                    name: "CI", prompt: "Fix it.", events: [.ciFailed, .ciPassed],
                    branches: ["main", "release/*"]))
        #expect(draft.body.permissionMode == .default)
        draft.permissionMode = .bypassPermissions
        let trigger = ChatTrigger(id: "t1", draft.body)
        #expect(
            TriggerText.summary(trigger)
                == "When CI fails or CI passes · on main, release/* · Bypass")
        draft.events = []
        #expect(draft.problem == "Choose at least one event")
    }

    @Test func savingATriggerShowsItOnTheProjectAtOnce() async throws {
        let store = AppStore(api: FakeAPI(), store: MemoryStore())
        try await store.loadRepos()
        let name = try #require(store.repos.first?.name)

        try await store.saveTrigger(
            name, id: nil, ChatTriggerBody(name: "CI", prompt: "Fix it.", events: [.ciFailed]))
        let saved = try #require(store.repo(name)?.triggers.first)
        try await store.switchTrigger(name, id: saved.id, on: false)
        #expect(store.repo(name)?.triggers.first?.enabled == false)
        try await store.deleteTrigger(name, id: saved.id)

        #expect(store.repo(name)?.triggers.isEmpty == true)
    }
}
