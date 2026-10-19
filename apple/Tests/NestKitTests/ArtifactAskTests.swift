import Foundation
import Testing
import UniformTypeIdentifiers

@testable import NestKit

/// B88 stage 4: a page reads the user's Claude usage and asks Claude small things, and the
/// reader shows the asks; `<input type=file accept>` narrows the open panel.
@MainActor @Suite struct ArtifactAskTests {
    let api = FakeAPI()
    nonisolated static let now = Fixture.date("2026-10-17T10:00:00Z")

    static func request(_ method: String, _ params: Any) -> [String: Any] {
        ["nest": 1, "id": "r1", "method": method, "params": params]
    }

    static func failure(_ message: ArtifactBridge.Message) -> ArtifactBridge.Code? {
        ArtifactBridgeTests.failure(message)
    }

    static func code(_ reply: ArtifactBridge.Reply?) -> ArtifactBridge.Code? {
        ArtifactBridgeTests.code(reply)
    }

    static func message(_ reply: ArtifactBridge.Reply?) -> String? {
        ArtifactPageDataTests.message(reply)
    }

    static var utc: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar
    }

    func store(now: @escaping @Sendable () -> Date = { ArtifactAskTests.now }) -> ArtifactsStore {
        api.set { $0.artifacts = [Fixture.artifact(kind: "html")] }
        return ArtifactsStore(api: api, calendar: Self.utc, now: now)
    }

    // MARK: Models

    @Test func answersAndAskEventsDecode() {
        let answer = Fixture.decode(
            ArtifactAnswer.self, json: #"{"text": "A haiku", "remaining": 17, "limit": 30}"#)
        #expect(answer == ArtifactAnswer(text: "A haiku", remaining: 17, limit: 30))
        // Without a limit, the default of 20.
        let plain = Fixture.decode(ArtifactAnswer.self, json: #"{"text": "x", "remaining": 3}"#)
        #expect(plain.limit == 20)

        let started = Fixture.event(
            EventType.artifactAsk, #"{"artifact_id": "a1", "state": "started", "remaining": 19}"#,
            session: nil)
        #expect(
            started.body
                == .artifactAsk(
                    ArtifactAskEvent(artifactID: "a1", state: .started, remaining: 19, limit: 20)))
        let finished = Fixture.event(
            EventType.artifactAsk,
            #"{"artifact_id": "a1", "state": "finished", "remaining": 18, "limit": 25}"#,
            session: nil)
        #expect(
            finished.body
                == .artifactAsk(
                    ArtifactAskEvent(artifactID: "a1", state: .finished, remaining: 18, limit: 25)))
    }

    @Test func theLineCountsTodaysAsks() {
        #expect(ArtifactAskCount(remaining: 17, limit: 20).text == "3 of 20 asks today")
        #expect(ArtifactAskCount(remaining: 0, limit: 20).text == "20 of 20 asks today")
        #expect(ArtifactAskCount(remaining: 25, limit: 20).text == "0 of 20 asks today")
        let artifact = Fixture.artifact(kind: "html")
        #expect(
            ArtifactText.line(
                artifact, author: .agent, saved: Self.now, now: Self.now, stored: 2_000,
                asks: ArtifactAskCount(remaining: 19, limit: 20))
                == "HTML · Pick a queue · saved now · 2 KB stored · 1 of 20 asks today")
        #expect(ArtifactText.asking == "Asking Claude\u{2026}")
    }

    @Test func aUsageSnapshotHasTheLimitsAndTodaysAndTheWeeksTokens() {
        var today = Fixture.usagePeriod
        today.sessions = 3
        let value = ArtifactPageUsage.value(
            limits: Fixture.usageLimits, today: today, week: Fixture.usagePeriod)
        #expect(
            value
                == .object([
                    "limits": .object([
                        "five_hour": .object([
                            "utilization": .number(0.3),
                            "resets_at": .string("2026-10-06T18:30:00Z"),
                        ]),
                        "seven_day": .null,
                    ]),
                    "today": .object(["tokens": .number(15_006_600), "sessions": .number(3)]),
                    "week": .object(["tokens": .number(15_006_600), "sessions": .number(74)]),
                ]))
        var limits = Fixture.usageLimits
        limits.fiveHour?.resetsAt = nil
        let open = ArtifactPageUsage.value(
            limits: limits, today: Fixture.usagePeriod, week: Fixture.usagePeriod)
        guard case .object(let fields) = open, case .object(let windows) = fields["limits"],
            case .object(let five) = windows["five_hour"]
        else {
            Issue.record("not a snapshot")
            return
        }
        #expect(five["resets_at"] == .null)
    }

    // MARK: Parsing

    @Test func askTakesAPromptAndAnOptionalSystemText() {
        #expect(
            ArtifactBridge.parse(Self.request("ask", ["prompt": "A haiku"]))
                == .call(id: "r1", .ask(prompt: "A haiku", system: nil)))
        #expect(
            ArtifactBridge.parse(Self.request("ask", ["prompt": "x", "system": "Be brief"]))
                == .call(id: "r1", .ask(prompt: "x", system: "Be brief")))
        let longest = String(repeating: "p", count: 8_000)
        let system = String(repeating: "s", count: 4_000)
        #expect(
            ArtifactBridge.parse(Self.request("ask", ["prompt": longest, "system": system]))
                == .call(id: "r1", .ask(prompt: longest, system: system)))
        for params: [String: Any] in [
            [:], ["prompt": ""], ["prompt": 3], ["prompt": longest + "p"],
            ["prompt": "x", "system": 4], ["prompt": "x", "system": system + "s"],
        ] {
            #expect(
                Self.failure(ArtifactBridge.parse(Self.request("ask", params))) == .badRequest,
                "\(params)")
        }
        let large = String(repeating: "x", count: 15 * 1024)
        #expect(
            Self.failure(ArtifactBridge.parse(Self.request("ask", ["prompt": "x", "pad": large])))
                == nil)
        let over = String(repeating: "x", count: 16 * 1024)
        #expect(
            Self.failure(ArtifactBridge.parse(Self.request("ask", ["prompt": "x", "pad": over])))
                == .tooLarge)
        #expect(ArtifactBridge.parse(Self.request("usage", [:])) == .call(id: "r1", .usage))
        #expect(ArtifactBridge.methods.isSuperset(of: ["usage", "ask"]))
        #expect(ArtifactBridge.Code.budget.rawValue == "budget")
        #expect(ArtifactBridge.Code.disabled.rawValue == "disabled")
    }

    // MARK: The session

    final class Calls {
        var asked: [(String, String?)] = []
        var askFailure: (any Error)?
        var usageFailure: (any Error)?
    }

    static let snapshot = ArtifactBridge.Value.object(["today": .number(1)])

    static func session(_ calls: Calls) -> ArtifactBridgeSession {
        ArtifactBridgeSession(
            prompt: ArtifactLinkPrompt(),
            usage: {
                if let failure = calls.usageFailure {
                    throw failure
                }
                return snapshot
            },
            ask: { prompt, system in
                if let failure = calls.askFailure {
                    throw failure
                }
                calls.asked.append((prompt, system))
                return ArtifactAnswer(text: "Leaves fall", remaining: 19, limit: 20)
            }
        ) { _ in }
    }

    @Test func askRepliesWithTheTextAndWhatIsLeft() async {
        let calls = Calls()
        let session = Self.session(calls)
        #expect(
            await session.receive(Self.request("ask", ["prompt": "A haiku", "system": "Short"]))
                == ArtifactBridge.Reply(
                    "r1",
                    .success(
                        .object(["text": .string("Leaves fall"), "remaining": .number(19)]))))
        #expect(calls.asked.map(\.0) == ["A haiku"])
        #expect(calls.asked.map(\.1) == ["Short"])
    }

    @Test func askFailuresGetTheirCodes() async {
        let calls = Calls()
        let session = Self.session(calls)
        let ask = Self.request("ask", ["prompt": "x"])
        let cases: [(any Error, ArtifactBridge.Code, String?)] = [
            (
                APIError.rateLimited("All 20 asks are used; more at 00:00.", retryAfter: nil),
                .budget, "All 20 asks are used; more at 00:00."
            ),
            (APIError.server(status: 403, detail: "Asking is off."), .disabled, "Asking is off."),
            (APIError.conflict("Already asking."), .busy, "Already asking."),
            (APIError.server(status: 500, detail: "boom"), .unavailable, nil),
            (APIError.transport("offline"), .unavailable, nil),
        ]
        for (error, code, text) in cases {
            calls.askFailure = error
            let reply = await session.receive(ask)
            #expect(Self.code(reply) == code, "\(error)")
            if let text {
                #expect(Self.message(reply) == text)
            }
        }
        #expect(
            Self.message(await session.receive(ask))
                == "Claude could not answer: offline")
        let none = ArtifactBridgeSession(prompt: ArtifactLinkPrompt()) { _ in }
        #expect(Self.code(await none.receive(ask)) == .unavailable)
        #expect(Self.code(await none.receive(Self.request("usage", [:]))) == .unavailable)
    }

    @Test func usageEventsReachOnlyAPageThatAskedForUsage() async {
        let calls = Calls()
        let session = Self.session(calls)
        let fresh = ArtifactBridge.Value.object(["today": .number(2)])
        #expect(session.usageEvents(for: fresh).isEmpty)
        calls.usageFailure = APIError.transport("offline")
        #expect(Self.code(await session.receive(Self.request("usage", [:]))) == .unavailable)
        // Asking once, even when that failed, is enough to hear of changes.
        #expect(
            session.usageEvents(for: fresh) == [
                .object(["nest": .number(1), "event": .string("usage"), "usage": fresh])
            ])
        calls.usageFailure = nil
        #expect(
            await session.receive(Self.request("usage", [:]))
                == ArtifactBridge.Reply("r1", .success(Self.snapshot)))
    }

    // MARK: The store

    @Test func usageIsReadOnceAMinute() async throws {
        let clock = Clock(Self.now)
        let store = store(now: { clock.now })
        let first = try await store.pageUsage()
        #expect(
            api.calls == [
                "usageLimits", "usagePeriod day 2026-10-17", "usagePeriod week 2026-10-17",
            ])
        clock.now = Self.now.addingTimeInterval(59)
        #expect(try await store.pageUsage() == first)
        #expect(api.calls.count == 3)
        clock.now = Self.now.addingTimeInterval(60)
        _ = try await store.pageUsage()
        #expect(api.calls.count == 6)
    }

    @Test func aUsageUpdateReachesListeningPagesWithTheNewLimits() async throws {
        let store = store()
        var heard: [ArtifactBridge.Value] = []
        let token = store.observeUsage { heard.append($0) }
        let update = Fixture.event(
            EventType.usageUpdated, #"{"five_hour": {"utilization": 0.5, "resets_at": null}}"#,
            session: nil)
        // Nothing read yet: nothing to tell.
        store.apply(update)
        #expect(heard.isEmpty)
        _ = try await store.pageUsage()
        store.apply(update)
        let today = ArtifactBridge.Value.object([
            "tokens": .number(15_006_600), "sessions": .number(74),
        ])
        #expect(
            heard == [
                .object([
                    "limits": .object([
                        "five_hour": .object([
                            "utilization": .number(0.5), "resets_at": .null,
                        ]),
                        "seven_day": .null,
                    ]),
                    "today": today, "week": today,
                ])
            ])
        let weekly = Fixture.event(
            EventType.usageUpdated, #"{"seven_day": {"utilization": 0.1, "resets_at": null}}"#,
            session: nil)
        store.apply(weekly)
        #expect(heard.count == 2)
        store.stopObservingUsage(token)
        store.apply(update)
        #expect(heard.count == 2)
    }

    @Test func anAskShowsWhileItRunsAndCountsTheDay() async throws {
        let store = store()
        #expect(!store.isAsking("a1"))
        #expect(store.askCount(of: "a1") == nil)
        let (gate, open) = AsyncStream<Void>.makeStream()
        api.set {
            $0.askAnswer = ArtifactAnswer(text: "Hi", remaining: 18, limit: 20)
            $0.gates["askArtifact"] = gate
        }
        let running = Task { try await store.ask("a1", prompt: "Hi?", system: "Brief") }
        await ArtifactBridgeTests.settle()
        #expect(store.isAsking("a1"))
        open.finish()
        let answer = try await running.value
        #expect(answer.text == "Hi")
        #expect(api.calls.contains("askArtifact a1 Hi? system=Brief"))
        #expect(!store.isAsking("a1"))
        #expect(store.askCount(of: "a1") == ArtifactAskCount(remaining: 18, limit: 20))

        api.fail("askArtifact", with: APIError.conflict("busy"))
        await #expect(throws: APIError.conflict("busy")) {
            try await store.ask("a1", prompt: "x", system: nil)
        }
        #expect(!store.isAsking("a1"))
    }

    @Test func theStatusDecodesAndShowsOnceThePageAsked() async throws {
        let status = Fixture.decode(
            ArtifactAskStatus.self,
            json:
                #"{"used": 2, "limit": 5, "remaining": 3, "resets_at": "2026-10-18T00:00:00Z", "enabled": true}"#
        )
        #expect(
            status
                == ArtifactAskStatus(
                    used: 2, limit: 5, remaining: 3,
                    resetsAt: Fixture.date("2026-10-18T00:00:00Z"), enabled: true))
        let store = store()
        api.set {
            $0.askStatus = ArtifactAskStatus(
                used: 0, limit: 5, remaining: 5, resetsAt: nil, enabled: true)
        }
        try await store.loadAsks("a1")
        #expect(api.calls.last == "askStatus a1")
        #expect(store.askCount(of: "a1") == nil)
        api.set { $0.askStatus = status }
        try await store.loadAsks("a1")
        #expect(store.askCount(of: "a1") == ArtifactAskCount(remaining: 3, limit: 5))
    }

    @Test func aUsedUpDayNamesWhenItResets() async throws {
        let store = store()
        api.fail("askArtifact", with: APIError.rateLimited("Limit reached", retryAfter: nil))
        api.set {
            $0.askStatus = ArtifactAskStatus(
                used: 20, limit: 20, remaining: 0,
                resetsAt: Fixture.date("2026-10-18T06:05:00Z"), enabled: true)
        }
        await #expect(
            throws: ArtifactsStore.AskBudgetUsed(
                message: "Today\u{2019}s asks for this page are used up. Resets 06:05.")
        ) {
            try await store.ask("a1", prompt: "x", system: nil)
        }
        #expect(store.askCount(of: "a1") == ArtifactAskCount(remaining: 0, limit: 20))
        api.set {
            $0.askStatus = ArtifactAskStatus(
                used: 20, limit: 20, remaining: 0, resetsAt: nil, enabled: true)
        }
        await #expect(
            throws: ArtifactsStore.AskBudgetUsed(
                message: "Today\u{2019}s asks for this page are used up.")
        ) {
            try await store.ask("a1", prompt: "x", system: nil)
        }
        api.fail("askStatus")
        await #expect(
            throws: ArtifactsStore.AskBudgetUsed(
                message: "Today\u{2019}s asks for this page are used up.")
        ) {
            try await store.ask("a1", prompt: "x", system: nil)
        }
        let session = ArtifactBridgeSession(
            prompt: ArtifactLinkPrompt(),
            ask: { _, _ in throw ArtifactsStore.AskBudgetUsed(message: "Used up.") }
        ) { _ in }
        let reply = await session.receive(Self.request("ask", ["prompt": "x"]))
        #expect(Self.code(reply) == .budget)
        #expect(Self.message(reply) == "Used up.")
    }

    @Test func theIndicatorStaysWhileAnotherAskFromThisAppRuns() async throws {
        let store = store()
        let (gate, open) = AsyncStream<Void>.makeStream()
        api.set { $0.gates["askArtifact"] = gate }
        let first = Task { try await store.ask("a1", prompt: "one", system: nil) }
        while !api.calls.contains("askArtifact a1 one system=") {
            await Task.yield()
        }
        // A second ask is refused at once; the first still runs.
        api.set { $0.failNext["askArtifact"] = APIError.conflict("busy") }
        await #expect(throws: APIError.conflict("busy")) {
            try await store.ask("a1", prompt: "two", system: nil)
        }
        #expect(store.isAsking("a1"))
        open.finish()
        _ = try await first.value
        #expect(!store.isAsking("a1"))
    }

    @Test func aStoreMadeWithItsDefaultsReadsTodaysUsage() async throws {
        api.set { $0.artifacts = [] }
        let store = ArtifactsStore(api: api)
        let before = Date()
        _ = try await store.pageUsage()
        let parts = Calendar.current.dateComponents([.year, .month, .day], from: before)
        let today = CalendarDay(year: parts.year!, month: parts.month!, day: parts.day!)
        // Around midnight the day may have turned while it read.
        let after = Calendar.current.dateComponents([.year, .month, .day], from: Date())
        let later = CalendarDay(year: after.year!, month: after.month!, day: after.day!)
        #expect(
            api.calls.contains("usagePeriod day \(today.description)")
                || api.calls.contains("usagePeriod day \(later.description)"))
    }

    @Test func askEventsFromOtherReadersShowTheIndicatorToo() {
        let store = store()
        func event(_ state: String, _ remaining: Int) -> Event {
            Fixture.event(
                EventType.artifactAsk,
                #"{"artifact_id": "a1", "state": "\#(state)", "remaining": \#(remaining)}"#,
                session: nil)
        }
        store.apply(event("started", 19))
        #expect(store.isAsking("a1"))
        #expect(store.askCount(of: "a1") == ArtifactAskCount(remaining: 19, limit: 20))
        store.apply(event("finished", 18))
        #expect(!store.isAsking("a1"))
        #expect(store.askCount(of: "a1") == ArtifactAskCount(remaining: 18, limit: 20))
        store.apply(event("paused", 17))
        #expect(!store.isAsking("a1"))
    }

    // MARK: The open panel

    @Test func acceptNarrowsTheOpenPanel() throws {
        let text = try #require(ArtifactOpenPanel.types(accept: ".txt, .MD,.csv"))
        #expect(text.contains(.plainText))
        #expect(text.contains(.commaSeparatedText))
        #expect(text.contains(UTType(filenameExtension: "md")!))
        #expect(!text.contains(.png))
        let kinds = try #require(
            ArtifactOpenPanel.types(accept: "image/*,audio/*,video/*,text/*,application/json"))
        #expect(kinds == [.image, .audio, .movie, .text, .json])
        #expect(ArtifactOpenPanel.types(accept: "") == nil)
        #expect(ArtifactOpenPanel.types(accept: nil) == nil)
        #expect(ArtifactOpenPanel.types(accept: " , ") == nil)
        // Something it cannot read leaves the panel open to every file.
        #expect(ArtifactOpenPanel.types(accept: ".txt,foo") == nil)
        #expect(ArtifactOpenPanel.types(accept: "x-made/up-type") == nil)
        #expect(ArtifactOpenPanel.watchScript.contains("window.__nestAccept=t.accept"))
        #expect(ArtifactOpenPanel.script.contains("window.__nestAccept"))
        #expect(ArtifactOpenPanel.world == "nest-host")
    }
}

/// A clock the test moves.
final class Clock: @unchecked Sendable {
    var now: Date

    init(_ now: Date) {
        self.now = now
    }
}
