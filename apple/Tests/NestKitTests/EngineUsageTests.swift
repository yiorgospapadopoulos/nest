import Foundation
import Testing

@testable import NestKit

/// B91, both engines side by side: one model menu with a section per engine, the usage
/// meter with a line per signed-in engine, the popover's windows of each, and the
/// calendar's split by engine.
@MainActor @Suite struct ModelSectionsTests {
    let api = FakeAPI()
    let claude = ModelCatalog(models: Fixture.models)

    init() {
        api.set {
            $0.providers =
                Fixture.decode(ProviderList.self, json: ProviderDecodingTests.json)
                .providers
            $0.providerModels = ["codex": ProviderDecodingTests.codexModels]
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
        #expect(sections[1].catalog.models.map(\.value) == ["default", "gpt-5.5-codex"])
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
    let claude = ModelCatalog(models: Fixture.models)
    let codex = ModelCatalog(models: ProviderDecodingTests.codexModels)
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
                    provider: "codex", model: "gpt-5.5-codex", effort: nil, permission: .plan))
    }

    /// On the same engine only the model changes, its thinking kept where it can be.
    @Test func aModelOfTheSameEngineKeepsTheRest() {
        let draft = NewChatChoices(
            provider: "codex", model: "gpt-5.5-codex", effort: .xhigh, permission: .auto)
        let chosen = draft.choosing("default", on: "codex", catalog: codex, defaults: defaults)
        #expect(
            chosen
                == NewChatChoices(
                    provider: "codex", model: "default", effort: .high, permission: .auto))
    }

    /// Back to a Claude model: Claude's thinking default, Auto left where it is missing.
    @Test func aClaudeModelBringsTheDraftBack() {
        let draft = NewChatChoices(
            provider: "codex", model: "default", effort: .low, permission: .auto)
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

    /// Codex's free plan, as the live check found it: one 30-day window.
    static let codexLimits = UsageLimits(windows: [
        LimitWindow(
            utilization: 0.04, resetsAt: tuesday.addingTimeInterval(29 * 86_400 + 3 * 3_600),
            updatedAt: tuesday, minutes: 43_200, label: "30 day")
    ])
    /// A plan with a 5-hour and a weekly window.
    static let plusLimits = UsageLimits(windows: [
        LimitWindow(
            utilization: 0.12, resetsAt: tuesday.addingTimeInterval(3_600), updatedAt: tuesday,
            minutes: 300, label: "5 hour"),
        LimitWindow(utilization: 0.45, updatedAt: tuesday, minutes: 10_080, label: "Weekly"),
    ])

    init() {
        api.set {
            $0.providers =
                Fixture.decode(ProviderList.self, json: ProviderDecodingTests.json)
                .providers
            $0.engineLimits = ["codex": Self.codexLimits]
        }
        providers = ProvidersStore(api: api)
    }

    func signIn(_ signedIn: Bool?) async {
        api.set { $0.providers[1].signedIn = signedIn }
        await providers.load()
    }

    @Test func loadsEachEnginesWindows() async throws {
        let usage = UsageStore(api: api, now: { tuesday })
        try await usage.load()
        #expect(usage.engineLimits["codex"] == Self.codexLimits)
        #expect(api.calls.prefix(2) == ["usageLimits", "usageLimitsFor codex"])
        // A daemon that cannot say keeps Claude's windows and the chart.
        api.fail("usageLimitsFor")
        let older = UsageStore(api: api, now: { tuesday })
        try await older.load()
        #expect(older.engineLimits.isEmpty)
        #expect(older.limits != nil)
    }

    /// Claude's line always; Codex's only while it is signed in.
    @Test func theMeterHasALinePerSignedInEngine() async throws {
        let usage = UsageStore(api: api, now: { tuesday })
        try await usage.load()
        await signIn(false)
        #expect(usage.meter(providers: providers, now: tuesday).map(\.provider) == ["claude"])
        await signIn(nil)
        #expect(usage.meter(providers: providers, now: tuesday).map(\.provider) == ["claude"])
        await signIn(true)
        let lines = usage.meter(providers: providers, now: tuesday)
        #expect(lines.map(\.id) == ["claude", "codex"])
        #expect(lines.map(\.name) == ["Claude", "Codex"])
        // One window is one value, named by its length.
        #expect(lines[1].chip?.entries.map(\.text) == ["4% 29d 3h"])
        #expect(lines[1].chip?.tooltip == "30 day: 4%, resets in 29d 3h")
        #expect(lines[1].chip?.used == 0.04)
        #expect(lines[0].chip?.entries.map(\.text) == ["30% 6h 30m"])
        api.set { $0.engineLimits = ["codex": Self.plusLimits] }
        try await usage.load()
        let plus = usage.meter(providers: providers, now: tuesday)[1].chip
        #expect(plus?.entries.map(\.text) == ["12% 1h", "45% wk"])
        #expect(plus?.tooltip == "5 hour: 12%, resets in 1h. Weekly: 45%")
        #expect(plus?.used == 0.12)
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

    /// A signed-in engine whose windows are not known yet shows its line without numbers.
    @Test func aSignedInEngineWithoutWindowsHasAnEmptyLine() async throws {
        api.set { $0.engineLimits = [:] }
        let usage = UsageStore(api: api, now: { tuesday })
        try await usage.load()
        await signIn(true)
        let lines = usage.meter(providers: providers, now: tuesday)
        #expect(lines.count == 2)
        #expect(lines[1].chip == nil)
        #expect(
            usage.meterTooltip(lines)
                == "Claude: 5-hour: 30%, resets in 6h 30m. Codex: not reported yet")
    }

    /// The popover's windows: Claude's alone without headings, then each signed-in engine
    /// under its name.
    @Test func thePopoverListsEachSignedInEnginesWindows() async throws {
        let usage = UsageStore(api: api, now: { tuesday })
        try await usage.load()
        await signIn(false)
        let alone = usage.limitGroups(providers: providers)
        #expect(alone.map(\.title) == [nil])
        #expect(alone[0].limits == usage.limits)
        await signIn(true)
        let both = usage.limitGroups(providers: providers)
        #expect(both.map(\.title) == ["Claude", "Codex"])
        #expect(both.map(\.id) == ["claude", "codex"])
        #expect(both[1].limits == Self.codexLimits)
        #expect(both[0].rows.map(\.title) == ["5 hour", "Weekly"])
        // Before Claude reported, its two rows without numbers.
        let early = UsageLimitGroup(provider: "claude", title: nil, limits: nil).rows
        #expect(early.map(\.title) == ["5 hour", "Weekly"])
        #expect(early.allSatisfy { $0.window == nil })
        // The popover lists the rows by their names.
        #expect(both[0].rows.map(\.id) == ["5 hour", "Weekly"])
        #expect(both[1].rows.map(\.title) == ["30 day"])
        #expect(both[1].rows[0].window?.utilization == 0.04)
        // An engine that has not reported yet shows one row without numbers.
        api.set { $0.engineLimits = [:] }
        let quiet = UsageStore(api: api, now: { tuesday })
        try await quiet.load()
        let rows = quiet.limitGroups(providers: providers)[1].rows
        #expect(rows.map(\.title) == ["Usage"])
        #expect(rows[0].window == nil)
    }

    @Test func anotherEnginesEventUpdatesOnlyItsWindows() async throws {
        let usage = UsageStore(api: api, now: { tuesday })
        try await usage.load()
        let claude = usage.limits
        // As the daemon sends it: the engine's windows whole, each with its length and label.
        let event = Fixture.event(
            EventType.usageProviderUpdated,
            """
            {"provider": "codex", "windows": [
              {"utilization": 0.1, "resets_at": null, "minutes": 300, "label": "5 hour"},
              {"utilization": 0.5, "resets_at": null, "minutes": 10080, "label": "Weekly"}]}
            """,
            session: nil)
        usage.apply(event)
        #expect(usage.limits == claude)
        let windows = try #require(usage.engineLimits["codex"]?.windows)
        #expect(windows.map(\.label) == ["5 hour", "Weekly"])
        #expect(windows.map(\.utilization) == [0.1, 0.5])
        #expect(windows.map(\.updatedAt) == [event.ts, event.ts])
        // A first report of an engine not loaded starts its windows.
        let fresh = UsageStore(api: api, now: { tuesday })
        fresh.apply(event)
        #expect(fresh.engineLimits["codex"]?.windows?.count == 2)
        #expect(fresh.limits == nil)
    }

    /// Refresh asks every engine; another engine failing changes nothing of Claude's.
    @Test func refreshAsksEveryEngine() async throws {
        let usage = UsageStore(api: api, now: { tuesday })
        try await usage.load()
        api.set { $0.refreshedEngineLimits = ["codex": UsageLimits(windows: [])] }
        await usage.refresh()
        #expect(api.calls.contains("refreshUsageFor codex"))
        #expect(usage.engineLimits["codex"] == UsageLimits(windows: []))
        api.fail("refreshUsageFor", with: APIError.badGateway("signed out"))
        await usage.refresh()
        #expect(usage.refreshFailure == nil)
        #expect(usage.engineLimits["codex"] == UsageLimits(windows: []))
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
        try await usage.load()
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
