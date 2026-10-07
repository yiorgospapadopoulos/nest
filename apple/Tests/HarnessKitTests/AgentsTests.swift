import Foundation
import Testing

@testable import HarnessKit

@Suite struct ModelListTests {
    @Test func decodesClaudeCodesModelList() throws {
        let list = Fixture.decode(ModelList.self, "models")
        #expect(
            list.models.map(\.value) == [
                "default", "opus", "claude-fable-5-1", "sonnet", "haiku", "claude-opus-4-8",
            ])
        let first = try #require(list.models.first)
        #expect(first.id == "default")
        #expect(first.displayName == "Default (recommended)")
        #expect(first.description.hasPrefix("Opus 5.5"))
        #expect(first.effortLevels == [.low, .medium, .high, .xhigh, .max])
        #expect(list.updatedAt == Date(timeIntervalSince1970: 1_791_360_000))
    }

    @Test func dropsUnknownEffortLevels() {
        let sonnet = Fixture.models[3]
        #expect(sonnet.effortLevels == [.low, .medium, .high, .xhigh])
    }

    @Test func thinkingLevelsAreOrderedAndEmptyWithoutEffort() {
        let scrambled = ModelInfo(
            value: "x", displayName: "X", description: "", effortLevels: [.max, .low, .high],
            supportsEffort: true)
        #expect(scrambled.thinkingLevels == [.low, .high, .max])
        let haiku = Fixture.models[4]
        #expect(haiku.thinkingLevels.isEmpty)
        let switchedOff = ModelInfo(
            value: "y", displayName: "Y", description: "", effortLevels: [.low],
            supportsEffort: false)
        #expect(switchedOff.thinkingLevels.isEmpty)
    }

    @Test func aListWithoutATimestampDecodes() {
        let list = Fixture.decode(ModelList.self, json: #"{"models": [], "updated_at": null}"#)
        #expect(list.models.isEmpty)
        #expect(list.updatedAt == nil)
    }

    @Test func decodesTheAccountWithMissingFields() {
        let account = Fixture.decode(
            ClaudeAccount.self,
            json:
                #"{"display_name": "Sam", "email": null, "plan": "Claude Max", "organization": "Acme"}"#
        )
        #expect(
            account
                == ClaudeAccount(
                    displayName: "Sam", email: nil, plan: "Claude Max", organization: "Acme"))
    }

    @Test func defaultsRoundTripWithNulls() throws {
        let defaults = Fixture.decode(
            AgentDefaults.self,
            json: #"{"model": null, "effort": null, "permission_mode": "plan", "mode": "worktree"}"#
        )
        #expect(
            defaults
                == AgentDefaults(model: nil, effort: nil, permissionMode: .plan, mode: .worktree))
        let encoded = String(decoding: try HarnessJSON.encoder.encode(defaults), as: UTF8.self)
        #expect(
            encoded == #"{"effort":null,"mode":"worktree","model":null,"permission_mode":"plan"}"#)
        #expect(AgentDefaults.standard.mode == .inPlace)
        #expect(AgentDefaults.standard.permissionMode == .default)
    }

    @Test func unknownDefaultsReadAsTheStandardOnes() {
        let defaults = Fixture.decode(
            AgentDefaults.self,
            json:
                #"{"model": "opus", "effort": "ultra", "permission_mode": "auto", "mode": "cloud"}"#
        )
        #expect(
            defaults
                == AgentDefaults(
                    model: "opus", effort: nil, permissionMode: .default, mode: .inPlace))
        let missing = Fixture.decode(
            AgentDefaults.self, json: #"{"permission_mode": "acceptEdits", "mode": "in_place"}"#)
        #expect(missing.model == nil)
        #expect(missing.effort == nil)
        #expect(missing.permissionMode == .acceptEdits)
    }
}

@Suite struct EffortFallbackTests {
    let all = Effort.selectable

    @Test func keepsASupportedEffort() {
        #expect(Effort.fallback(.xhigh, supported: all) == .xhigh)
        #expect(Effort.fallback(.low, supported: [.low]) == .low)
    }

    @Test func stepsDownToTheHighestSupportedLevelBelow() {
        #expect(Effort.fallback(.max, supported: [.low, .medium, .high]) == .high)
        #expect(Effort.fallback(.xhigh, supported: [.low, .medium]) == .medium)
        #expect(Effort.fallback(.high, supported: [.low, .max]) == .low)
    }

    @Test func fallsBackToNoneWhenNothingFits() {
        #expect(Effort.fallback(.high, supported: []) == nil)
        #expect(Effort.fallback(.low, supported: [.medium, .high]) == nil)
    }

    @Test func noEffortOrAnUnknownOneStaysNone() {
        #expect(Effort.fallback(nil, supported: all) == nil)
        #expect(Effort.fallback(.unknown, supported: all) == nil)
    }
}

@MainActor
@Suite struct AgentsStoreTests {
    let api = FakeAPI()

    @Test func loadsModelsDefaultsAndAccount() async {
        let store = AgentsStore(api: api)
        #expect(store.models.isEmpty)
        #expect(store.defaults == nil)
        #expect(store.current == .standard)
        await store.load()
        #expect(store.models.count == 6)
        #expect(store.defaults?.model == "opus")
        #expect(store.current.effort == .xhigh)
        #expect(store.account?.plan == "Claude Max")
        #expect(api.calls == ["models", "agentDefaults", "account"])
    }

    @Test func eachPartLoadsOnItsOwn() async {
        let store = AgentsStore(api: api)
        await store.load()
        api.fail("models")
        api.fail("account")
        api.set { $0.agentDefaults.mode = .worktree }
        await store.load()
        #expect(store.models.count == 6)
        #expect(store.account?.displayName == "Sam")
        #expect(store.defaults?.mode == .worktree)

        let fresh = AgentsStore(api: api)
        api.fail("agentDefaults")
        await fresh.load()
        #expect(fresh.models.isEmpty)
        #expect(fresh.defaults == nil)
        #expect(fresh.account == nil)
    }

    @Test func labelsKnownDefaultAndUnknownModels() async {
        let store = AgentsStore(api: api)
        #expect(store.label(for: nil) == "Default")
        #expect(store.label(for: "claude-opus-4-1") == "claude-opus-4-1")
        await store.load()
        #expect(store.label(for: nil) == "Default (recommended)")
        #expect(store.label(for: "default") == "Default (recommended)")
        #expect(store.label(for: "claude-fable-5-1") == "Fable 5.1")
        #expect(store.label(for: "claude-opus-4-1") == "claude-opus-4-1")
        #expect(store.info(for: "opus")?.displayName == "Opus 5.5")
        #expect(store.info(for: "gpt") == nil)
    }

    @Test func marksTheCurrentModel() async {
        let store = AgentsStore(api: api)
        await store.load()
        let models = store.models
        #expect(models.filter { store.isSelected($0, current: nil) }.map(\.value) == ["default"])
        #expect(models.filter { store.isSelected($0, current: "haiku") }.map(\.value) == ["haiku"])
        #expect(models.filter { store.isSelected($0, current: "claude-x") }.isEmpty)
    }

    @Test func offersEachModelsOwnThinkingLevels() async {
        let store = AgentsStore(api: api)
        #expect(store.thinkingLevels(for: "opus") == Effort.selectable)
        await store.load()
        #expect(store.thinkingLevels(for: "opus") == Effort.selectable)
        #expect(store.thinkingLevels(for: "claude-fable-5-1") == [.low, .medium, .high])
        #expect(store.thinkingLevels(for: "haiku").isEmpty)
        #expect(store.thinkingLevels(for: "claude-unknown") == Effort.selectable)
    }

    @Test func switchingModelsAdjustsTheEffort() async {
        let store = AgentsStore(api: api)
        await store.load()
        #expect(store.effort(.max, afterSwitchingTo: "claude-fable-5-1") == .high)
        #expect(store.effort(.max, afterSwitchingTo: "haiku") == nil)
        #expect(store.effort(.xhigh, afterSwitchingTo: "sonnet") == .xhigh)
        #expect(store.effort(nil, afterSwitchingTo: "opus") == nil)
        #expect(store.effort(.max, afterSwitchingTo: "claude-unknown") == .max)
    }

    @Test func changesTheDefaultsOnTheDaemon() async throws {
        let store = AgentsStore(api: api)
        await store.load()
        try await store.setDefaultPermissionMode(.acceptEdits)
        try await store.setDefaultMode(.worktree)
        try await store.setDefaultEffort(.max)
        try await store.setDefaultEffort(nil)
        #expect(
            store.current
                == AgentDefaults(
                    model: "opus", effort: nil, permissionMode: .acceptEdits, mode: .worktree))
        #expect(
            Array(api.calls.dropFirst(3)) == [
                "updateAgentDefaults opus xhigh acceptEdits in_place",
                "updateAgentDefaults opus xhigh acceptEdits worktree",
                "updateAgentDefaults opus max acceptEdits worktree",
                "updateAgentDefaults opus nil acceptEdits worktree",
            ])
        #expect(api.state.withLock { $0.agentDefaults } == store.current)
    }

    @Test func aNewDefaultModelKeepsOnlyASupportedEffort() async throws {
        let store = AgentsStore(api: api)
        await store.load()
        try await store.setDefaultModel("claude-fable-5-1")
        #expect(store.current.model == "claude-fable-5-1")
        #expect(store.current.effort == .high)
        try await store.setDefaultModel("haiku")
        #expect(store.current.effort == nil)
    }

    @Test func changesBeforeLoadingStartFromTheStandardDefaults() async throws {
        let store = AgentsStore(api: api)
        try await store.setDefaultMode(.worktree)
        #expect(api.calls == ["updateAgentDefaults nil nil default worktree"])
        #expect(store.defaults?.mode == .worktree)
    }

    @Test func aRefusedChangeRestoresTheOldDefaults() async throws {
        let store = AgentsStore(api: api)
        await store.load()
        api.fail("updateAgentDefaults", with: APIError.invalidInput("Haiku has no effort"))
        await #expect(throws: APIError.self) { try await store.setDefaultEffort(.low) }
        #expect(store.current.effort == .xhigh)

        let unloaded = AgentsStore(api: api)
        await #expect(throws: APIError.self) { try await unloaded.setDefaultMode(.worktree) }
        #expect(unloaded.defaults == nil)
    }

    @Test func showsTheAccountWithFallbacks() async {
        let store = AgentsStore(api: api)
        #expect(store.accountName(fallback: "Mac User") == "Mac User")
        #expect(store.plan == "Claude")
        #expect(store.email == nil)
        await store.load()
        #expect(store.accountName(fallback: "Mac User") == "Sam")
        #expect(store.plan == "Claude Max")
        #expect(store.email == "me@example.com")

        api.set { $0.account = ClaudeAccount(displayName: "", email: "", plan: "") }
        await store.load()
        #expect(store.accountName(fallback: "Mac User") == "Mac User")
        #expect(store.plan == "Claude")
        #expect(store.email == nil)
    }

    @Test func aRefreshLoadsThemWithoutFailingTheSync() async {
        let model = AppModel(
            api: api, events: ManualEventSource(), preferences: MemoryStore())
        api.fail("models", with: APIError.notFound("Not Found"))
        await model.live.refresh()
        #expect(model.app.syncError == nil)
        #expect(model.agents.defaults?.model == "opus")
        #expect(model.agents.models.isEmpty)
    }
}

@MainActor
@Suite struct SessionModelTests {
    let api = FakeAPI()

    @Test func switchingAChatsModelCanCarryAnEffort() async throws {
        api.set { $0.sessions = [Fixture.session("s1")] }
        let store = SessionsStore(api: api, approvals: ApprovalsStore(api: api))
        try await store.load()
        try await store.setModel("s1", "claude-fable-5-1", effort: .high)
        try await store.setModel("s1", "opus")
        #expect(store.session("s1")?.model == "opus")
        #expect(store.session("s1")?.effort == .high)
    }
}
