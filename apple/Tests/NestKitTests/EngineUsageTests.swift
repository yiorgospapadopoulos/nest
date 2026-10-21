import Foundation
import Testing

@testable import NestKit

/// B91, both engines side by side: one model menu with a section per engine, the usage
/// meter with a line per signed-in engine, the popover's windows of each, and the
/// calendar's split by engine.
@MainActor @Suite struct ModelSectionsTests {
    let api = FakeAPI()
    let claude = ModelCatalog(models: Fixture.models, defaultModel: "opus")

    init() {
        api.set {
            $0.providers =
                Fixture.decode(ProviderList.self, json: ProviderDecodingTests.json)
                .providers
            $0.providerModels = ["codex": ProviderDecodingTests.codexModels]
            $0.providerDefaults = ["codex": "gpt-5.5-codex"]
        }
    }

    /// Before the engines load, or from a daemon with one engine: one Model section of
    /// Claude's models, as before B91.
    @Test func oneEngineIsOneModelSection() {
        let store = ProvidersStore(api: api)
        let sections = store.modelSections(claude: claude, provider: nil, isDraft: true)
        #expect(sections.map(\.title) == ["Model"])
        #expect(sections[0].provider == "claude")
        #expect(sections[0].detail == "")
        #expect(sections[0].catalog == claude)
    }

    /// A new chat lists every engine, each under its name with its plan or that it is not
    /// signed in; a signed-out engine still lists its models.
    @Test func aNewChatListsEveryEngine() async {
        let store = ProvidersStore(api: api)
        await store.load()
        let sections = store.modelSections(claude: claude, provider: nil, isDraft: true)
        #expect(sections.map(\.title) == ["Claude", "Codex"])
        #expect(sections.map(\.detail) == ["", "Not signed in"])
        #expect(sections[1].catalog.models.map(\.value) == ["gpt-5.5-codex", "gpt-5.5-mini"])
        #expect(sections.map(\.id) == ["claude", "codex"])
    }

    /// A chat that exists keeps its engine: only its engine's models.
    @Test func anOpenChatListsOnlyItsEngine() async {
        let store = ProvidersStore(api: api)
        await store.load()
        let codex = store.modelSections(claude: claude, provider: "codex", isDraft: false)
        #expect(codex.map(\.title) == ["Codex"])
        let onClaude = store.modelSections(claude: claude, provider: nil, isDraft: false)
        #expect(onClaude.map(\.provider) == ["claude"])
        #expect(onClaude[0].title == "Claude")
    }

    /// The checkmark sits on the chat's model in the chat's engine's section only.
    @Test func onlyTheChatsEngineHasACheckmark() async {
        let store = ProvidersStore(api: api)
        await store.load()
        let sections = store.modelSections(claude: claude, provider: "codex", isDraft: true)
        let codexDefault = ProviderDecodingTests.codexModels[0]
        #expect(sections[1].isSelected(codexDefault, provider: "codex", model: nil))
        #expect(!sections[0].isSelected(Fixture.models[0], provider: "codex", model: nil))
        #expect(sections[0].isSelected(Fixture.models[0], provider: nil, model: nil))
        #expect(sections[0].isSelected(Fixture.models[0], provider: "claude", model: nil))
    }
}

@Suite struct ChoosingAModelTests {
    let claude = ModelCatalog(models: Fixture.models, defaultModel: "opus")
    let codex = ModelCatalog(
        models: ProviderDecodingTests.codexModels, defaultModel: "gpt-5.5-codex")
    let defaults = AgentDefaults(
        model: "opus", effort: .xhigh, permissionMode: .acceptEdits, mode: .inPlace)

    /// A Codex model moves a Claude draft to Codex, on that model, with thinking the
    /// model offers; the mode stays.
    @Test func aModelOfAnotherEngineSetsTheEngine() {
        let draft = NewChatChoices(provider: nil, model: "opus", effort: .max, permission: .plan)
        let chosen = draft.choosing(
            "gpt-5.5-codex", on: "codex", catalog: codex, defaults: defaults)
        #expect(
            chosen
                == NewChatChoices(
                    provider: "codex", model: "gpt-5.5-codex", effort: .medium, permission: .plan))
    }

    /// On the same engine only the model changes, its thinking kept where it can be.
    @Test func aModelOfTheSameEngineKeepsTheRest() {
        let draft = NewChatChoices(
            provider: "codex", model: "gpt-5.5-codex", effort: .xhigh, permission: .auto)
        let chosen = draft.choosing(
            "gpt-5.5-mini", on: "codex", catalog: codex, defaults: defaults)
        // Mini takes low and high, and no Auto: the agent default's mode.
        #expect(
            chosen
                == NewChatChoices(
                    provider: "codex", model: "gpt-5.5-mini", effort: .high,
                    permission: .acceptEdits))
    }

    /// Back to a Claude model: Claude's thinking default, Auto left where it is missing.
    @Test func aClaudeModelBringsTheDraftBack() {
        let draft = NewChatChoices(
            provider: "codex", model: "gpt-5.5-codex", effort: .low, permission: .auto)
        let chosen = draft.choosing("haiku", on: "claude", catalog: claude, defaults: defaults)
        #expect(chosen.provider == nil)
        #expect(chosen.model == "haiku")
        #expect(chosen.permission == .acceptEdits)
    }
}

/// 2026-10-06 12:00 UTC, a Tuesday.
private let tuesday = Date(timeIntervalSince1970: 1_791_288_000)

@MainActor @Suite struct EngineUsageTests {
    let api = FakeAPI()
    let providers: ProvidersStore

    init() {
        api.set {
            $0.providers =
                Fixture.decode(ProviderList.self, json: ProviderDecodingTests.json)
                .providers
        }
        providers = ProvidersStore(api: api)
    }

    /// Codex's limits as the daemon serves them: its windows by length, each labelled.
    @Test func anEnginesWindowsDecodeWithTheirLengthAndLabel() {
        let json = """
            {"windows": [{"utilization": 0.04, "resets_at": null,
              "updated_at": "2026-10-06T12:00:00Z", "minutes": 43200, "label": "30 day"}]}
            """
        let limits = Fixture.decode(UsageLimits.self, json: json)
        #expect(limits.fiveHour == nil)
        #expect(limits.windows?.map(\.minutes) == [43_200])
        #expect(limits.rows.map(\.title) == ["30 day"])
        // Claude's have no windows list and keep their two rows.
        let claude = Fixture.decode(
            UsageLimits.self, json: #"{"five_hour": null, "seven_day": null}"#)
        #expect(claude.windows == nil)
        #expect(claude.rows.map(\.title) == ["5 hour", "Weekly"])
    }

    /// A window's short size, shown when its reset time is not reported.
    @Test func aWindowsShortSizeComesFromItsLength() {
        let sizes = [300, 10_080, 43_200, 1_440, 120, 90, nil].map { UsageLimitRow.size($0) }
        #expect(sizes == ["5h", "wk", "30d", "1d", "2h", "90m", ""])
        let unsized = UsageLimits(windows: [LimitWindow(utilization: 0.2)])
        #expect(unsized.rows.map(\.title) == ["Usage"])
        #expect(UsageChip.of(unsized, now: tuesday)?.entries.map(\.text) == ["20%"])
    }

    /// The calendar's day counts every engine; its detail splits Claude and Codex.
    @Test func theBreakdownSplitsTheEngines() async throws {
        api.set {
            $0.periodEngines = [
                EngineTokens(provider: "codex", tokens: 400_000, sessions: 2),
                EngineTokens(provider: "claude", tokens: 1_200_000, sessions: 5),
            ]
        }
        let usage = UsageStore(api: api, now: { tuesday })
        try await usage.loadPeriod()
        await providers.load()
        let breakdown = try #require(usage.breakdown(providers: providers))
        #expect(breakdown.engines.map(\.label) == ["Claude", "Codex"])
        #expect(breakdown.engines.map(\.value) == ["1.2M", "400k"])
        // Without Codex tokens, both engines still show while there are two.
        api.set { $0.periodEngines = [] }
        try await usage.loadPeriod()
        let quiet = try #require(usage.breakdown(providers: providers))
        #expect(quiet.engines.map(\.label) == ["Claude", "Codex"])
        #expect(quiet.engines.map(\.value) == ["0", "0"])
        // One engine known and used: no split.
        let alone = ProvidersStore(api: FakeAPI())
        #expect(usage.breakdown(providers: alone)?.engines == [])
    }

    /// An engine the period reports but this app does not list is named after itself.
    @Test func anUnlistedEngineIsNamedAfterItself() throws {
        var period = Fixture.usagePeriod
        period.engines = [EngineTokens(provider: "gemini", tokens: 10, sessions: 1)]
        let breakdown = UsageBreakdown(period, engines: [])
        #expect(breakdown.engines.map(\.label) == ["Claude", "Gemini"])
    }

    @Test func aPeriodWithoutEnginesDecodes() {
        #expect(Fixture.usagePeriod.engines.isEmpty)
        let json = """
            {"provider": "codex", "tokens": 12, "sessions": 1}
            """
        #expect(
            Fixture.decode(EngineTokens.self, json: json)
                == EngineTokens(provider: "codex", tokens: 12, sessions: 1))
    }
}
