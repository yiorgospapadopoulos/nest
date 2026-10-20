import Foundation
import Testing

@testable import NestKit

private var utc: Calendar {
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = TimeZone(identifier: "UTC")!
    return calendar
}

/// 2026-10-17 12:00 UTC, a Saturday.
private let saturday = Date(timeIntervalSince1970: 1_792_238_400)

private func date(_ text: String) -> Date {
    try! Date.ISO8601FormatStyle().parse(text)
}

@Suite struct UsagePeriodModelTests {
    @Test func decodesThePeriod() {
        let period = Fixture.usagePeriod
        #expect(period.unit == .month)
        #expect(period.start == CalendarDay(year: 2026, month: 10, day: 1))
        #expect(period.end == CalendarDay(year: 2026, month: 10, day: 31))
        #expect(period.current)
        #expect(period.sessions == 74)
        #expect(period.tokens.total == 15_006_600)
        #expect(period.subagents.total == 1_600_000)
        #expect(period.bars.count == 31)
        #expect(
            period.bars[5]
                == PeriodBar(start: date("2026-10-06T00:00:00Z"), tokens: 1_060_000, sessions: 4))
        #expect(
            period.projects[3] == ProjectTokens(name: "Pixies", tokens: 1_120_000, pixies: true))
        #expect(period.probes == ProbeTotals(count: 12, tokens: 5_000))
    }

    @Test func barsKeepTheirOffset() {
        let json = #"{"start": "2026-10-01T00:00:00+03:00", "tokens": 5, "sessions": 1}"#
        let bar = Fixture.decode(PeriodBar.self, json: json)
        #expect(bar.start == date("2026-09-30T21:00:00Z"))
    }

    @Test func unitsAreTheQueryWords() {
        #expect(UsageUnit.allCases.map(\.rawValue) == ["day", "week", "month", "year"])
        #expect(UsageUnit.allCases.map(\.title) == ["Day", "Week", "Month", "Year"])
    }
}

@Suite struct UsagePeriodTextTests {
    func start(_ text: String, _ unit: UsageUnit) -> Date {
        UsageText.periodStart(of: date(text), unit: unit, calendar: utc)
    }

    @Test func periodsStartOnTheirFirstDay() {
        #expect(start("2026-10-17T12:00:00Z", .day) == date("2026-10-17T00:00:00Z"))
        // Weeks start on Monday, also from a Sunday.
        #expect(start("2026-10-17T12:00:00Z", .week) == date("2026-10-12T00:00:00Z"))
        #expect(start("2026-10-18T23:00:00Z", .week) == date("2026-10-12T00:00:00Z"))
        #expect(start("2026-10-12T00:00:00Z", .week) == date("2026-10-12T00:00:00Z"))
        #expect(start("2026-10-17T12:00:00Z", .month) == date("2026-10-01T00:00:00Z"))
        #expect(start("2026-10-17T12:00:00Z", .year) == date("2026-01-01T00:00:00Z"))
    }

    @Test func periodsMoveByTheirUnit() {
        func shifted(_ text: String, _ unit: UsageUnit, _ count: Int) -> Date {
            UsageText.shift(date(text), unit: unit, by: count, calendar: utc)
        }
        #expect(shifted("2026-10-17T00:00:00Z", .day, -1) == date("2026-10-16T00:00:00Z"))
        #expect(shifted("2026-10-12T00:00:00Z", .week, -2) == date("2026-09-28T00:00:00Z"))
        #expect(shifted("2026-01-01T00:00:00Z", .month, -1) == date("2025-12-01T00:00:00Z"))
        #expect(shifted("2026-01-01T00:00:00Z", .year, 1) == date("2027-01-01T00:00:00Z"))
    }

    @Test func titles() {
        func title(_ text: String, _ unit: UsageUnit) -> String {
            UsageText.periodTitle(
                start: start(text, unit), unit: unit, now: saturday, calendar: utc)
        }
        #expect(title("2026-10-17T08:00:00Z", .day) == "Today")
        #expect(title("2026-10-16T08:00:00Z", .day) == "Fri 16 Oct")
        #expect(title("2026-10-17T08:00:00Z", .week) == "12 to 18 Oct")
        #expect(title("2026-10-01T08:00:00Z", .week) == "28 Sep to 4 Oct")
        #expect(title("2026-10-17T08:00:00Z", .month) == "October")
        #expect(title("2025-10-17T08:00:00Z", .month) == "October 2025")
        #expect(title("2026-10-17T08:00:00Z", .year) == "2026")
    }

    @Test func barTips() {
        func tip(_ text: String, _ unit: UsageUnit, tokens: Int = 3_400_000, sessions: Int = 12)
            -> String
        {
            UsageText.barTip(
                PeriodBar(start: date(text), tokens: tokens, sessions: sessions), unit: unit,
                calendar: utc)
        }
        #expect(tip("2026-10-14T00:00:00Z", .month) == "Wed 14 Oct: 3.4M tokens, 12 chats")
        #expect(tip("2026-10-14T00:00:00Z", .week) == "Wed 14 Oct: 3.4M tokens, 12 chats")
        #expect(tip("2026-10-14T14:00:00Z", .day, sessions: 1) == "14:00: 3.4M tokens, 1 chat")
        #expect(
            tip("2026-10-01T00:00:00Z", .year, tokens: 0, sessions: 0)
                == "October: 0 tokens, 0 chats")
    }

    @Test func ticksSpanEachPeriod() {
        #expect(UsageText.ticks(unit: .day, bars: 24) == ["0", "6", "12", "18", "23"])
        #expect(UsageText.ticks(unit: .week, bars: 7) == ["Mo", "We", "Fr", "Su"])
        #expect(UsageText.ticks(unit: .month, bars: 30) == ["1", "8", "15", "22", "30"])
        #expect(UsageText.ticks(unit: .year, bars: 12) == ["Jan", "Apr", "Jul", "Oct", "Dec"])
    }

    @Test func barHeights() {
        #expect(UsageText.barHeight(tokens: 0, peak: 0, full: 64) == 1)
        #expect(UsageText.barHeight(tokens: 0, peak: 10, full: 64) == 1)
        #expect(UsageText.barHeight(tokens: 10, peak: 10, full: 64) == 64)
        #expect(UsageText.barHeight(tokens: 5, peak: 10, full: 64) == 32)
        // A bar with any tokens stays visible.
        #expect(UsageText.barHeight(tokens: 1, peak: 1_000, full: 64) == 3)
    }

    @Test func shares() {
        #expect(UsageText.share(89, of: 100) == "89%")
        #expect(UsageText.share(7, of: 1_000) == "0.7%")
        #expect(UsageText.share(1, of: 10_000) == "0.01%")
        #expect(UsageText.share(1, of: 1_000_000) == "<0.01%")
        #expect(UsageText.share(0, of: 100) == "0%")
        #expect(UsageText.share(5, of: 0) == "0%")
    }

    @Test func chats() {
        #expect(UsageText.chats(1) == "1 chat")
        #expect(UsageText.chats(74) == "74 chats")
    }

    @Test func probes() {
        #expect(
            UsageText.probes(ProbeTotals(count: 12, tokens: 5_000))
                == "12 usage checks, 5k tokens, not counted above")
        #expect(
            UsageText.probes(ProbeTotals(count: 1, tokens: 400))
                == "1 usage check, 400 tokens, not counted above")
        #expect(UsageText.probes(ProbeTotals(count: 0, tokens: 0)) == nil)
    }
}

@Suite struct UsageBreakdownTests {
    @Test func splitsThePeriod() {
        let breakdown = UsageBreakdown(Fixture.usagePeriod)
        #expect(breakdown.total == "15M")
        #expect(
            breakdown.who == [
                .init(label: "Chats", value: "13.4M", share: "89%"),
                .init(label: "Subagents", value: "1.6M", share: "11%"),
            ])
        #expect(
            breakdown.kinds == [
                .init(label: "Cache read", value: "12.1M", share: "81%"),
                .init(label: "Cache write", value: "2.8M", share: "19%"),
                .init(label: "Output", value: "105k", share: "0.7%"),
                .init(label: "Input", value: "2k", share: "0.01%"),
            ])
        #expect(
            breakdown.projects.map(\.name) == [
                "DEMO", "CV-page", "b59-live", "Pixies", "Others (10)",
            ])
        #expect(breakdown.projects.map(\.value) == ["7.2M", "2.2M", "1.4M", "1.1M", "1.1M"])
        #expect(breakdown.projects[0].fraction == 1)
        #expect(abs(breakdown.projects[4].fraction - 1_125_000 / 7_155_867) < 1e-9)
        #expect(breakdown.projects[3].id == "Pixies")
        #expect(breakdown.probes == "12 usage checks, 5k tokens, not counted above")
    }

    @Test func fewProjectsNeedNoOthers() {
        var period = Fixture.usagePeriod
        period.projects = Array(period.projects.prefix(4))
        #expect(
            UsageBreakdown(period).projects.map(\.name) == [
                "DEMO", "CV-page", "b59-live", "Pixies",
            ])
    }

    @Test func anEmptyPeriod() {
        var period = Fixture.usagePeriod
        let zero = TokenTotals(
            inputTokens: 0, outputTokens: 0, cacheCreationInputTokens: 0,
            cacheReadInputTokens: 0, total: 0)
        period.tokens = zero
        period.subagents = zero
        period.projects = []
        period.probes = ProbeTotals(count: 0, tokens: 0)
        let breakdown = UsageBreakdown(period)
        #expect(breakdown.total == "0")
        #expect(breakdown.who.map(\.share) == ["0%", "0%"])
        #expect(breakdown.projects.isEmpty)
        #expect(breakdown.probes == nil)
    }
}

@MainActor
@Suite struct UsagePeriodStoreTests {
    let api = FakeAPI()

    func store(now: Date = saturday) -> UsageStore {
        UsageStore(api: api, calendar: utc, now: { now })
    }

    @Test func loadsLimitsAndTheCurrentMonth() async throws {
        let usage = store()
        #expect(usage.unit == .month)
        #expect(usage.period == nil)
        #expect(usage.chatsText == "-")
        #expect(usage.subagentsText == "-")
        #expect(usage.totalText == "-")
        #expect(usage.totalLabel == "Total")
        #expect(usage.bars.isEmpty)
        #expect(usage.ticks == ["1", "8", "15", "22", "31"])
        let providers = ProvidersStore(api: api)
        #expect(usage.breakdown(providers: providers) == nil)

        try await usage.load()

        #expect(
            api.calls == ["usageLimits", "usageLimitsFor codex", "usagePeriod month 2026-10-01"])
        #expect(usage.periodTitle == "October")
        #expect(usage.chatsText == "13.4M")
        #expect(usage.subagentsText == "1.6M")
        #expect(usage.totalText == "15M")
        #expect(usage.totalLabel == "Total · 74 chats")
        #expect(usage.breakdown(providers: providers)?.total == "15M")
        #expect(usage.breakdownTitle == "October tokens")
        #expect(!usage.canShowNext)
    }

    @Test func barsScaleToTheBusiestAndStopAtNow() async throws {
        let usage = store()
        try await usage.loadPeriod()
        let bars = usage.bars
        #expect(bars.count == 31)
        #expect(bars.map(\.id) == Array(0..<31))
        #expect(bars[0].height == 1)
        #expect(bars[5].height == 19)
        #expect(bars[14].height == 64)
        #expect(bars[5].tip == "Tue 6 Oct: 1.1M tokens, 4 chats")
        // Today's bar (the 17th) is the last one that is not in the future.
        #expect(bars.filter(\.isFuture).count == 14)
        #expect(!bars[16].isFuture)
        #expect(bars[17].tip == nil)
    }

    @Test func movesBetweenPeriodsButNotIntoTheFuture() async throws {
        let usage = store()
        try await usage.loadPeriod()
        try await usage.showNext()
        #expect(api.calls == ["usagePeriod month 2026-10-01"])

        try await usage.showPrevious()
        #expect(usage.periodTitle == "September")
        #expect(usage.canShowNext)
        #expect(usage.period?.start == CalendarDay(year: 2026, month: 9, day: 1))
        try await usage.showNext()
        #expect(usage.periodTitle == "October")
        #expect(
            api.calls.suffix(2) == ["usagePeriod month 2026-09-01", "usagePeriod month 2026-10-01"])
    }

    @Test func choosingAUnitShowsItsCurrentPeriod() async throws {
        let usage = store()
        try await usage.showPrevious()
        try await usage.choose(.week)
        #expect(usage.unit == .week)
        #expect(usage.periodTitle == "12 to 18 Oct")
        #expect(api.calls.last == "usagePeriod week 2026-10-12")
        #expect(usage.ticks == ["Mo", "We", "Fr", "Su"])
        try await usage.showPrevious()
        #expect(usage.periodTitle == "5 to 11 Oct")

        try await usage.choose(.day)
        #expect(usage.periodTitle == "Today")
        try await usage.showPrevious()
        #expect(usage.periodTitle == "Fri 16 Oct")
        #expect(usage.breakdownTitle == "Fri 16 Oct tokens")

        try await usage.choose(.year)
        #expect(usage.periodTitle == "2026")
        try await usage.showPrevious()
        #expect(usage.periodTitle == "2025")
        #expect(api.calls.last == "usagePeriod year 2025-01-01")
    }

    @Test func theLastNavigationWins() async throws {
        let usage = store()
        async let first: Void = usage.showPrevious()
        async let second: Void = usage.showPrevious()
        _ = try await (first, second)
        #expect(usage.periodTitle == "August")
        #expect(usage.period?.start == CalendarDay(year: 2026, month: 8, day: 1))
    }

    @Test func showsLoadingWhileAPeriodLoads() async throws {
        let usage = store()
        let gate = AsyncStream<Void>.makeStream()
        api.set { $0.gates["usagePeriod"] = gate.stream }
        let task = Task { try await usage.loadPeriod() }
        try await waitFor { usage.isLoading }
        gate.continuation.finish()
        try await task.value
        #expect(!usage.isLoading)
        #expect(usage.period != nil)
    }

    @Test func aFailedLoadStopsLoading() async throws {
        let usage = store()
        api.fail("usagePeriod")
        await #expect(throws: APIError.self) { try await usage.loadPeriod() }
        #expect(!usage.isLoading)
        #expect(usage.period == nil)
    }

    @Test func detailsOpenAndClose() async throws {
        let usage = store()
        #expect(!usage.showsDetails)
        usage.showDetails()
        #expect(usage.showsDetails)
        usage.hideDetails()
        #expect(!usage.showsDetails)
    }

    @Test func refreshShowsTheLatestReport() async throws {
        let usage = store()
        #expect(usage.refreshTitle == "Refresh")
        #expect(!usage.limitsAreStale(at: saturday))
        usage.apply(
            Fixture.event(
                EventType.usageUpdated,
                #"{"five_hour": {"utilization": 0.03, "resets_at": null}, "seven_day": null}"#,
                session: nil))
        let reported = try #require(usage.limits?.fiveHour?.updatedAt)
        let parts = utc.dateComponents([.hour, .minute], from: reported)
        #expect(usage.refreshTitle == String(format: "as of %02d:%02d", parts.hour!, parts.minute!))
        #expect(!usage.limitsAreStale(at: reported.addingTimeInterval(60)))
        #expect(usage.limitsAreStale(at: reported.addingTimeInterval(11 * 60)))

        // The weekly window reported later wins.
        var later = try #require(usage.limits)
        later.sevenDay = LimitWindow(
            utilization: 0.2, resetsAt: nil, updatedAt: reported.addingTimeInterval(3_600))
        later.fiveHour?.updatedAt = reported
        try await withLimits(later, usage)
        #expect(!usage.limitsAreStale(at: reported.addingTimeInterval(3_660)))
    }

    private func withLimits(_ limits: UsageLimits, _ usage: UsageStore) async throws {
        api.set { $0.limits = limits }
        try await usage.load()
    }
}
