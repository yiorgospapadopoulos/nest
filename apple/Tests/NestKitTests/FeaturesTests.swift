import Foundation
import Testing

@testable import NestKit

/// B103: Settings > Features, what makes Nest different by area, with the features that
/// are new on this device.
@MainActor
@Suite struct FeaturesTests {
    static var catalog: FeaturesCatalog { Fixture.decode(FeaturesCatalog.self, "features") }
    static let key = "nest.features.groups"

    func store(_ preferences: MemoryStore = MemoryStore()) -> (FeaturesStore, FakeAPI) {
        let api = FakeAPI()
        api.set { $0.features = Self.catalog }
        return (FeaturesStore(api: api, store: preferences), api)
    }

    @Test func decodesTheDaemonsBody() {
        let catalog = Self.catalog
        #expect(catalog.groups.map(\.id) == ["chats", "git"])
        #expect(catalog.groups.map(\.name) == ["Chats", "Worktrees and git"])
        #expect(catalog.newCount == 2)
        #expect(catalog.total == 5)
        let feedback = catalog.groups[1].features[1]
        #expect(feedback.id == "feedback-to-agent")
        #expect(feedback.name == "Feedback back to the agent")
        #expect(feedback.place == "Needs you")
        #expect(feedback.added == "2026-10-14")
        #expect(feedback.changed == "2026-10-21")
        #expect(feedback.block == "B101")
        #expect(feedback.isNew)
        let review = catalog.groups[1].features[2]
        #expect(review.changed == nil)
        #expect(!review.isNew)
        #expect(catalog.groups[1].newCount == 2)
        #expect(catalog.groups[0].newCount == 0)
        let built = FeatureGroup(
            id: "git", name: "Worktrees and git",
            features: [
                Feature(
                    id: "review", name: "Review before it lands", text: review.text,
                    place: "Above the composer", added: "2026-10-15", block: "B57")
            ])
        #expect(built.features == [review])
        #expect(built.newCount == 0)
    }

    /// Backtick spans show as inline code; the rest is plain text, without the ticks.
    @Test func textSplitsIntoPlainAndCodeRuns() {
        let shortcuts = Self.catalog.groups[0].features[0]
        let parts = shortcuts.parts
        #expect(
            parts.prefix(4).map(\.text) == [
                "/", " for commands and skills, ", "@", " for files and pixies, ",
            ])
        #expect(parts.prefix(4).map(\.isCode) == [true, false, true, false])
        #expect(parts.filter(\.isCode).map(\.text) == ["/", "@", "!", "#"])
        #expect(!parts.contains { $0.text.contains("`") })
        let plain = Self.catalog.groups[0].features[1].parts
        #expect(plain == [InlineCode(text: plain[0].text, isCode: false)])
    }

    @Test func loadReadsTheCatalogAndANewCount() async throws {
        let (store, api) = store()
        #expect(store.catalog == nil)
        #expect(store.newCount == 0)
        #expect(!store.isNew(Self.catalog.groups[1].features[0]))
        try await store.load()
        #expect(store.newCount == 2)
        #expect(store.isNew(Self.catalog.groups[1].features[0]))
        #expect(store.catalog?.groups.count == 2)
        api.fail("features")
        await #expect(throws: (any Error).self) { try await store.load() }
        #expect(store.newCount == 2)
        #expect(api.calls == ["features", "features"])
    }

    /// A group with something new starts open; the user's own open or close is kept per
    /// group on this Mac and wins from then on.
    @Test func groupsOpenWhenNewAndRememberTheUsersChoice() async throws {
        let preferences = MemoryStore()
        let (store, _) = store(preferences)
        try await store.load()
        let groups = Self.catalog.groups
        #expect(!store.isOpen(groups[0]))
        #expect(store.isOpen(groups[1]))
        store.toggle(groups[0])
        store.toggle(groups[1])
        #expect(store.isOpen(groups[0]))
        #expect(!store.isOpen(groups[1]))
        let stored = try #require(preferences.values[Self.key])
        let decoded = try JSONDecoder().decode([String: Bool].self, from: Data(stored.utf8))
        #expect(decoded == ["chats": true, "git": false])

        let (again, _) = self.store(preferences)
        try await again.load()
        #expect(again.isOpen(groups[0]))
        #expect(!again.isOpen(groups[1]))
    }

    @Test func anUnreadableStoredChoiceIsIgnored() async throws {
        let (store, _) = store(MemoryStore([Self.key: "not json"]))
        try await store.load()
        #expect(store.isOpen(Self.catalog.groups[1]))
        #expect(!store.isOpen(Self.catalog.groups[0]))
    }

    /// What the page shows: the features of the open groups, in order.
    @Test func shownIDsAreTheOpenGroupsFeatures() async throws {
        let (store, _) = store()
        #expect(store.shownIDs.isEmpty)
        try await store.load()
        #expect(store.shownIDs == ["branch-map", "feedback-to-agent", "review"])
        store.toggle(Self.catalog.groups[0])
        #expect(
            store.shownIDs == [
                "composer-shortcuts", "talk-while-working", "branch-map", "feedback-to-agent",
                "review",
            ])
    }

    /// Each id is reported once per run of the app; a failed report is tried again next time.
    @Test func markShownReportsEachIDOnce() async throws {
        let (store, api) = store()
        try await store.load()
        var answer = Self.catalog
        answer.groups[1].features[0].isNew = false
        api.set { $0.features = answer }
        try await store.markShown(["branch-map", "review"])
        #expect(store.catalog == answer)
        try await store.markShown(["review", "branch-map"])
        try await store.markShown([])
        api.fail("markFeaturesShown")
        await #expect(throws: (any Error).self) {
            try await store.markShown(["review", "composer-shortcuts"])
        }
        api.set { $0.failures = [:] }
        try await store.markShown(["composer-shortcuts"])
        #expect(
            api.calls == [
                "features", "markFeaturesShown branch-map,review",
                "markFeaturesShown composer-shortcuts", "markFeaturesShown composer-shortcuts",
            ])
    }

    @Test func pageWords() async throws {
        let (store, api) = store()
        #expect(store.intro == FeaturesStore.introBase)
        #expect(store.footer == nil)
        try await store.load()
        #expect(
            store.intro
                == "What makes Nest different, by area. The README has every detail. 2 new since your last update."
        )
        #expect(store.footer == "5 features. New ones show \"New\" until you close Settings.")
        var none = Self.catalog
        none.newCount = 0
        none.groups = [none.groups[1]]
        none.groups[0].features = [none.groups[0].features[2]]
        api.set { $0.features = none }
        try await store.load()
        #expect(store.intro == "What makes Nest different, by area. The README has every detail.")
        #expect(store.footer == "1 feature. New ones show \"New\" until you close Settings.")
    }

    /// The catalog once this device has shown every feature: nothing is new any more.
    static var seenCatalog: FeaturesCatalog {
        var seen = catalog
        seen.newCount = 0
        for group in seen.groups.indices {
            for feature in seen.groups[group].features.indices {
                seen.groups[group].features[feature].isNew = false
            }
        }
        return seen
    }

    /// What was new when the page showed keeps its badge, its group open and its dot, and
    /// its place in the intro's and the sidebar's count for the rest of the visit, though
    /// the daemon stops calling it new as soon as it is shown. Opening Settings again starts
    /// a new visit, which forgets them.
    @Test func newBadgesLastTheVisitToSettings() async throws {
        let (store, api) = store()
        store.beginVisit()
        try await store.load()
        let branchMap = Self.catalog.groups[1].features[0]
        let review = Self.catalog.groups[1].features[2]
        #expect(store.isNew(branchMap))
        #expect(!store.isNew(review))
        api.set { $0.features = Self.seenCatalog }
        await store.pageShown()
        #expect(api.calls == ["features", "markFeaturesShown branch-map,feedback-to-agent,review"])
        #expect(store.newCount == 2)
        #expect(store.hasNew(Self.catalog.groups[1]))
        #expect(!store.hasNew(Self.catalog.groups[0]))
        #expect(store.isNew(branchMap))
        #expect(!store.isNew(review))
        #expect(store.isOpen(Self.catalog.groups[1]))
        #expect(store.intro.hasSuffix(" 2 new since your last update."))

        // Another page and back, still in the same visit: the daemon's answer changes nothing.
        try await store.load()
        await store.pageShown()
        #expect(store.isNew(branchMap))
        #expect(store.isOpen(Self.catalog.groups[1]))
        #expect(store.newCount == 2)

        // Settings opens again: the sidebar's count is gone before the page shows.
        store.beginVisit()
        try await store.load()
        #expect(store.newCount == 0)
        #expect(!store.hasNew(Self.catalog.groups[1]))
        await store.pageShown()
        #expect(!store.isNew(branchMap))
        #expect(!store.isOpen(Self.catalog.groups[1]))
        #expect(!store.hasNew(Self.catalog.groups[1]))
        #expect(store.newCount == 0)
        #expect(store.intro == FeaturesStore.introBase)
    }

    /// A failed report leaves the badges as they were; the sidebar keeps its count.
    @Test func aFailedReportKeepsTheVisitsBadges() async throws {
        let (store, api) = store()
        try await store.load()
        api.fail("markFeaturesShown")
        await store.pageShown()
        #expect(store.newCount == 2)
        #expect(store.isNew(Self.catalog.groups[1].features[1]))
    }

    /// The search field finds the page by its groups' and features' names.
    @Test func searchLabelsAreTheGroupAndFeatureNames() async throws {
        let (store, _) = store()
        #expect(store.labels.isEmpty)
        try await store.load()
        #expect(
            store.labels == [
                "Chats", "Composer shortcuts", "Talk while it works", "Worktrees and git",
                "Branch map", "Feedback back to the agent", "Review before it lands",
            ])
        let listed = SettingsPage.listed(projects: [], query: "branch map", features: store.labels)
        #expect(listed.pages == [.features])
        #expect(SettingsPage.listed(projects: [], query: "branch map").pages.isEmpty)
        #expect(SettingsPage.features.matches("features"))
        #expect(SettingsPage.features.matches("new"))
    }

    @Test func theFeaturesPageFollowsConfiguration() {
        let fixed = SettingsPage.fixed
        let index = try! #require(fixed.firstIndex(of: .configuration))
        #expect(fixed[index + 1] == .features)
        #expect(SettingsPage.features.title == "Features")
    }
}
