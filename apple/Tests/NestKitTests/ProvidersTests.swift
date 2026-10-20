import Foundation
import Testing

@testable import NestKit

/// The engines a chat runs on (B91): `GET /api/providers`, their model lists, what their
/// chats cannot do, and the engine choice of a new chat.
@Suite struct ProviderDecodingTests {
    @Test func decodesEachEngineWithItsUnsupportedFeatures() throws {
        let list = Fixture.decode(ProviderList.self, json: Self.json)
        #expect(list.providers.map(\.name) == ["claude", "codex"])
        let claude = list.providers[0]
        #expect(claude.id == "claude")
        #expect(claude.displayName == "Claude")
        #expect(claude.signedIn == nil)
        #expect(claude.signInHint == nil)
        #expect(claude.account == nil)
        #expect(claude.unsupported.isEmpty)
        let codex = list.providers[1]
        #expect(codex.signedIn == false)
        #expect(codex.signInHint == Self.hint)
        #expect(codex.account?.plan == "ChatGPT Plus")
        // A feature this app does not know is left out.
        #expect(
            codex.unsupported == [
                .rewind, .fork, .slashCommands, .stopTask, .withdraw, .planReview, .questions,
                .subagents, .nestTools, .taskList, .pixies, .memory, .pixieSkills,
            ])
    }

    @Test func aBuiltEngineDefaultsToNothingUnsupported() {
        let info = ProviderInfo(name: "claude", displayName: "Claude")
        #expect(info.signedIn == nil)
        #expect(info.unsupported.isEmpty)
    }

    /// Each feature says what a chat without it cannot do, for a refusal without words.
    @Test func everyFeatureHasRefusalWords() {
        let words = [
            ProviderFeature.rewind, .fork, .slashCommands, .stopTask, .withdraw, .planReview,
            .questions, .subagents, .nestTools, .taskList, .pixies, .memory, .pixieSkills,
            .unknown,
        ].map(\.refusal)
        #expect(
            words == [
                "be rewound", "be forked", "run slash commands", "stop a single task",
                "take back a message sent into the turn", "review a plan", "ask questions",
                "run subagents", "use Nest's tools", "keep a task list", "call pixies",
                "save a memory to CLAUDE.md", "keep a pixie's own skill list", "do that",
            ])
    }

    /// Codex's list as the daemon gives it since B94: real models, the first its default.
    static let codexModels = [
        ModelInfo(
            value: "gpt-5.5-codex", displayName: "GPT-5.5 Codex", description: "For coding",
            effortLevels: [.low, .medium, .high, .xhigh], supportsEffort: true,
            supportsAutoMode: true),
        ModelInfo(
            value: "gpt-5.5-mini", displayName: "GPT-5.5 Mini", description: "Fast",
            effortLevels: [.low, .high], supportsEffort: true),
    ]

    static let hint = "Codex isn't signed in. Run `codex login` with a ChatGPT plan."

    static let json = """
        {"providers": [
          {"name": "claude", "display_name": "Claude", "signed_in": null, "sign_in_hint": null,
           "account": null, "unsupported": []},
          {"name": "codex", "display_name": "Codex", "signed_in": false,
           "sign_in_hint": "\(hint)",
           "account": {"display_name": null, "email": null, "plan": "ChatGPT Plus",
                       "organization": null},
           "unsupported": ["fork", "nest_tools", "pixies", "plan_review", "questions",
                           "rewind", "slash_commands", "stop_task", "subagents", "task_list",
                           "withdraw", "memory", "pixie_skills", "teleport"]}
        ]}
        """
}

@MainActor @Suite struct ProvidersStoreTests {
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

    @Test func loadsTheEnginesAndTheOtherEnginesModels() async {
        let store = ProvidersStore(api: api)
        #expect(store.providers.isEmpty)
        #expect(!store.offersChoice)
        await store.load()
        #expect(store.providers.map(\.name) == ["claude", "codex"])
        #expect(store.offersChoice)
        #expect(store.models["codex"]?.map(\.value) == ["gpt-5.5-codex", "gpt-5.5-mini"])
        #expect(store.defaultModels["codex"] == "gpt-5.5-codex")
        // Claude's list is the agents store's; it is not asked twice.
        #expect(api.calls == ["providers false", "modelsFor codex"])
        await store.load(refresh: true)
        #expect(api.calls.suffix(2) == ["providers true", "modelsFor codex"])
    }

    /// An older daemon without engines, or one call failing, keeps what was there.
    @Test func aFailedLoadKeepsTheLastAnswer() async {
        let store = ProvidersStore(api: api)
        await store.load()
        api.fail("providers")
        api.fail("modelsFor")
        await store.load()
        #expect(store.providers.count == 2)
        #expect(store.models["codex"]?.count == 2)

        let fresh = ProvidersStore(api: api)
        await fresh.load()
        #expect(fresh.providers.isEmpty)
        #expect(fresh.models.isEmpty)
    }

    @Test func namesEachEngine() async {
        let store = ProvidersStore(api: api)
        // Before loading, a chat is Claude's, and other names read as themselves.
        #expect(store.displayName(nil) == "Claude")
        #expect(store.displayName("codex") == "Codex")
        await store.load()
        #expect(store.displayName(nil) == "Claude")
        #expect(store.displayName("claude") == "Claude")
        #expect(store.provider("codex")?.displayName == "Codex")
        #expect(store.provider("gemini") == nil)
        #expect(store.displayName("gemini") == "Gemini")
    }

    /// What the menu says under each engine's name.
    @Test func describesEachEngineInTheMenu() async {
        let store = ProvidersStore(api: api)
        await store.load()
        #expect(store.detail(for: store.providers[0]) == "")
        #expect(store.detail(for: store.providers[1]) == "Not signed in")
        api.set { $0.providers[1].signedIn = true }
        await store.load()
        #expect(store.detail(for: store.providers[1]) == "ChatGPT Plus")
        api.set { $0.providers[1].account = nil }
        await store.load()
        #expect(store.detail(for: store.providers[1]) == "")
    }

    /// Gating follows the daemon's list, not the engine's name: what is not loaded or not
    /// listed stays offered, and the daemon still refuses it.
    @Test func gatesFeaturesByTheEnginesList() async {
        let store = ProvidersStore(api: api)
        #expect(store.supports(.rewind, on: "codex"))
        await store.load()
        #expect(store.supports(.rewind, on: nil))
        #expect(store.supports(.rewind, on: "claude"))
        #expect(!store.supports(.rewind, on: "codex"))
        #expect(!store.supports(.pixies, on: "codex"))
        #expect(store.supports(.rewind, on: "gemini"))

        var session = Fixture.session()
        #expect(store.supports(.fork, in: session))
        session.provider = "codex"
        #expect(!store.supports(.fork, in: session))
        #expect(store.supports(.fork, in: nil))
    }

    /// A message already written into a Codex turn cannot be taken back; one still waiting
    /// for the turn's end can, as in Claude's chats.
    @Test func takesBackOnlyWhatTheEngineCan() async {
        let store = ProvidersStore(api: api)
        await store.load()
        var session = Fixture.session()
        let waiting = QueuedMessage(id: "q1", text: "a", createdAt: Date(), sent: false)
        let written = QueuedMessage(id: "q2", text: "b", createdAt: Date(), sent: true)
        #expect(store.canTakeBack(written, in: session))
        session.provider = "codex"
        #expect(store.canTakeBack(waiting, in: session))
        #expect(!store.canTakeBack(written, in: session))
    }

    @Test func hintsAtSigningInOnlyWhenTheEngineSaysItIsNot() async {
        let store = ProvidersStore(api: api)
        #expect(store.signInHint(for: "codex") == nil)
        await store.load()
        #expect(store.signInHint(for: nil) == nil)
        #expect(store.signInHint(for: "claude") == nil)
        #expect(store.signInHint(for: "codex") == ProviderDecodingTests.hint)
        api.set { $0.providers[1].signInHint = nil }
        await store.load()
        #expect(store.signInHint(for: "codex") == "Codex isn't signed in.")
        api.set { $0.providers[1].signedIn = nil }
        await store.load()
        #expect(store.signInHint(for: "codex") == nil)
    }

    /// What the running agent is called in a chat's words, such as "Codex reads this at
    /// its next step": its engine's name, Claude for a chat on Claude or none.
    @Test func namesTheAgentOfEachChat() async {
        let store = ProvidersStore(api: api)
        await store.load()
        var session = Fixture.session()
        #expect(store.agentName(in: nil) == "Claude")
        #expect(store.agentName(in: session) == "Claude")
        session.provider = "codex"
        #expect(store.agentName(in: session) == "Codex")
    }

    /// The chat header names the engine only for a chat off the default one.
    @Test func labelsChatsOffTheDefaultEngine() async {
        let store = ProvidersStore(api: api)
        var session = Fixture.session()
        session.provider = "codex"
        #expect(store.label(for: session) == "Codex")
        await store.load()
        #expect(store.label(for: nil) == nil)
        #expect(store.label(for: session) == "Codex")
        session.provider = "claude"
        #expect(store.label(for: session) == nil)
    }

    @Test func picksEachEnginesModelCatalog() async {
        let store = ProvidersStore(api: api)
        let claude = ModelCatalog(models: Fixture.models)
        #expect(store.catalog(for: "codex", claude: claude).models.isEmpty)
        await store.load()
        #expect(store.catalog(for: nil, claude: claude) == claude)
        #expect(store.catalog(for: "claude", claude: claude) == claude)
        let codex = store.catalog(for: "codex", claude: claude)
        #expect(codex.models.map(\.value) == ["gpt-5.5-codex", "gpt-5.5-mini"])
        #expect(codex.defaultModel == "gpt-5.5-codex")
        #expect(codex.label(for: nil) == "GPT-5.5 Codex")
        #expect(codex.thinkingLevels(for: "gpt-5.5-codex") == [.low, .medium, .high, .xhigh])
        #expect(codex.supportsAuto(nil))
        #expect(!codex.supportsAuto("gpt-5.5-mini"))
    }

    @Test func liveSyncLoadsTheEngines() async {
        let model = AppModel(api: api, events: ManualEventSource(), preferences: MemoryStore())
        await model.live.refresh()
        #expect(model.providers.providers.count == 2)
        #expect(api.calls.contains("providers false"))
    }
}

@Suite struct ModelCatalogTests {
    let catalog = ModelCatalog(models: Fixture.models, defaultModel: "opus")

    @Test func labelsAndSelectsModels() {
        #expect(catalog.label(for: nil) == "Opus 5.5")
        #expect(catalog.label(for: "claude-opus-4-1") == "claude-opus-4-1")
        #expect(catalog.isSelected(Fixture.models[0], current: nil))
        #expect(!catalog.isSelected(Fixture.models[1], current: nil))
    }

    /// A new chat leaves Auto for a model without it: for the fallback mode, or Ask when
    /// the fallback is Auto too.
    @Test func newChatsLeaveAutoWhereTheModelLacksIt() {
        #expect(
            catalog.newChatPermission(.auto, afterSwitchingTo: "opus", fallback: .default)
                == .auto)
        #expect(
            catalog.newChatPermission(.auto, afterSwitchingTo: "haiku", fallback: .plan) == .plan)
        #expect(
            catalog.newChatPermission(.auto, afterSwitchingTo: "haiku", fallback: .auto)
                == .default)
        #expect(
            catalog.newChatPermission(.plan, afterSwitchingTo: "haiku", fallback: .default)
                == .plan)
    }
}

@Suite struct NewChatChoicesTests {
    let claude = ModelCatalog(models: Fixture.models, defaultModel: "opus")
    let codex = ModelCatalog(
        models: ProviderDecodingTests.codexModels, defaultModel: "gpt-5.5-codex")
    let defaults = AgentDefaults(
        model: "opus", effort: .xhigh, permissionMode: .acceptEdits, mode: .inPlace)

    /// Codex starts on its own default model, its thinking kept where it takes it; the
    /// mode stays.
    @Test func switchingToAnotherEngineTakesItsDefaults() {
        let choices = NewChatChoices(
            provider: nil, model: "opus", effort: .max, permission: .plan)
        let switched = choices.switching(to: "codex", catalog: codex, defaults: defaults)
        #expect(
            switched
                == NewChatChoices(
                    provider: "codex", model: "gpt-5.5-codex", effort: .medium, permission: .plan))
    }

    /// Back on Claude, the agent defaults' model and thinking apply again.
    @Test func switchingBackToClaudeTakesTheAgentDefaults() {
        let choices = NewChatChoices(
            provider: "codex", model: "gpt-5.5-codex", effort: .low, permission: .auto)
        let switched = choices.switching(to: "claude", catalog: claude, defaults: defaults)
        #expect(
            switched
                == NewChatChoices(provider: nil, model: "opus", effort: .xhigh, permission: .auto))
        var haikuDefaults = defaults
        haikuDefaults.model = "haiku"
        // Haiku has no Auto: the agent default's mode instead.
        #expect(
            choices.switching(to: nil, catalog: claude, defaults: haikuDefaults).permission
                == .acceptEdits)
    }

    @Test func choosingTheSameEngineChangesNothing() {
        let choices = NewChatChoices(
            provider: "codex", model: "gpt-5.5-codex", effort: .low, permission: .plan)
        #expect(choices.switching(to: "codex", catalog: codex, defaults: defaults) == choices)
        let onClaude = NewChatChoices(
            provider: nil, model: "haiku", effort: nil, permission: .default)
        #expect(onClaude.switching(to: "claude", catalog: claude, defaults: defaults) == onClaude)
    }
}
