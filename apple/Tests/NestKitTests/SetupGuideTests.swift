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

    /// Regression (B130): the pairing code showed before Nest was shared, so before the phone
    /// could reach it.
    @Test func thePairingCodeWaitsUntilNestIsShared() {
        let check = { (stage: String?) in
            SetupCheck(id: "tailscale", title: "", state: .missing, stage: stage)
        }
        #expect(TailscaleStage(nil) == .install)
        #expect(TailscaleStage(check("something new")) == .install)
        let stages = ["install", "connect", "share", "pair", "done"].map {
            TailscaleStage(check($0))
        }
        #expect(stages == [.install, .connect, .share, .pair, .done])
        #expect(stages.map(\.reachable) == [false, false, false, true, true])
    }

    @Test func sharingShowsItsAnswerAndAsksAgainOncePastTheSharingStep() async throws {
        let api = FakeAPI()
        let waiting = SetupCheck(
            id: "tailscale", title: "Tailscale", state: .missing, stage: "share")
        let https = SetupCheck(
            id: "tailscale", title: "Tailscale", state: .missing,
            message: "Turn on HTTPS for your tailnet at this link, then share again.",
            fix: .init(kind: .link, value: "https://login.tailscale.com/f/serve"), stage: "share")
        api.set {
            $0.setupChecks = [waiting]
            $0.tailscaleShare = https
        }
        let store = SetupChecksStore(api: api)
        await store.refresh()

        try await store.shareTailscale()
        #expect(store.checks == [https])
        #expect(api.calls.count { $0 == "setupChecks" } == 1)

        let shared = SetupCheck(id: "tailscale", title: "Tailscale", state: .missing, stage: "pair")
        api.set {
            $0.tailscaleShare = shared
            $0.setupChecks = [shared]
        }
        try await store.shareTailscale()
        #expect(store.checks == [shared])
        #expect(api.calls.count { $0 == "setupChecks" } == 2)
        #expect(!store.sharing)
    }

    @Test func checkNestPutsWhatMattersMostOnTop() {
        let checks = [
            SetupCheck(id: "fine", title: "", state: .ok),
            SetupCheck(id: "extra", title: "", state: .missing, importance: .optional),
            SetupCheck(id: "warned", title: "", state: .warning),
            SetupCheck(id: "lacking", title: "", state: .missing),
            SetupCheck(id: "hidden", title: "", state: .notApplicable),
            SetupCheck(id: "stops", title: "", state: .missing, importance: .required),
            SetupCheck(id: "also fine", title: "", state: .ok),
        ]
        #expect(
            SetupCheck.ranked(checks).map(\.id) == [
                "stops", "lacking", "warned", "extra", "fine", "also fine",
            ])
    }

    @Test func theChecksDecodeTheirImportanceAndStage() {
        let check = Fixture.decode(
            SetupCheck.self,
            json: """
                {"id": "tailscale", "title": "Tailscale and iPhone", "state": "missing",
                 "message": "", "detail": null, "fix": null, "importance": "required",
                 "stage": "share", "rank": 0}
                """)
        #expect(check.importance == .required)
        #expect(check.stage == "share")
        #expect(check.rank == 0)
    }

    /// Regression (B130): a report made from the app said "Checked in the app." for what only
    /// the app can answer.
    @Test func theReportCarriesTheAppsOwnAnswers() async throws {
        let api = FakeAPI()
        let store = SetupChecksStore(api: api)
        let answers = SystemAnswers(
            notifications: .refused, microphone: .allowed, speech: .allowed, accessibility: true
        ).reportChecks
        _ = try await store.makeReport(answers: answers)

        let sent = try #require(api.state.withLock { $0.reportAnswers })
        #expect(sent.map(\.id) == ["notifications", "dictation", "permissions"])
        #expect(sent.map(\.state) == [.missing, .ok, .ok])
        let body = try #require(
            String(data: try NestJSON.encoder.encode(SetupReportAsk(checks: sent)), encoding: .utf8)
        )
        #expect(body.contains(#""id":"notifications""#))
        #expect(body.contains(#""state":"missing""#))
    }

    @Test func theReportsIssueAddressIsRead() {
        let report = Fixture.decode(
            SetupReport.self,
            json: """
                {"path": "/r.txt", "text": "Nest", "issue_url": "https://github.com/x/new",
                 "attach_file": true}
                """)
        #expect(report.issueURL == "https://github.com/x/new")
        #expect(report.attachFile)
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

    private static let update = UpdateUnderWay(
        fromVersion: "0.1.1", toVersion: "0.1.2", startedAt: "2026-11-07T10:00:00+00:00")

    @Test func theDaemonDownScreenShowsOnlyAtLaunchAfterASecondFailure() {
        var watch = DaemonDownWatch()
        var starts = false
        starts = watch.note(.reconnecting(attempt: 1, delay: 1), remote: false)
        #expect(!starts)
        #expect(!watch.isDown)
        starts = watch.note(.reconnecting(attempt: 2, delay: 1), remote: false)
        #expect(starts)
        watch.startFinished()
        starts = watch.note(.reconnecting(attempt: 2, delay: 1), remote: false)
        #expect(!starts)
        #expect(watch.screen == .down)
        // Try again starts over from the first attempt: the screen stays until it connects.
        starts = watch.note(.reconnecting(attempt: 1, delay: 1), remote: false)
        #expect(!starts)
        #expect(watch.isDown)
        starts = watch.note(.connected, remote: false)
        #expect(!starts)
        #expect(!watch.isDown)
        starts = watch.note(.reconnecting(attempt: 5, delay: 1), remote: false)
        #expect(!starts)
        #expect(!watch.isDown)

        var remote = DaemonDownWatch()
        starts = remote.note(.reconnecting(attempt: 5, delay: 1), remote: true)
        #expect(!starts)
        #expect(!remote.isDown)
    }

    /// Regression (B130): the repair line showed at once, asking the user to install again
    /// for what starting the service fixes. It starts once by itself first.
    @Test func theAppStartsTheServiceOnceBeforeShowingTheLine() {
        var watch = DaemonDownWatch()
        var starts = false
        starts = watch.note(.reconnecting(attempt: 2, delay: 1), remote: false)
        #expect(starts)
        // While the start runs, later failures neither start it again nor show the line.
        starts = watch.note(.reconnecting(attempt: 3, delay: 1), remote: false)
        #expect(!starts)
        #expect(watch.screen == .none)
        watch.startFinished()
        starts = watch.note(.reconnecting(attempt: 1, delay: 1), remote: false)
        #expect(!starts)
        #expect(watch.screen == .none)
        starts = watch.note(.reconnecting(attempt: 2, delay: 1), remote: false)
        #expect(!starts)
        #expect(watch.screen == .down)
    }

    /// Regression (B130): during an update the daemon-down screen asked for the repair line.
    @Test func anUpdateUnderWayShowsItsProgressAndNeverTheLine() {
        var watch = DaemonDownWatch()
        var starts = false
        starts = watch.note(update: Self.update)
        #expect(!starts)
        starts = watch.note(.reconnecting(attempt: 2, delay: 1), remote: false)
        #expect(!starts)
        #expect(watch.screen == .updating(Self.update))
        starts = watch.note(.reconnecting(attempt: 9, delay: 1), remote: false)
        #expect(!starts)
        #expect(watch.screen == .updating(Self.update))
        // The watcher cleared it but the daemon is not back: the service starts once, as at
        // launch.
        starts = watch.note(update: nil)
        #expect(starts)
        #expect(watch.screen == .none)
        starts = watch.note(.connected, remote: false)
        #expect(!starts)
        starts = watch.note(update: Self.update)
        #expect(!starts)
        #expect(!watch.isDown)
    }

    @Test func anUpdatesNoteSaysWhenItIsSlowAndWhenItIsLeftOver() throws {
        let started = try #require(Self.update.started)
        #expect(!Self.update.isSlow(at: started.addingTimeInterval(14)))
        #expect(Self.update.isSlow(at: started.addingTimeInterval(15)))
        #expect(Self.update.isUnderWay(at: started.addingTimeInterval(299)))
        #expect(!Self.update.isUnderWay(at: started.addingTimeInterval(300)))
        let micro = UpdateUnderWay(
            fromVersion: "a", toVersion: "b", startedAt: "2026-11-07T10:00:00.123456+00:00")
        #expect(micro.started?.timeIntervalSince(started) ?? 0 > 0.12)
    }
}

@Suite struct SystemAnswersTests {
    private static let daemon = ["notifications", "dictation", "permissions", "git"].map {
        SetupCheck(id: $0, title: $0, state: .notApplicable, message: "Checked in the app.")
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
        #expect(checks.values.filter { $0.message == "Checked in the app." }.map(\.id) == ["git"])
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
