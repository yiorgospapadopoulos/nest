import Foundation
import Testing

@testable import NestKit

/// B94: menus list only real models, levels and modes; the defaults name an engine; Codex
/// signs in from Settings; the usage meter shows the engines chosen.
@Suite struct ConcreteDefaultsTests {
    let claude = ModelCatalog(models: Fixture.models, defaultModel: "opus")
    let codex = ModelCatalog(models: Self.codexModels, defaultModel: "gpt-5.5-codex")

    static let codexModels = [
        ModelInfo(
            value: "gpt-5.5-codex", displayName: "GPT-5.5 Codex", description: "For coding",
            effortLevels: [.low, .high, .xhigh], supportsEffort: true, supportsAutoMode: true),
        ModelInfo(
            value: "gpt-5.5-mini", displayName: "GPT-5.5 Mini", description: "Fast",
            effortLevels: [], supportsEffort: false),
    ]

    @Test func theModelListNamesTheEnginesDefault() {
        let list = Fixture.decode(ModelList.self, "models")
        #expect(list.defaultModel == "opus")
        #expect(!list.models.contains { $0.value == "default" })
        let older = Fixture.decode(ModelList.self, json: #"{"models": [], "updated_at": null}"#)
        #expect(older.defaultModel == nil)
    }

    /// A chat from before B94 without a model shows the engine's default by name.
    @Test func noModelReadsAsTheEnginesDefault() {
        #expect(claude.label(for: nil) == "Opus 5.5")
        #expect(claude.isSelected(Fixture.models[0], current: nil))
        #expect(claude.info(for: nil)?.value == "opus")
        #expect(ModelCatalog(models: []).label(for: nil) == "Model")
        #expect(ModelCatalog(models: [], defaultModel: "gpt-7").label(for: nil) == "gpt-7")
    }

    @Test func thinkingIsMediumOrTheNearestLevel() {
        #expect(Effort.standard(supported: Effort.selectable) == .medium)
        #expect(Effort.standard(supported: [.low, .high]) == .low)
        #expect(Effort.standard(supported: [.high, .max]) == .high)
        #expect(Effort.standard(supported: [.xhigh]) == .xhigh)
        #expect(Effort.standard(supported: []) == nil)
        // Kept where the model takes it, the next level down, else the nearest to Medium.
        #expect(codex.effort(.xhigh, afterSwitchingTo: "gpt-5.5-codex") == .xhigh)
        #expect(codex.effort(.medium, afterSwitchingTo: "gpt-5.5-codex") == .low)
        #expect(codex.effort(nil, afterSwitchingTo: "gpt-5.5-codex") == .low)
        #expect(codex.effort(.high, afterSwitchingTo: "gpt-5.5-mini") == nil)
    }

    @Test func aNewChatsModeIsAlwaysARealMode() {
        #expect(claude.newChatPermission(nil, afterSwitchingTo: "opus", fallback: .plan) == .plan)
        #expect(
            claude.newChatPermission(nil, afterSwitchingTo: "haiku", fallback: .auto) == .default)
        #expect(
            claude.newChatPermission(.auto, afterSwitchingTo: "haiku", fallback: .plan) == .plan)
        #expect(claude.newChatPermission(.auto, afterSwitchingTo: "opus", fallback: .plan) == .auto)
    }

    @Test func agentDefaultsNameTheirEngineAndARealMode() throws {
        let decoded = Fixture.decode(
            AgentDefaults.self,
            json:
                #"{"provider": "codex", "model": "gpt-5.5-codex", "effort": "low", "permission_mode": "plan", "mode": "worktree"}"#
        )
        #expect(decoded.provider == "codex")
        #expect(decoded.permissionMode == .plan)
        // A daemon before B94 names no engine and may leave the mode to Claude Code.
        let older = Fixture.decode(
            AgentDefaults.self,
            json: #"{"model": null, "effort": null, "permission_mode": null, "mode": "in_place"}"#)
        #expect(older.provider == "claude")
        #expect(older.permissionMode == .default)
        let unknown = Fixture.decode(
            AgentDefaults.self, json: #"{"permission_mode": "dontAsk", "mode": "in_place"}"#)
        #expect(unknown.permissionMode == .default)
        let sent = try JSONSerialization.jsonObject(with: JSONEncoder().encode(decoded))
        #expect((sent as? [String: Any])?["provider"] as? String == "codex")
        #expect(AgentDefaults.standard.effort == .medium)
        #expect(AgentDefaults.standard.permissionMode == .default)
    }

    /// A new chat starts from the defaults: their engine, model, thinking and mode.
    @Test func aNewChatStartsFromTheDefaults() {
        let onCodex = AgentDefaults(
            provider: "codex", model: "gpt-5.5-codex", effort: .high, permissionMode: .plan,
            mode: .inPlace)
        #expect(
            NewChatChoices.from(onCodex, catalog: codex)
                == NewChatChoices(
                    provider: "codex", model: "gpt-5.5-codex", effort: .high, permission: .plan))
        // Before the daemon answered: Claude's default model, Medium, Ask.
        #expect(
            NewChatChoices.from(.standard, catalog: claude)
                == NewChatChoices(
                    provider: nil, model: "opus", effort: .medium, permission: .default))
        // Back on the defaults' engine before they name a model: its default model.
        let drafted = NewChatChoices(
            provider: "codex", model: "gpt-5.5-codex", effort: .low, permission: .plan)
        #expect(drafted.switching(to: nil, catalog: claude, defaults: .standard).model == "opus")
        var haiku = AgentDefaults.standard
        haiku.model = "haiku"
        haiku.effort = nil
        haiku.permissionMode = .auto
        // No thinking, and Auto left on a model without it.
        #expect(NewChatChoices.from(haiku, catalog: claude).effort == nil)
        #expect(NewChatChoices.from(haiku, catalog: claude).permission == .default)
    }

    /// Another engine starts on its own default model and the level nearest Medium.
    @Test func switchingEnginesTakesTheirConcreteDefaults() {
        let defaults = AgentDefaults(
            model: "opus", effort: .xhigh, permissionMode: .auto, mode: .inPlace)
        let draft = NewChatChoices.from(defaults, catalog: claude)
        let onCodex = draft.switching(to: "codex", catalog: codex, defaults: defaults)
        #expect(
            onCodex
                == NewChatChoices(
                    provider: "codex", model: "gpt-5.5-codex", effort: .low, permission: .auto))
        // Back on the defaults' engine, their model and thinking again.
        let back = onCodex.switching(to: "claude", catalog: claude, defaults: defaults)
        #expect(
            back == NewChatChoices(provider: nil, model: "opus", effort: .xhigh, permission: .auto))
        let chosen = draft.choosing("haiku", on: nil, catalog: claude, defaults: defaults)
        // Haiku takes no thinking and no Auto: Ask.
        #expect(
            chosen
                == NewChatChoices(provider: nil, model: "haiku", effort: nil, permission: .default))
    }

    /// The defaults on Codex: Claude is then the other engine, on its own default model.
    @Test func defaultsOnCodexMakeClaudeTheOtherEngine() {
        let defaults = AgentDefaults(
            provider: "codex", model: "gpt-5.5-mini", effort: nil, permissionMode: .acceptEdits,
            mode: .inPlace)
        let draft = NewChatChoices.from(defaults, catalog: codex)
        let onClaude = draft.switching(to: nil, catalog: claude, defaults: defaults)
        #expect(
            onClaude
                == NewChatChoices(
                    provider: nil, model: "opus", effort: .medium, permission: .acceptEdits))
    }
}

@MainActor @Suite struct ConcreteDefaultStoresTests {
    let api = FakeAPI()

    @Test func choosingACodexModelMakesCodexTheDefaultEngine() async throws {
        let store = AgentsStore(api: api)
        await store.load()
        #expect(store.defaultModel == "opus")
        #expect(store.catalog.defaultModel == "opus")
        let codex = ModelCatalog(models: ConcreteDefaultsTests.codexModels)
        try await store.setDefaultPermissionMode(.auto)

        try await store.setDefaultModel("gpt-5.5-mini", provider: "codex", catalog: codex)

        #expect(store.current.provider == "codex")
        #expect(store.current.model == "gpt-5.5-mini")
        // Mini takes no thinking and no Auto.
        #expect(store.current.effort == nil)
        #expect(store.current.permissionMode == .default)
        #expect(api.calls.last == "updateAgentDefaults codex gpt-5.5-mini nil default in_place")

        try await store.setDefaultModel("gpt-5.5-codex", provider: "codex", catalog: codex)
        #expect(store.current.effort == .low)
        try await store.setDefaultModel("opus")
        #expect((store.current.provider, store.current.effort) == ("claude", .low))
    }

    @Test func providersKeepEachEnginesDefaultModel() async {
        api.set {
            $0.providers = [
                ProviderInfo(name: "claude", displayName: "Claude"),
                ProviderInfo(name: "codex", displayName: "Codex", signedIn: true),
            ]
            $0.providerModels = ["codex": ConcreteDefaultsTests.codexModels]
            $0.providerDefaults = ["codex": "gpt-5.5-codex"]
        }
        let providers = ProvidersStore(api: api)
        await providers.load()
        let catalog = providers.catalog(for: "codex", claude: ModelCatalog(models: []))
        #expect(catalog.defaultModel == "gpt-5.5-codex")
        #expect(catalog.label(for: nil) == "GPT-5.5 Codex")
    }

    /// The pixie picker lists real models only; a pixie the daemon has not given a model
    /// yet shows its engine's default.
    @Test func thePixiePickerHasNoDefaultEntry() async {
        api.set {
            $0.providers = [
                ProviderInfo(name: "claude", displayName: "Claude"),
                ProviderInfo(name: "codex", displayName: "Codex", signedIn: true),
            ]
            $0.providerModels = ["codex": ConcreteDefaultsTests.codexModels]
            $0.providerDefaults = ["codex": "gpt-5.5-codex"]
        }
        let providers = ProvidersStore(api: api)
        await providers.load()
        let claude = ModelCatalog(models: Fixture.models, defaultModel: "opus")
        var pixie = Fixture.decode(Pixie.self, "pixie")
        pixie.provider = "codex"
        pixie.model = nil
        let picker = PixieModelPicker(pixie: pixie, providers: providers, claude: claude)
        #expect(picker.sections.map(\.entries.count) == [Fixture.models.count, 2])
        #expect(!picker.sections.flatMap(\.entries).contains { $0.title == "Default" })
        #expect(picker.value == "Codex · GPT-5.5 Codex")
        #expect(picker.runningModel == "gpt-5.5-codex")
        #expect(picker.sections[1].entries[0].checked)
        #expect(
            picker.sections[0].entries[0].request
                == UpdatePixieRequest(provider: "claude", model: "opus"))
    }
}

@MainActor @Suite struct CodexAccountTests {
    let api = FakeAPI()

    @Test func signsInThroughTheBrowserUntilTheDaemonSaysHowItWent() async throws {
        let accounts = AccountsStore(api: api)
        try await accounts.loadCodex()
        #expect(accounts.codex?.signedIn == false)

        let url = try await accounts.signInCodex()

        #expect(url.host() == "auth.openai.com")
        #expect(accounts.isSigningInCodex)
        try await accounts.cancelCodexSignIn()
        #expect(api.calls.contains("cancelCodexSignIn"))
        accounts.apply(
            Fixture.event(
                EventType.accountCodex,
                #"{"signed_in": false, "email": null, "plan": null, "checked_at": "2026-10-20T10:00:00Z", "error": "Access denied"}"#,
                session: nil))
        #expect(!accounts.isSigningInCodex)
        #expect(accounts.codexSignInError == "Access denied")
        // A newer sign in starts without the old error.
        _ = try await accounts.signInCodex()
        #expect(accounts.codexSignInError == nil)
        accounts.apply(
            Fixture.event(
                EventType.accountCodex,
                #"{"signed_in": true, "email": "me@example.com", "plan": "ChatGPT Plus", "checked_at": "2026-10-20T10:00:00Z", "error": null}"#,
                session: nil))
        #expect(accounts.codex?.plan == "ChatGPT Plus")
        #expect(accounts.codex?.email == "me@example.com")
        // Claude's account is left alone.
        #expect(accounts.claude == nil)
    }

    @Test func theCodexRowSaysWhoAndHow() {
        let date = Date(timeIntervalSince1970: 0)
        let signedIn = CodexLogin(
            signedIn: true, email: "me@example.com", plan: "ChatGPT Plus", checkedAt: date)
        #expect(AccountText.codexState(signedIn) == "Signed in")
        #expect(
            AccountText.codexState(CodexLogin(signedIn: false, checkedAt: date)) == "Signed out")
        #expect(AccountText.codexState(CodexLogin(signedIn: nil, checkedAt: date)) == "Not checked")
        #expect(AccountText.codexTitle(signedIn) == "me@example.com")
        #expect(
            AccountText.codexTitle(CodexLogin(signedIn: true, email: "", checkedAt: date))
                == "Codex")
        #expect(AccountText.codexTitle(nil) == "Codex")
    }

    @Test func aSignInThatCannotStartEndsAtOnce() async throws {
        api.fail("signInCodex")
        let accounts = AccountsStore(api: api)
        await #expect(throws: APIError.self) { _ = try await accounts.signInCodex() }
        #expect(!accounts.isSigningInCodex)
    }

    @Test func signsOut() async throws {
        api.set { $0.codexLogin.signedIn = true }
        let accounts = AccountsStore(api: api)
        try await accounts.loadCodex()
        let gate = AsyncStream<Void>.makeStream()
        api.set { $0.gates["signOutCodex"] = gate.stream }
        let out = Task { try await accounts.signOutCodex() }
        try await waitFor { accounts.isSigningOutCodex }
        gate.continuation.finish()
        try await out.value
        #expect(!accounts.isSigningOutCodex)
        #expect(accounts.codex?.signedIn == false)
    }

    /// Signing in or out may change the engines' lists and the defaults: both reload.
    @Test func anAccountChangeReloadsTheEnginesAndDefaults() async {
        let model = AppModel(api: api, events: ManualEventSource(), preferences: MemoryStore())
        model.live.route(
            Fixture.event(
                EventType.accountCodex,
                #"{"signed_in": true, "email": null, "plan": "ChatGPT Plus", "checked_at": "2026-10-20T10:00:00Z", "error": null}"#,
                session: nil))
        await model.live.engineReload?.value
        #expect(api.calls.suffix(4).contains("providers false"))
        #expect(api.calls.suffix(4).contains("agentDefaults"))
        #expect(model.accounts.codex?.plan == "ChatGPT Plus")
    }
}

@MainActor @Suite struct UsageMeterEnginesTests {
    let api = FakeAPI()

    func providers(_ list: [ProviderInfo]) async -> ProvidersStore {
        api.set { $0.providers = list }
        let store = ProvidersStore(api: api)
        await store.load()
        return store
    }

    static let three = [
        ProviderInfo(name: "claude", displayName: "Claude"),
        ProviderInfo(name: "codex", displayName: "Codex", signedIn: true),
        ProviderInfo(name: "gemini", displayName: "Gemini", signedIn: false),
    ]

    /// The meter stacks the engines left checked that are signed in, in the list's order.
    @Test func theMeterShowsTheCheckedEnginesSignedIn() async {
        let providers = await providers(Self.three)
        let usage = UsageStore(api: api)
        let now = Date()
        #expect(usage.meter(providers: providers, now: now).map(\.provider) == ["claude", "codex"])
        #expect(
            usage.meter(providers: providers, now: now, hidden: ["claude"]).map(\.provider)
                == ["codex"])
        #expect(
            usage.meter(providers: providers, now: now, hidden: ["codex"]).map(\.provider)
                == ["claude"])
        // Nothing checked and signed in left: Claude's line, so the meter stays.
        #expect(
            usage.meter(providers: providers, now: now, hidden: ["claude", "codex"])
                .map(\.provider) == ["claude"])
    }

    /// The Usage tab's list comes from the engine list, so a new engine shows up checked.
    @Test func theChoicesFollowTheEngineList() async {
        let usage = UsageStore(api: api)
        let empty = ProvidersStore(api: api)
        #expect(
            usage.meterEngines(providers: empty, hidden: [])
                == [UsageMeterEngine(provider: "claude", name: "Claude", detail: "", shown: true)])
        let providers = await providers(Self.three)
        #expect(
            usage.meterEngines(providers: providers, hidden: ["codex"]) == [
                UsageMeterEngine(provider: "claude", name: "Claude", detail: "", shown: true),
                UsageMeterEngine(provider: "codex", name: "Codex", detail: "", shown: false),
                UsageMeterEngine(
                    provider: "gemini", name: "Gemini", detail: "Not signed in", shown: true),
            ])
        #expect(
            usage.meterEngines(providers: providers, hidden: []).map(\.id) == [
                "claude", "codex", "gemini",
            ])
    }

    /// Kept on this Mac as the engines unchecked, so engines added later start checked.
    @Test func theChoiceIsKeptOnThisMac() {
        let store = MemoryStore()
        let settings = SettingsStore(store: store)
        #expect(settings.usageMeterHidden.isEmpty)
        #expect(settings.showsInUsageMeter("codex"))
        settings.setUsageMeter("codex", shown: false)
        settings.setUsageMeter("claude", shown: false)
        #expect(store.values["usage.meter.hidden"] == "claude,codex")
        #expect(!settings.showsInUsageMeter("codex"))
        #expect(SettingsStore(store: store).usageMeterHidden == ["claude", "codex"])
        settings.setUsageMeter("codex", shown: true)
        settings.setUsageMeter("claude", shown: true)
        #expect(store.values["usage.meter.hidden"] == nil)
        #expect(
            SettingsStore(store: MemoryStore(["usage.meter.hidden": ""])).usageMeterHidden.isEmpty)
    }
}
