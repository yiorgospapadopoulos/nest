import Foundation
import Synchronization
import Testing

@testable import NestKit

private var utc: Calendar {
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = TimeZone(identifier: "UTC")!
    return calendar
}

/// 2026-10-06 14:00 UTC.
private let two = Date(timeIntervalSince1970: 1_791_295_200)

/// A clock the test moves by hand.
final class TestClock: Sendable {
    private let date: Mutex<Date>

    init(_ start: Date = two) {
        date = Mutex(start)
    }

    var now: Date { date.withLock { $0 } }

    func advance(_ seconds: TimeInterval) {
        date.withLock { $0 += seconds }
    }

    var read: @Sendable () -> Date { { self.now } }
}

private func window(updated: Date?) -> LimitWindow {
    LimitWindow(utilization: 0.3, resetsAt: nil, updatedAt: updated)
}

@MainActor
@Suite struct UsageFreshnessTests {
    @Test func asOfShowsTheReportTime() {
        #expect(UsageText.asOf(window(updated: two + 5 * 60 + 40), calendar: utc) == "as of 14:05")
        #expect(UsageText.asOf(window(updated: nil), calendar: utc) == nil)
        #expect(UsageText.asOf(nil, calendar: utc) == nil)
    }

    @Test func numbersOlderThanTenMinutesAreStale() {
        let report = window(updated: two)
        #expect(!UsageText.isStale(report, now: two))
        #expect(!UsageText.isStale(report, now: two + 600))
        #expect(UsageText.isStale(report, now: two + 601))
        #expect(!UsageText.isStale(window(updated: nil), now: two + 3600))
        #expect(!UsageText.isStale(nil, now: two + 3600))
    }

    @Test func refreshIntervals() {
        #expect(UsageText.refreshChoices == [0, 1, 3, 5, 10, 15])
        #expect(
            [nil, 0, 1, 3, 15].map(UsageText.refreshInterval) == [
                "-", "Off", "Every minute", "Every 3 minutes", "Every 15 minutes",
            ])
    }

    @Test func theStoreFormatsInItsCalendar() async throws {
        let api = FakeAPI()
        let usage = UsageStore(api: api, calendar: utc, now: { two })
        try await usage.load()
        #expect(usage.asOfText(usage.limits?.fiveHour) == "as of 14:00")
        #expect(usage.asOfText(usage.limits?.sevenDay) == nil)
    }
}

@MainActor
@Suite struct UsageRefreshTests {
    let api = FakeAPI()
    let clock = TestClock()
    let usage: UsageStore

    init() {
        usage = UsageStore(api: api, calendar: utc, now: clock.read)
    }

    @Test func refreshReplacesTheLimits() async throws {
        try await usage.load()
        let fresh = UsageLimits(
            fiveHour: LimitWindow(utilization: 0.5, resetsAt: nil, updatedAt: two),
            sevenDay: LimitWindow(utilization: 0.2, resetsAt: nil, updatedAt: two))
        api.set { $0.refreshedLimits = fresh }

        await usage.refresh()

        #expect(usage.limits == fresh)
        #expect(!usage.isRefreshing)
        #expect(usage.refreshNote(at: clock.now) == nil)
        #expect(api.calls.contains("refreshUsage"))
    }

    @Test func tooSoonCountsDownUntilTheDaemonAcceptsAgain() async {
        api.fail("refreshUsage", with: APIError.rateLimited("too soon", retryAfter: 12))
        await usage.refresh()
        #expect(usage.limits == nil)
        #expect(usage.retryAt == two + 12)
        #expect(usage.refreshNote(at: two) == "Try again in 12 s")
        #expect(usage.refreshNote(at: two + 0.4) == "Try again in 12 s")
        #expect(usage.refreshNote(at: two + 11.5) == "Try again in 1 s")
        #expect(usage.refreshNote(at: two + 12) == nil)

        // Without a retry time, the daemon's 20 s rule.
        api.fail("refreshUsage", with: APIError.rateLimited("too soon", retryAfter: nil))
        await usage.refresh()
        #expect(usage.refreshNote(at: two) == "Try again in 20 s")
    }

    @Test func failuresAreNotedQuietlyAndClearedBySuccess() async {
        api.fail("refreshUsage", with: APIError.badGateway("no windows"))
        await usage.refresh()
        #expect(usage.refreshNote(at: two) == "Claude did not report the limits")

        api.fail("refreshUsage", with: APIError.transport("offline"))
        await usage.refresh()
        #expect(usage.refreshNote(at: two) == "Could not refresh")

        api.set { $0.failures = [:] }
        await usage.refresh()
        #expect(usage.refreshNote(at: two) == nil)
        #expect(usage.limits == Fixture.usageLimits)
    }

    @Test func aRefreshUnderWayIsNotRepeated() async throws {
        let (gate, open) = AsyncStream<Void>.makeStream()
        api.set { $0.gates["refreshUsage"] = gate }
        let first = Task { await usage.refresh() }
        try await waitFor { usage.isRefreshing }

        await usage.refresh()
        open.finish()
        await first.value

        #expect(api.calls.filter { $0 == "refreshUsage" }.count == 1)
        #expect(!usage.isRefreshing)
    }

    @Test func settingsLoadAndSave() async throws {
        #expect(usage.refreshMinutes == nil)
        try await usage.loadSettings()
        #expect(usage.refreshMinutes == 3)

        try await usage.setRefreshMinutes(0)
        #expect(usage.refreshMinutes == 0)
        #expect(api.calls.contains("updateUsageSettings 0"))
        #expect(api.state.withLock { $0.usageSettings } == UsageSettings(refreshMinutes: 0))
    }

    @Test func aRefusedIntervalRestoresTheOldOne() async throws {
        try await usage.loadSettings()
        api.fail("updateUsageSettings", with: APIError.conflict("read-only"))
        await #expect(throws: APIError.conflict("read-only")) {
            try await usage.setRefreshMinutes(10)
        }
        #expect(usage.refreshMinutes == 3)
    }
}

@MainActor
@Suite struct VisibilityTests {
    let api = FakeAPI()
    let clock = TestClock()
    let reporter: VisibilityReporter

    init() {
        reporter = VisibilityReporter(api: api, now: clock.read)
    }

    var reports: [String] {
        api.calls.filter { $0.hasPrefix("reportVisibility") }
    }

    @Test func visibleNeedsAnUnhiddenAppAnAwakeScreenAndAWindowOnScreen() {
        let shown = WindowPresence(isShown: true, isOnScreen: true, isMiniaturized: false)
        let covered = WindowPresence(isShown: true, isOnScreen: false, isMiniaturized: false)
        let minimized = WindowPresence(isShown: true, isOnScreen: true, isMiniaturized: true)
        let closed = WindowPresence(isShown: false, isOnScreen: true, isMiniaturized: false)
        func visible(hidden: Bool = false, away: Bool = false, _ windows: [WindowPresence])
            -> Bool
        {
            WindowPresence.isVisible(appHidden: hidden, screenAway: away, windows: windows)
        }
        #expect(visible([shown]))
        #expect(visible([covered, shown]))
        #expect(!visible([covered, minimized, closed]))
        #expect(!visible([]))
        #expect(!visible(hidden: true, [shown]))
        #expect(!visible(away: true, [shown]))
    }

    @Test func reportsTheFirstStateAndEachChangeInOrder() async {
        #expect(reporter.lastReport == nil)
        let (gate, open) = AsyncStream<Void>.makeStream()
        api.set { $0.gates["reportVisibility"] = gate }

        reporter.update(visible: false)
        reporter.update(visible: false)
        reporter.update(visible: true)
        reporter.update(visible: true)
        reporter.update(visible: false)
        #expect(reporter.lastReport == two)
        #expect(reports.isEmpty)

        open.finish()
        await reporter.flush()
        #expect(
            reports == [
                "reportVisibility false mac", "reportVisibility true mac",
                "reportVisibility false mac",
            ])
        #expect(!reporter.isVisible)
    }

    @Test func aHeartbeatGoesOutEveryMinuteWhileVisible() async {
        reporter.tick()
        reporter.update(visible: true)
        clock.advance(59)
        reporter.tick()
        await reporter.flush()
        #expect(reports.count == 1)

        clock.advance(1)
        reporter.tick()
        #expect(reporter.lastReport == two + 60)
        clock.advance(30)
        reporter.tick()
        await reporter.flush()
        #expect(reports == Array(repeating: "reportVisibility true mac", count: 2))

        reporter.update(visible: false)
        clock.advance(600)
        reporter.tick()
        await reporter.flush()
        #expect(reports.last == "reportVisibility false mac")
        #expect(reports.count == 3)
    }

    @Test func runTicksUntilItsSleepIsCancelled() async {
        reporter.update(visible: true)
        let sleeps = Mutex<[Duration]>([])
        let clock = clock
        await reporter.run { duration in
            let count = sleeps.withLock { sleeps in
                sleeps.append(duration)
                return sleeps.count
            }
            guard count <= 13 else { throw CancellationError() }
            clock.advance(10)
        }
        await reporter.flush()
        // 13 ticks of 10 s: heartbeats at 60 s and 120 s after the first report.
        #expect(sleeps.withLock { $0.count } == 14)
        #expect(sleeps.withLock { $0.allSatisfy { $0 == .seconds(10) } })
        #expect(reports.count == 3)
    }

    @Test func theRealClockAndSleepStopOnCancellation() async {
        let sent = Mutex<[Bool]>([])
        let reporter = VisibilityReporter { visible in sent.withLock { $0.append(visible) } }
        reporter.update(visible: true)
        #expect(abs(reporter.lastReport!.timeIntervalSinceNow) < 60)
        let heartbeat = Task { await reporter.run() }
        heartbeat.cancel()
        await heartbeat.value
        await reporter.flush()
        #expect(sent.withLock { $0 } == [true])
    }

    @Test func resendReportsAgainOnlyWhileVisible() async {
        reporter.resend()
        reporter.update(visible: false)
        reporter.resend()
        reporter.update(visible: true)
        reporter.resend()
        await reporter.flush()
        #expect(
            reports == [
                "reportVisibility false mac", "reportVisibility true mac",
                "reportVisibility true mac",
            ])
    }

    @Test func failedReportsDoNotStopTheNextOnes() async {
        api.fail("reportVisibility", with: APIError.transport("offline"))
        reporter.update(visible: true)
        await reporter.flush()
        api.set { $0.failures = [:] }
        reporter.update(visible: false)
        await reporter.flush()
        #expect(reports.count == 2)
    }

    @Test func aReconnectReportsVisibilityAgain() async throws {
        let source = ManualEventSource()
        let model = AppModel(api: api, events: source, preferences: MemoryStore())
        model.visibility.update(visible: true)
        let run = Task { await model.live.run() }
        source.continuation.yield(.connected(resumed: false))
        try await waitFor { reports.count == 2 }
        #expect(reports == Array(repeating: "reportVisibility true mac", count: 2))
        source.continuation.finish()
        await run.value
    }
}
