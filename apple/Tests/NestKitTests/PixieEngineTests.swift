import Foundation
import Testing

@testable import NestKit

/// B91 stage 2: a pixie runs on Claude or Codex, chosen with its model in one picker with
/// a section per engine, as a new chat's model menu.
@MainActor @Suite struct PixieEngineTests {
    let api = FakeAPI()

    init() {
        api.set {
            $0.providers =
                Fixture.decode(ProviderList.self, json: ProviderDecodingTests.json)
                .providers
            $0.providerModels = ["codex": ProviderDecodingTests.codexModels]
            $0.providerDefaults = ["codex": "gpt-5.5-codex"]
        }
    }

    static let claude = ModelCatalog(models: models, defaultModel: "opus")

    static let models = [
        ModelInfo(
            value: "opus", displayName: "Opus", description: "Most capable",
            effortLevels: [.low, .high], supportsEffort: true, supportsAutoMode: true),
        ModelInfo(
            value: "haiku", displayName: "Haiku", description: "Fastest", effortLevels: [],
            supportsEffort: false),
    ]

    func pixie(provider: String? = nil, model: String? = nil) -> Pixie {
        var pixie = Fixture.decode(Pixie.self, "pixie")
        pixie.provider = provider
        pixie.model = model
        return pixie
    }

    func picker(_ pixie: Pixie, loaded: Bool = true) async -> PixieModelPicker {
        let store = ProvidersStore(api: api)
        if loaded {
            await store.load()
        }
        return PixieModelPicker(pixie: pixie, providers: store, claude: Self.claude)
    }

    @Test func aPixieFromBeforeB91RunsOnClaude() {
        let pixie = Fixture.decode(Pixie.self, "pixie")
        #expect(pixie.provider == nil)
        #expect(pixie.engine == "claude")
        #expect(self.pixie(provider: "codex").engine == "codex")
    }

    @Test func eachEngineIsASectionAndChoosingAModelChoosesTheEngine() async {
        let picker = await picker(pixie())

        #expect(picker.sections.map(\.title) == ["Claude", "Codex"])
        #expect(picker.sections.map(\.id) == ["claude", "codex"])
        #expect(picker.sections.map(\.detail) == ["", "Not signed in"])
        // Real models only (B94); a pixie without a model yet shows its engine's default.
        let claude = picker.sections[0].entries
        #expect(claude.map(\.title) == ["Opus", "Haiku"])
        #expect(claude.map(\.checked) == [true, false])
        #expect(claude[0].request == UpdatePixieRequest(model: "opus"))
        let codex = picker.sections[1].entries
        #expect(codex.map(\.title) == ["GPT-5.5 Codex", "GPT-5.5 Mini"])
        #expect(codex.map(\.checked) == [false, false])
        #expect(codex[0].request == UpdatePixieRequest(provider: "codex", model: "gpt-5.5-codex"))
        #expect(picker.value == "Opus")
        #expect(picker.catalog == Self.claude)
        #expect(picker.runningModel == "opus")
    }

    @Test func aCodexPixieShowsItsEngineAndGoesBackToClaudeByAModel() async {
        let onDefault = await picker(pixie(provider: "codex"))
        let chosen = await picker(pixie(provider: "codex", model: "gpt-5.5-codex"))

        #expect(onDefault.value == "Codex · GPT-5.5 Codex")
        #expect(onDefault.sections[1].entries.map(\.checked) == [true, false])
        #expect(onDefault.sections[0].entries.map(\.checked) == [false, false])
        #expect(chosen.value == "Codex · GPT-5.5 Codex")
        #expect(chosen.sections[1].entries.map(\.checked) == [true, false])
        #expect(
            chosen.sections[0].entries.map(\.request) == [
                UpdatePixieRequest(provider: "claude", model: "opus"),
                UpdatePixieRequest(provider: "claude", model: "haiku"),
            ])
        #expect(chosen.catalog.models.map(\.value) == ["gpt-5.5-codex", "gpt-5.5-mini"])
        #expect(chosen.runningModel == "gpt-5.5-codex")
        #expect(onDefault.runningModel == "gpt-5.5-codex")
    }

    /// With one engine, one Model section as before; an engine whose list is not loaded
    /// says so.
    @Test func oneEngineKeepsOneModelSection() async {
        let alone = await picker(pixie(model: "haiku"), loaded: false)
        #expect(alone.sections.map(\.title) == ["Model"])
        #expect(alone.sections[0].entries.map(\.checked) == [false, true])
        #expect(!alone.sections[0].unavailable)
        #expect(alone.value == "Haiku")

        api.set { $0.providerModels = [:] }
        let unloaded = await picker(pixie())
        #expect(unloaded.sections[1].entries.isEmpty)
        #expect(unloaded.sections[1].unavailable)
    }

    @Test func movingToAnotherEngineClearsTheModelAndThinkingAsTheDaemonDoes() {
        var pixie = pixie(model: "opus")
        pixie.effort = .high

        let moved = pixie.applying(UpdatePixieRequest(provider: "codex"))
        let chosen = pixie.applying(UpdatePixieRequest(provider: "codex", model: "gpt-5.5-codex"))
        let same = pixie.applying(UpdatePixieRequest(provider: "claude"))

        #expect((moved.provider, moved.model, moved.effort) == ("codex", nil, nil))
        #expect((chosen.model, chosen.effort) == ("gpt-5.5-codex", nil))
        #expect((same.model, same.effort) == ("opus", .high))
    }

    @Test func theEngineIsSentOnlyWhenChosen() {
        #expect(
            Fixture.json(UpdatePixieRequest(provider: "codex", model: "gpt-5.5-codex"))
                == #"{"model":"gpt-5.5-codex","provider":"codex"}"#)
        #expect(Fixture.json(UpdatePixieRequest(model: "opus")) == #"{"model":"opus"}"#)
    }

    /// Codex has no per-run skill list, so a Codex pixie's details leave Skills out; read
    /// from the engine's unsupported list, not its name.
    @Test func skillsShowOnlyForAnEngineThatTakesThem() async {
        let store = ProvidersStore(api: api)
        #expect(store.supports(.pixieSkills, on: pixie(provider: "codex").provider))
        await store.load()
        #expect(store.supports(.pixieSkills, on: pixie().provider))
        #expect(!store.supports(.pixieSkills, on: pixie(provider: "codex").provider))
    }
}
