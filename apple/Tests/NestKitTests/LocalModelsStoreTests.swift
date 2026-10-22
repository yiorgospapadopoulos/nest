import Foundation
import Testing

@testable import NestKit

/// The local models (B106) as the app keeps them: the list, its engine, today's tokens, the
/// first run, the weak warning each device dismisses, and the chats whose server is down.
@MainActor @Suite struct LocalModelsStoreTests {
    let api = FakeAPI()

    static let ready = LocalModel(
        id: "lm_q", serverID: "s1", model: "qwen3-coder-30b", name: "qwen3-coder-30b",
        address: "localhost:1234", app: "LM Studio", context: 65_536)
    static let thinking = LocalModel(
        id: "lm_g", serverID: "s1", model: "gpt-oss-20b", name: "gpt-oss-20b",
        address: "localhost:1234", app: "LM Studio", context: 131_072, thinking: true)
    static let down = LocalModel(
        id: "lm_d", serverID: "s2", model: "devstral", name: "devstral-small-2",
        address: "localhost:11434", app: "Ollama", running: false)
    static let weak = LocalModel(
        id: "lm_w", serverID: "s1", model: "qwen3-4b", name: "qwen3-4b",
        address: "localhost:1234", app: "LM Studio", context: 32_768, tools: .weak)

    init() {
        api.set {
            $0.localList = LocalModelList(
                models: [Self.ready, Self.thinking, Self.down, Self.weak], engine: "claude")
            $0.localUsage = LocalUsage(todayTokens: 48_600)
        }
    }

    func loaded(_ preferences: MemoryStore? = nil) async -> LocalModelsStore {
        let store = LocalModelsStore(api: api, preferences: preferences)
        await store.load()
        return store
    }

    @Test func loadsTheModelsUsageAndSetup() async {
        let store = LocalModelsStore(api: api)
        #expect(!store.hasModels)
        #expect(!store.signInOptional)
        await store.load()
        #expect(store.models.map(\.id) == ["lm_q", "lm_g", "lm_d", "lm_w"])
        #expect(store.engine == "claude")
        #expect(store.hasModels)
        #expect(store.signInOptional)
        #expect(store.usage?.todayTokens == 48_600)
        #expect(store.setup == SetupState(firstRun: false, localOnly: false))
        #expect(!store.isFirstRun)
        #expect(api.calls == ["localModels", "setup", "localUsage"])
        #expect(store.model("local:lm_g") == Self.thinking)
        #expect(store.model("lm_g") == nil)
        #expect(store.model(nil) == nil)
    }

    /// A daemon without local models (before B106), or one call failing, keeps the rest.
    @Test func aFailedLoadKeepsWhatWasThere() async {
        let store = await loaded()
        api.fail("localModels")
        api.fail("setup")
        api.fail("localUsage")
        await store.load()
        #expect(store.models.count == 4)
        #expect(store.usage?.todayTokens == 48_600)
        api.set { $0.localUsage = LocalUsage(todayTokens: 9) }
        await store.loadUsage()
        #expect(store.usage?.todayTokens == 48_600)
    }

    /// Local only, or the first-run welcome, as the daemon says.
    @Test func localOnlyMakesSigningInOptional() async {
        api.set {
            $0.localList = LocalModelList(models: [], localOnly: true)
            $0.setup = SetupState(firstRun: true, localOnly: false)
        }
        let store = await loaded()
        #expect(store.localOnly)
        #expect(store.signInOptional)
        #expect(store.isFirstRun)
    }

    /// The menus look local models up as models: their name, and thinking only where they
    /// have it; never Auto.
    @Test func eachModelIsAModelInfo() async {
        let store = await loaded()
        let infos = store.infos
        #expect(infos.map(\.value) == ["local:lm_q", "local:lm_g", "local:lm_d", "local:lm_w"])
        #expect(infos[0].displayName == "qwen3-coder-30b")
        #expect(infos[0].description == "LM Studio · 64k context")
        #expect(infos[0].thinkingLevels.isEmpty)
        #expect(infos[1].thinkingLevels == [.low, .medium, .high])
        #expect(!infos[1].supportsAutoMode)
        #expect(infos[2].description == "Ollama is not running")
    }

    @Test func removingTakesTheModelAway() async throws {
        let store = await loaded()
        try await store.remove("lm_w")
        #expect(store.models.map(\.id) == ["lm_q", "lm_g", "lm_d"])
        #expect(api.calls.last == "removeLocalModel lm_w")
    }

    @Test func addingPutsTheModelsInTheList() async throws {
        let store = await loaded()
        let added = try await store.add(address: "localhost:8080", key: "k", models: ["m1"])
        #expect(added.map(\.id) == ["lm_m1"])
        #expect(store.models.last?.id == "lm_m1")
        #expect(api.calls.last == "addLocalModels localhost:8080 key=k m1")
        // Adding one already listed replaces it.
        _ = try await store.add(address: "localhost:8080", key: nil, models: ["m1"])
        #expect(store.models.filter { $0.id == "lm_m1" }.count == 1)
        #expect(store.models.last?.hasKey == false)
    }

    /// The engine shows at once and goes back when the daemon refuses it.
    @Test func theEngineChangesAndGoesBackOnFailure() async throws {
        let store = await loaded()
        try await store.setEngine("codex")
        #expect(store.engine == "codex")
        #expect(api.calls.last == "setLocalEngine codex")
        api.fail("setLocalEngine")
        await #expect(throws: APIError.self) { try await store.setEngine("claude") }
        #expect(store.engine == "codex")
    }

    /// Start runs the app's server; the list is read again for who answers now.
    @Test func startingAnAppReadsTheListAgain() async throws {
        let store = await loaded()
        try await store.start(.ollama)
        #expect(
            api.calls.suffix(4) == [
                "startLocalServer ollama", "localModels", "setup", "localUsage",
            ])
        #expect(store.starting.isEmpty)
        api.fail("startLocalServer", with: APIError.notFound("Ollama is not installed"))
        await #expect(throws: APIError.notFound("Ollama is not installed")) {
            try await store.start(.ollama)
        }
        #expect(store.starting.isEmpty)
    }

    @Test func choosingLocalOnlyEndsTheFirstRun() async throws {
        api.set { $0.setup = SetupState(firstRun: true, localOnly: false) }
        let store = await loaded()
        try await store.useLocalOnly()
        #expect(store.setup == SetupState(firstRun: false, localOnly: true))
        #expect(store.localOnly)
        #expect(!store.isFirstRun)
        #expect(api.calls.last == "useLocalOnly")

        api.set { $0.setup = SetupState(firstRun: true, localOnly: false) }
        let other = await loaded()
        try await other.finishSetup()
        #expect(!other.isFirstRun)
        #expect(api.calls.last == "finishSetup")
        // Before the setup was read, finishing still ends it.
        let fresh = LocalModelsStore(api: api)
        try await fresh.finishSetup()
        #expect(fresh.setup == SetupState(firstRun: false, localOnly: false))
    }

    /// The weak warning shows for a weak model until dismissed on this device, per model.
    @Test func theWeakWarningIsDismissedPerModelOnThisDevice() async {
        let preferences = MemoryStore()
        let store = await loaded(preferences)
        #expect(store.weakWarning(for: "local:lm_w") == Self.weak)
        #expect(store.weakWarning(for: "local:lm_q") == nil)
        #expect(store.weakWarning(for: "opus") == nil)
        store.dismissWarning("lm_w")
        #expect(store.weakWarning(for: "local:lm_w") == nil)
        #expect(preferences.values[LocalModelsStore.dismissedKey] == "lm_w")
        store.dismissWarning("lm_x")
        #expect(preferences.values[LocalModelsStore.dismissedKey] == "lm_w,lm_x")

        let again = await loaded(preferences)
        #expect(again.weakWarning(for: "local:lm_w") == nil)
        // Without a place to keep it, the dismissal lasts while the app runs.
        let memoryOnly = await loaded()
        memoryOnly.dismissWarning("lm_w")
        #expect(memoryOnly.weakWarning(for: "local:lm_w") == nil)
    }

    /// A refused send or a turn that ended on a down server shows the card; a new turn
    /// clears it.
    @Test func aChatRemembersItsDownServer() async {
        let store = await loaded()
        let down = LocalServerDown(app: "LM Studio", address: "localhost:1234", start: .lmstudio)
        store.markDown("c1", down)
        #expect(store.serverDown["c1"] == down)
        store.clearDown("c1")
        #expect(store.serverDown["c1"] == nil)

        store.apply(
            Fixture.event(
                EventType.sessionState,
                #"{"state": "failed", "error": "LM Studio is not running", "code": "local_server_down", "app": "LM Studio", "address": "localhost:1234", "start": "lmstudio"}"#,
                session: "c2"))
        #expect(store.serverDown["c2"] == down)
        store.apply(
            Fixture.event(
                EventType.sessionState, #"{"state": "failed", "error": "boom"}"#, session: "c2"))
        #expect(store.serverDown["c2"] == down)
        store.apply(
            Fixture.event(
                EventType.sessionState, #"{"state": "running", "error": null}"#, session: "c2"))
        #expect(store.serverDown["c2"] == nil)
        // An event without a chat changes nothing.
        store.apply(
            Fixture.event(
                EventType.sessionState, #"{"state": "failed", "code": "local_server_down"}"#,
                session: nil))
        #expect(store.serverDown.isEmpty)
    }

    @Test func eventsReadTheListAndTodaysTokensAgain() async {
        let store = await loaded()
        api.set {
            $0.localList.models = [Self.ready]
            $0.localUsage = LocalUsage(todayTokens: 50_000)
        }
        store.apply(Fixture.event(EventType.localModelsChanged, "{}", session: nil))
        await store.reload?.value
        #expect(store.models == [Self.ready])
        store.apply(
            Fixture.event(
                EventType.sessionResult,
                "{}"))
        await store.reload?.value
        #expect(store.usage?.todayTokens == 50_000)
        // Without local models a turn's end does not ask.
        api.set { $0.localList.models = [] }
        await store.load()
        let calls = api.calls.count
        store.apply(
            Fixture.event(
                EventType.sessionResult,
                "{}"))
        await store.reload?.value
        #expect(api.calls.count == calls)
        store.apply(Fixture.event(EventType.reposReordered, "{}", session: nil))
    }

    /// The top bar shows today's local tokens when no account is signed in.
    @Test func theChipShowsWhenNoAccountIsSignedIn() async {
        let store = await loaded()
        let signedOut = EngineAccount(
            id: "a", provider: "claude", title: "Claude", signedIn: false, active: true,
            first: true)
        var signedIn = signedOut
        signedIn.signedIn = true
        #expect(store.chip(accounts: [signedOut]) == "Local · 49k tokens today")
        #expect(store.chip(accounts: []) == "Local · 49k tokens today")
        #expect(store.chip(accounts: [signedOut, signedIn]) == nil)
        api.set { $0.localList.models = [] }
        await store.load()
        #expect(store.chip(accounts: [signedOut]) == nil)
        let fresh = LocalModelsStore(api: api)
        api.set { $0.localList = LocalModelList(models: [], localOnly: true) }
        await fresh.load()
        api.fail("localUsage")
        let noUsage = LocalModelsStore(api: api)
        await noUsage.load()
        #expect(noUsage.chip(accounts: []) == "Local · 0 tokens today")
    }
}

/// The Add local model sheet (B106): Find on this Mac with its choices, or an address
/// checked, then Add.
@MainActor @Suite struct AddLocalFlowTests {
    let api = FakeAPI()

    static let good = FoundModel(
        address: "localhost:1234", app: "LM Studio", model: "q30", name: "qwen3-coder-30b",
        context: 65_536)
    static let other = FoundModel(
        address: "localhost:1234", app: "LM Studio", model: "gpt", name: "gpt-oss-20b")
    static let weak = FoundModel(
        address: "localhost:1234", app: "LM Studio", model: "q4", name: "qwen3-4b",
        tools: .weak)
    static let ollama = FoundModel(
        address: "localhost:11434", app: "Ollama", model: "llama", name: "llama3.2:3b",
        tools: .unknown)
    static let added = FoundModel(
        address: "localhost:1234", app: "LM Studio", model: "old", name: "old", added: true)

    init() {
        api.set {
            $0.localFind = LocalFind(
                running: [Self.good, Self.other, Self.weak, Self.ollama, Self.added],
                downloaded: [
                    DownloadedModel(
                        name: "d", source: "Ollama models folder", path: "/d", hint: "h",
                        start: .ollama)
                ])
        }
    }

    func flow(_ tab: AddLocalFlow.Tab = .find) -> AddLocalFlow {
        AddLocalFlow(store: LocalModelsStore(api: api), tab: tab)
    }

    /// A model too big for this Mac's memory is not chosen, even when good at tools, on
    /// Find and on an address.
    @Test func aModelTooBigForMemoryIsNotChosen() async throws {
        var big = Self.good
        big.model = "big"
        big.memoryWarning = "Needs about 40 GB of this Mac's 24 GB."
        api.set {
            $0.localFind = LocalFind(running: [Self.good, big], downloaded: [])
            $0.localChecks["localhost:1234"] = LocalCheck(
                ok: true,
                server: LocalServerInfo(
                    address: "localhost:1234", app: nil, messages: true, responses: true,
                    chat: true),
                models: [big])
        }
        let flow = flow()
        try await flow.find()
        #expect(flow.isSelected(Self.good))
        #expect(!flow.isSelected(big))
        let address = self.flow(.address)
        address.address = "localhost:1234"
        try await address.checkAddress()
        #expect(!address.isSelected(big))
        #expect(!address.canAdd)
    }

    /// Models good at tools start chosen; weak, unknown and added ones do not.
    @Test func findChoosesTheModelsGoodAtTools() async throws {
        let flow = flow()
        #expect(flow.choices.isEmpty)
        #expect(flow.addTitle == "Add models")
        #expect(!flow.canAdd)
        try await flow.find()
        #expect(flow.found?.downloaded.count == 1)
        #expect(!flow.finding)
        #expect(flow.choices.map(\.model) == ["q30", "gpt", "q4", "llama", "old"])
        #expect(flow.isSelected(Self.good))
        #expect(flow.isSelected(Self.other))
        #expect(!flow.isSelected(Self.weak))
        #expect(!flow.isSelected(Self.ollama))
        #expect(flow.isSelected(Self.added))
        #expect(!flow.canToggle(Self.added))
        #expect(flow.addTitle == "Add 2 models")
        #expect(flow.canAdd)
        flow.toggle(Self.weak)
        flow.toggle(Self.other)
        flow.toggle(Self.added)
        #expect(flow.addTitle == "Add 2 models")
        #expect(flow.isSelected(Self.weak))
        #expect(!flow.isSelected(Self.other))
    }

    @Test func aFailedFindStopsLooking() async {
        api.fail("findLocalModels")
        let flow = flow()
        await #expect(throws: APIError.self) { try await flow.find() }
        #expect(!flow.finding)
        #expect(flow.found == nil)
    }

    /// Add sends each server's chosen models, with no key from Find.
    @Test func addSendsEachServersModels() async throws {
        let flow = flow()
        try await flow.find()
        flow.toggle(Self.ollama)
        try await flow.add()
        #expect(
            api.calls.suffix(2) == [
                "addLocalModels localhost:1234 key=none q30,gpt",
                "addLocalModels localhost:11434 key=none llama",
            ])
        #expect(flow.store.models.map(\.model) == ["q30", "gpt", "llama"])
        #expect(!flow.adding)
    }

    /// Enter address: Check with the key, the server's models chosen unless weak, then Add
    /// with the key.
    @Test func anAddressIsCheckedThenAdded() async throws {
        let server = LocalServerInfo(
            address: "localhost:8080", app: nil, messages: false, responses: false, chat: true)
        let model = FoundModel(address: "localhost:8080", model: "m", name: "M", tools: .unknown)
        let weak = FoundModel(address: "localhost:8080", model: "w", name: "W", tools: .weak)
        api.set {
            $0.localChecks["localhost:8080"] = LocalCheck(
                ok: true, server: server, models: [model, weak])
        }
        let flow = flow(.address)
        #expect(flow.checkLine == nil)
        #expect(!flow.canCheck)
        flow.address = "  localhost:8080 "
        flow.key = "secret"
        #expect(flow.canCheck)
        try await flow.checkAddress()
        #expect(api.calls.last == "checkLocalServer localhost:8080 key=secret")
        #expect(flow.checkLine?.ok == true)
        #expect(flow.choices.map(\.model) == ["m", "w"])
        #expect(flow.isSelected(model))
        #expect(!flow.isSelected(weak))
        #expect(!flow.checking)
        try await flow.add()
        #expect(api.calls.last == "addLocalModels localhost:8080 key=secret m")
    }

    /// A failed check lists nothing, says why, and sends no key when none was typed.
    @Test func aFailedCheckSaysWhy() async throws {
        let flow = flow(.address)
        flow.address = "localhost:8081"
        try await flow.checkAddress()
        #expect(api.calls.last == "checkLocalServer localhost:8081 key=none")
        #expect(flow.choices.isEmpty)
        #expect(flow.checkLine?.ok == false)
        #expect(flow.checkLine?.text.hasPrefix("Nothing answered at localhost:8081") == true)
        api.fail("checkLocalServer")
        await #expect(throws: APIError.self) { try await flow.checkAddress() }
        #expect(!flow.checking)
        // Switching tabs shows that tab's models.
        try await flow.find()
        flow.tab = .find
        #expect(flow.choices.count == 5)
    }

    /// Start runs the app, then looks again.
    @Test func startLooksAgain() async throws {
        let flow = flow()
        try await flow.start(.ollama)
        #expect(api.calls.contains("startLocalServer ollama"))
        #expect(api.calls.last == "findLocalModels")
    }

    /// An add the daemon refuses keeps the sheet's choices.
    @Test func aFailedAddKeepsTheChoices() async throws {
        let flow = flow()
        try await flow.find()
        api.fail("addLocalModels")
        await #expect(throws: APIError.self) { try await flow.add() }
        #expect(!flow.adding)
        #expect(flow.addTitle == "Add 2 models")
    }
}

/// Local models in every model menu (B106): looked up on any engine, listed in their own
/// section, greyed while their server is down, the weak ones warned.
@MainActor @Suite struct LocalModelMenuTests {
    let api = FakeAPI()

    init() {
        api.set {
            $0.providers =
                Fixture.decode(ProviderList.self, json: ProviderDecodingTests.json).providers
            $0.providerModels = ["codex": ProviderDecodingTests.codexModels]
            $0.providerDefaults = ["codex": "gpt-5.5-codex"]
            $0.localList = LocalModelList(
                models: [
                    LocalModelsStoreTests.ready, LocalModelsStoreTests.thinking,
                    LocalModelsStoreTests.down, LocalModelsStoreTests.weak,
                ], engine: "codex")
        }
    }

    func loaded() async -> ProvidersStore {
        let store = ProvidersStore(api: api)
        await store.load()
        await store.local.load()
        return store
    }

    static let claude = ModelCatalog(
        models: [
            ModelInfo(
                value: "opus", displayName: "Opus 5.5", description: "Most capable",
                effortLevels: [.low, .medium, .high], supportsEffort: true, supportsAutoMode: true)
        ], defaultModel: "opus")

    /// Every engine's catalog knows the local models by their values, without listing them.
    @Test func everyCatalogLooksUpLocalModels() async {
        let store = await loaded()
        for engine in [nil, "claude", "codex"] {
            let catalog = store.catalog(for: engine, claude: Self.claude)
            #expect(catalog.label(for: "local:lm_q") == "qwen3-coder-30b")
            #expect(catalog.thinkingLevels(for: "local:lm_q").isEmpty)
            #expect(catalog.thinkingLevels(for: "local:lm_g") == [.low, .medium, .high])
            #expect(!catalog.models.contains { $0.value.hasPrefix("local:") })
        }
        #expect(
            store.modelTitle("local:lm_q", on: "codex", claude: Self.claude) == "qwen3-coder-30b")
        #expect(
            store.modelTitle("gpt-5.5-mini", on: "codex", claude: Self.claude)
                == "Codex · GPT-5.5 Mini")
    }

    /// A new chat's menu ends with the Local section on the local engine; a chat that
    /// exists keeps its own engine for it.
    @Test func theLocalSectionFollowsTheEngines() async {
        let store = await loaded()
        let sections = store.modelSections(claude: Self.claude, provider: nil, isDraft: true)
        #expect(sections.map(\.id) == ["claude", "codex", "local"])
        let local = sections[2]
        #expect(local.title == "Local")
        #expect(local.detail == "On this Mac, free, no limits")
        #expect(local.local)
        #expect(local.provider == "codex")
        #expect(
            local.catalog.models.map(\.value) == [
                "local:lm_q", "local:lm_g", "local:lm_d", "local:lm_w",
            ])
        let entries = local.catalog.models
        #expect(!local.isDisabled(entries[0]))
        #expect(local.isDisabled(entries[2]))
        #expect(local.warns(entries[3]))
        #expect(!local.warns(entries[0]))
        #expect(!sections[0].isDisabled(entries[0]))
        // A local model is checked whatever engine the chat runs on.
        #expect(local.isSelected(entries[0], provider: nil, model: "local:lm_q"))
        #expect(local.isSelected(entries[0], provider: "codex", model: "local:lm_q"))
        // Opus is not checked while the chat is on a local model.
        let opus = sections[0].catalog.models[0]
        #expect(!sections[0].isSelected(opus, provider: nil, model: "local:lm_q"))

        let existing = store.modelSections(claude: Self.claude, provider: nil, isDraft: false)
        #expect(existing.map(\.id) == ["claude", "local"])
        #expect(existing[1].provider == "claude")
    }

    /// With one engine listed, the Model section and the Local one.
    @Test func oneEngineAndLocalModels() async {
        api.set { $0.providers = [] }
        let store = await loaded()
        let sections = store.modelSections(claude: Self.claude, provider: nil, isDraft: true)
        #expect(sections.map(\.title) == ["Model", "Local"])
    }

    /// No local models, no Local section.
    @Test func noLocalModelsNoSection() async {
        api.set { $0.localList = LocalModelList(models: []) }
        let store = await loaded()
        #expect(
            store.modelSections(claude: Self.claude, provider: nil, isDraft: true).map(\.id)
                == ["claude", "codex"])
    }

    /// A local chat's header has its own words, so no engine label; and no sign-in nag
    /// once local models make signing in optional.
    @Test func localChatsNeedNoEngineLabelOrSignIn() async throws {
        let store = await loaded()
        var session = Fixture.session("s1")
        session.provider = "codex"
        session.model = "local:lm_q"
        #expect(store.label(for: session) == nil)
        #expect(store.localModel(in: session) == LocalModelsStoreTests.ready)
        session.model = "gpt-5.5-mini"
        #expect(store.label(for: session) == "Codex")
        #expect(store.localModel(in: session) == nil)
        #expect(store.localModel(in: nil) == nil)
        #expect(store.signInHint(for: "codex") == nil)
        api.set { $0.localList = LocalModelList(models: []) }
        await store.local.load()
        #expect(store.signInHint(for: "codex") == ProviderDecodingTests.hint)
    }

    /// A pixie's picker lists the local models too, greyed or warned as in the menu.
    @Test func thePixiePickerHasTheLocalModels() async {
        let store = await loaded()
        let pixie = Fixture.decode(Pixie.self, "pixie")
        let picker = PixieModelPicker(pixie: pixie, providers: store, claude: Self.claude)
        let local = picker.sections.last!
        #expect(local.title == "Local")
        #expect(
            local.entries.map(\.id) == ["local:lm_q", "local:lm_g", "local:lm_d", "local:lm_w"])
        #expect(local.entries[2].disabled)
        #expect(local.entries[3].warns)
        #expect(!local.entries[0].disabled)
        // The pixie runs on Claude; a local model runs on the local engine.
        #expect(
            local.entries[0].request == UpdatePixieRequest(provider: "codex", model: "local:lm_q"))
        var onLocal = pixie
        onLocal.model = "local:lm_q"
        let chosen = PixieModelPicker(pixie: onLocal, providers: store, claude: Self.claude)
        #expect(chosen.sections.last?.entries[0].checked == true)
        #expect(chosen.value == "qwen3-coder-30b")
    }
}

/// Signing in is optional once local models run chats (B106).
@Suite struct OptionalSignInTextTests {
    @Test func aSignedOutAccountIsOptional() {
        let account = EngineAccount(
            id: "a", provider: "claude", title: "Claude", signedIn: false, active: true,
            first: true)
        #expect(AccountText.state(account, optional: true) == "Not signed in, optional")
        #expect(AccountText.state(account) == "Signed out")
        var signedIn = account
        signedIn.signedIn = true
        #expect(AccountText.state(signedIn, optional: true) == "Signed in")
    }

    @Test func configurationDoesNotAskToSignIn() {
        #expect(
            ConfigurationText.footer(signInOptional: false)
                == "Other engines appear here once you sign in to them under Accounts.")
        #expect(ConfigurationText.footer(signInOptional: true) == nil)
    }
}
