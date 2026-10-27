import Foundation
import Testing

@testable import NestKit

/// The engines past Claude and Codex (B107): their state and sign-in from the daemon, what
/// Settings > Accounts offers for each, and that a new chat cannot choose one not ready.
@MainActor @Suite struct MoreEnginesTests {
    static let json = """
        {"providers": [
          {"name": "claude", "display_name": "Claude", "signed_in": null, "sign_in_hint": null,
           "account": null, "unsupported": [], "version": null, "tested": true,
           "git_guard": true, "state": "ready", "state_detail": null, "sign_in": "browser",
           "login_command": null},
          {"name": "opencode", "display_name": "OpenCode", "signed_in": true,
           "unsupported": ["rewind"], "version": "1.19.4", "tested": true, "git_guard": true,
           "state": "ready", "sign_in": "terminal", "login_command": "opencode auth login"},
          {"name": "gemini", "display_name": "Gemini CLI", "signed_in": false,
           "unsupported": [], "version": "0.65.0", "state": "ready", "sign_in": "api_key"},
          {"name": "cursor", "display_name": "Cursor agent", "signed_in": null,
           "unsupported": [], "tested": false, "git_guard": false, "state": "not_installed",
           "state_detail": "Install Cursor's CLI first.", "sign_in": "terminal",
           "login_command": "agent login"},
          {"name": "later", "display_name": "Later", "unsupported": [], "state": "warming",
           "sign_in": "telepathy"}
        ]}
        """

    let api = FakeAPI()
    let claude = ModelCatalog(models: Fixture.models, defaultModel: "opus")
    let free = ModelInfo(
        value: "opencode/free", displayName: "Free", description: "", effortLevels: [],
        supportsEffort: false)
    let flash = ModelInfo(
        value: "gemini-flash", displayName: "Flash", description: "", effortLevels: [],
        supportsEffort: false)

    init() {
        let providers = Fixture.decode(ProviderList.self, json: Self.json).providers
        let free = free
        let flash = flash
        api.set {
            $0.providers = providers
            $0.providerModels = ["opencode": [free], "gemini": [flash]]
        }
    }

    @Test func decodesTheNewFieldsAndStaysSafeWithUnknownValues() {
        let list = Fixture.decode(ProviderList.self, json: Self.json)
        let cursor = list.providers[3]
        #expect(cursor.state == .notInstalled)
        #expect(!cursor.tested)
        #expect(!cursor.gitGuard)
        #expect(cursor.signIn == .terminal)
        #expect(cursor.loginCommand == "agent login")
        #expect(cursor.stateDetail == "Install Cursor's CLI first.")
        #expect(list.providers[1].version == "1.19.4")
        let later = list.providers[4]
        #expect(later.state == .unknown)
        #expect(later.signIn == .unknown)
        #expect(!later.offeredForNewChats)
    }

    /// A daemon before B107 sends none of the new fields: Claude and Codex as before.
    @Test func anOlderDaemonsEnginesAreReadyBrowserSignIns() {
        let codex = Fixture.decode(ProviderList.self, json: ProviderDecodingTests.json)
            .providers[1]
        #expect(codex.state == .ready)
        #expect(codex.signIn == .browser)
        #expect(codex.tested)
        #expect(codex.gitGuard)
        #expect(codex.version == nil)
        #expect(codex.loginCommand == nil)
        // Signed out, it stays offered and says so at sending (B91).
        #expect(codex.offeredForNewChats)
    }

    /// More engines has one row per engine, each with its state in a word and its one
    /// action; the git warning is there for the engines Nest cannot guard.
    @Test func moreEnginesOffersEachEngineItsOneAction() {
        let providers = Fixture.decode(ProviderList.self, json: Self.json).providers
        let setups = EngineSetup.others(
            providers + [ProviderInfo(name: "codex", displayName: "Codex")])
        #expect(setups.map(\.name) == ["opencode", "gemini", "cursor", "later"])
        let byName = Dictionary(uniqueKeysWithValues: setups.map { ($0.name, $0) })

        // Signed in from Terminal, it is ready and needs nothing.
        let opencode = byName["opencode"]!
        #expect((opencode.state, opencode.action) == ("Ready", .none))
        #expect(opencode.ready)
        #expect(opencode.gitWarning == nil)
        #expect(opencode.labels.isEmpty)
        // Signed out, it signs in with its own command.
        var signedOut = providers[1]
        signedOut.signedIn = false
        let out = EngineSetup(signedOut)
        #expect((out.state, out.action) == ("Signed out", .signIn(command: "opencode auth login")))
        #expect(!out.ready)

        let gemini = byName["gemini"]!
        #expect(
            (gemini.state, gemini.action)
                == ("No key", .addKey(placeholder: "Paste your Gemini CLI API key")))
        var keyed = providers[2]
        keyed.signedIn = true
        #expect((EngineSetup(keyed).state, EngineSetup(keyed).action) == ("Ready", .removeKey))

        // Nest does not fetch Cursor's CLI: no Install, and no explanation shown.
        let cursor = byName["cursor"]!
        #expect((cursor.state, cursor.action) == ("Not installed", .none))
        #expect(cursor.failure == nil)
        #expect(cursor.labels == ["untested"])
        #expect(cursor.gitWarning == EngineSetup.gitWarningText)
        var ready = providers[3]
        ready.state = .ready
        ready.signedIn = false
        #expect(EngineSetup(ready).action == .signIn(command: "agent login"))

        var missing = providers[2]
        missing.state = .notInstalled
        #expect(EngineSetup(missing).action == .install(again: false))
        var failed = providers[2]
        failed.state = .installFailed
        failed.stateDetail = "npm could not be reached"
        let again = EngineSetup(failed)
        #expect((again.state, again.action) == ("Install failed", .install(again: true)))
        #expect(again.failure == "npm could not be reached")
    }

    /// A new chat lists only engines it can run on as choices: one not ready, or signed out
    /// where Nest checks it, is greyed under what it waits on.
    @Test func aNewChatCannotChooseAnEngineNotReady() async {
        let store = ProvidersStore(api: api)
        await store.load()
        // Models are asked only of ready engines.
        #expect(
            api.calls.filter { $0.hasPrefix("modelsFor") } == [
                "modelsFor opencode", "modelsFor gemini",
            ])
        let sections = store.modelSections(claude: claude, provider: nil, isDraft: true)
        #expect(
            sections.map(\.id) == ["claude", "opencode", "gemini", "cursor", "later"])
        let byID = Dictionary(uniqueKeysWithValues: sections.map { ($0.id, $0) })
        #expect(!byID["opencode"]!.isDisabled(free))
        #expect(byID["gemini"]!.isDisabled(flash))
        #expect(byID["gemini"]!.detail == "Not signed in")
        #expect(byID["cursor"]!.detail == "Not installed")
        #expect(!byID["claude"]!.isDisabled(Fixture.models[0]))

        // Signed in with a key, Gemini is a choice.
        api.set { $0.providers[2].signedIn = true }
        await store.load()
        let signedIn = store.modelSections(claude: claude, provider: nil, isDraft: true)
        #expect(signedIn.first { $0.id == "gemini" }?.isDisabled(flash) == false)

        // A chat that exists keeps its own engine's models.
        let existing = store.modelSections(claude: claude, provider: "opencode", isDraft: false)
        #expect(existing.map(\.id) == ["opencode"])
    }

    /// A pixie's picker offers only ready engines Nest can block git on, since the daemon
    /// refuses the others; a pixie already on one still shows its engine.
    @Test func aPixieCannotChooseAnEngineWithoutGitGuardOrNotReady() async {
        var cursor = Fixture.decode(ProviderList.self, json: Self.json).providers[3]
        #expect(!cursor.offeredForPixies)
        cursor.state = .ready
        // Ready, but Nest cannot block its git commands.
        #expect(!cursor.offeredForPixies)
        cursor.gitGuard = true
        #expect(cursor.offeredForPixies)

        let store = ProvidersStore(api: api)
        await store.load()
        var pixie = Fixture.decode(Pixie.self, "pixie")
        let picker = PixieModelPicker(pixie: pixie, providers: store, claude: claude)
        // Cursor (no git guard, not installed) and an engine in a state this app does not
        // know are left out.
        #expect(picker.sections.map(\.id) == ["claude", "opencode", "gemini"])
        pixie.provider = "cursor"
        let onCursor = PixieModelPicker(pixie: pixie, providers: store, claude: claude)
        #expect(onCursor.sections.map(\.id) == ["claude", "opencode", "gemini", "cursor"])
    }

    /// An account signed in from Terminal makes the engines' list stale; the same state
    /// again does not.
    @Test func seesAnAccountSignedInElsewhere() async {
        let store = ProvidersStore(api: api)
        await store.load()
        let gemini = EngineAccount(
            id: "gemini-main", provider: "gemini", title: "Gemini CLI", signedIn: false,
            active: true, first: true)
        #expect(!store.signInChanged([gemini]))
        var signedIn = gemini
        signedIn.signedIn = true
        #expect(store.signInChanged([signedIn]))
    }
}
