import Testing

@testable import NestKit

/// Browse's search (B94): it looks through every plugin the marketplaces offer, not only
/// the rows drawn so far.
@Suite struct PluginSearchTests {
    private let plugins = [
        AvailablePlugin(
            id: "superpowers@claude-plugins", name: "superpowers", marketplace: "claude-plugins",
            description: "Brainstorming, plans and test-driven development", source: "github"),
        AvailablePlugin(
            id: "pdf-viewer@tools", name: "pdf-viewer", marketplace: "tools",
            description: nil, source: "github"),
        AvailablePlugin(
            id: "remember@tools", name: "Remember", marketplace: "tools",
            description: "Keeps a memory of the session", source: "github"),
    ]

    @Test func anEmptyQueryKeepsEveryPlugin() {
        #expect(plugins.matching("") == plugins)
        #expect(plugins.matching("   ") == plugins)
    }

    @Test func matchesNameMarketplaceAndDescriptionIgnoringCase() {
        #expect(plugins.matching("PDF").map(\.name) == ["pdf-viewer"])
        #expect(plugins.matching("tools").map(\.name) == ["pdf-viewer", "Remember"])
        #expect(plugins.matching("brainstorm").map(\.name) == ["superpowers"])
        #expect(plugins.matching("remember").map(\.name) == ["Remember"])
    }

    @Test func everyWordMustMatchSomewhere() {
        #expect(plugins.matching("tools memory").map(\.name) == ["Remember"])
        #expect(plugins.matching("tools brainstorm").isEmpty)
    }
}
