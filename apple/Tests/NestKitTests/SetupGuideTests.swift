import Foundation
import Testing

@testable import NestKit

@MainActor
@Suite struct SetupGuideTests {
    @Test func theEngineCannotBeSkippedOrPassedUntilItIsReady() {
        let flow = SetupFlow(firstRun: true)
        #expect(!SetupStep.engine.canSkip)
        flow.skip()
        #expect(flow.step == .engine)
        #expect(flow.skipped.isEmpty)
        #expect(!flow.canContinue(engineReady: false))
        flow.moveOn(engineReady: false)
        #expect(flow.step == .engine)
        flow.moveOn(engineReady: true)
        #expect(flow.step == .git)
    }

    @Test func everyOtherStepMovesOnWhateverItsState() {
        let flow = SetupFlow(firstRun: true)
        flow.open(.github)
        flow.skip()
        #expect(flow.step == .service)
        #expect(flow.skipped == [.github])
        flow.moveOn(engineReady: false)
        #expect(flow.step == .tailscale)
    }

    @Test func aFirstRunNeedsAnEngineToFinishAndAReopenedGuideDoesNot() {
        #expect(!SetupFlow(firstRun: true).canFinish(engineReady: false))
        #expect(SetupFlow(firstRun: true).canFinish(engineReady: true))
        #expect(SetupFlow(firstRun: false).canFinish(engineReady: false))
    }

    @Test func marksNeverLeaveADoneStepLookingUndone() {
        #expect(SetupMark(.ok, open: true, skipped: true) == .ok)
        #expect(SetupMark(.missing, open: true, skipped: true) == .now)
        #expect(SetupMark(.missing, open: false, skipped: true) == .skipped)
        #expect(SetupMark(nil, open: false, skipped: false) == .todo)
    }

    private static func info(_ value: String, _ name: String) -> ModelInfo {
        ModelInfo(
            value: value, displayName: name, description: "", effortLevels: [],
            supportsEffort: false)
    }

    private static func account(_ provider: String, signedIn: Bool) -> EngineAccount {
        Fixture.decode(
            EngineAccount.self,
            json: """
                {"id": "\(provider)-1", "provider": "\(provider)", "title": "x", "active": true,
                 "first": true, "signed_in": \(signedIn), "signing_in": false, "limits": []}
                """)
    }

    @Test func theFirstChatTakesTheCheapestModelOfTheEngineSignedIn() {
        let catalogs = [
            "claude": ModelCatalog(models: [Self.info("opus", "Opus"), Self.info("h", "Haiku 4")]),
            "codex": ModelCatalog(models: [Self.info("gpt", "GPT")], defaultModel: "gpt"),
        ]
        let choose = { (accounts: [EngineAccount]) in
            FirstChatModel.choose(
                accounts: accounts, catalog: { catalogs[$0] ?? ModelCatalog(models: []) },
                local: [Self.info("local:q", "qwen")], defaultProvider: "claude")
        }
        #expect(
            choose([Self.account("claude", signedIn: true)])
                == FirstChatModel(provider: "claude", model: "h"))
        #expect(
            choose([
                Self.account("claude", signedIn: false), Self.account("codex", signedIn: true),
            ]) == FirstChatModel(provider: "codex", model: "gpt"))
        #expect(choose([]) == FirstChatModel(provider: "claude", model: "local:q"))
    }

    @Test func tailscaleStageFollowsTheFix() {
        let check = { (fix: String?) in
            SetupCheck(
                id: "tailscale", title: "", state: .missing,
                fix: fix.map { .init(kind: .command, value: $0) })
        }
        #expect(TailscaleStage(nil) == .off)
        #expect(TailscaleStage(check("tailscale up")) == .off)
        #expect(TailscaleStage(check("tailscale serve --bg 8765")) == .unshared)
        #expect(TailscaleStage(check(nil)) == .shared)
    }

    @Test func aLaterAnswerOfTheChecksWinsAndAFailedOneKeepsThem() async throws {
        let api = FakeAPI()
        let check = SetupCheck(id: "git", title: "git", state: .ok)
        api.set { $0.setupChecks = [check] }
        let store = SetupChecksStore(api: api)
        await store.refresh()
        #expect(store.checks == [check])
        api.fail("setupChecks", with: APIError.server(status: 500, detail: "no"))
        await store.refresh()
        #expect(store.checks == [check])
        #expect(!store.checking)
    }

    @Test func aRefusedNtfyChangeGoesBack() async throws {
        let api = FakeAPI()
        let store = NotificationRulesStore(api: api)
        try await store.load()
        try await store.changeNtfy { $0.topic = "a-long-random-topic" }
        #expect(store.rules?.ntfy.topic == "a-long-random-topic")
        api.fail("updateNotificationRules", with: APIError.server(status: 422, detail: "no"))
        await #expect(throws: (any Error).self) {
            try await store.changeNtfy { $0.enabled = true }
        }
        #expect(store.rules?.ntfy.enabled == false)
    }

    @Test func theDaemonDownScreenShowsOnlyAtLaunchAfterASecondFailure() {
        var watch = DaemonDownWatch()
        watch.note(.reconnecting(attempt: 1, delay: 1), remote: false)
        #expect(!watch.isDown)
        watch.note(.reconnecting(attempt: 2, delay: 1), remote: false)
        #expect(watch.isDown)
        // Try again starts over from the first attempt: the screen stays until it connects.
        watch.note(.reconnecting(attempt: 1, delay: 1), remote: false)
        #expect(watch.isDown)
        watch.note(.connected, remote: false)
        #expect(!watch.isDown)
        watch.note(.reconnecting(attempt: 5, delay: 1), remote: false)
        #expect(!watch.isDown)

        var remote = DaemonDownWatch()
        remote.note(.reconnecting(attempt: 5, delay: 1), remote: true)
        #expect(!remote.isDown)
    }
}

@Suite struct SystemAnswersTests {
    private static let daemon = ["notifications", "dictation", "permissions", "git"].map {
        SetupCheck(id: $0, title: $0, state: .notApplicable, message: "The app checks this.")
    }

    private func filled(_ answers: SystemAnswers) -> [String: SetupCheck] {
        Dictionary(uniqueKeysWithValues: answers.filling(Self.daemon).map { ($0.id, $0) })
    }

    @Test func theAppsAnswersReplaceTheDaemons() {
        let checks = filled(
            SystemAnswers(
                notifications: .allowed, microphone: .allowed, speech: .allowed,
                accessibility: true))
        #expect(checks["notifications"]?.state == .ok)
        #expect(checks["dictation"]?.state == .ok)
        #expect(checks["permissions"]?.state == .ok)
        #expect(checks.values.filter { $0.message == "The app checks this." }.map(\.id) == ["git"])
    }

    @Test func aRefusalLinksToSystemSettings() {
        let checks = filled(
            SystemAnswers(notifications: .refused, microphone: .allowed, speech: .refused))
        #expect(checks["notifications"]?.state == .missing)
        #expect(checks["notifications"]?.fix?.value == SystemAnswers.notificationSettings)
        #expect(checks["dictation"]?.state == .missing)
        #expect(checks["dictation"]?.message == "Speech Recognition: refused")
        #expect(checks["dictation"]?.fix?.value == SystemAnswers.speechSettings)
    }
}
