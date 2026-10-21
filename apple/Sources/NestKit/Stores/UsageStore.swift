import Foundation
import Observation

/// One bar of the usage chart.
public struct UsageBarCell: Sendable, Hashable, Identifiable {
    /// Its place in the period.
    public let id: Int
    /// In points, of `UsageStore.barsHeight`.
    public let height: Double
    /// After now: drawn as an empty slot.
    public let isFuture: Bool
    /// "Wed 14 Oct: 3.4M tokens, 12 chats"; nil for a future bar.
    public let tip: String?
}

/// The token chart of the usage popover: a day, week, month or year at a time, with its
/// breakdown, and the usage settings. The limits are the accounts' (B98).
@MainActor @Observable
public final class UsageStore {
    /// The tallest bar, in points.
    public static let barsHeight = 64.0
    /// The shown period's numbers; nil while it loads.
    public private(set) var period: UsagePeriod?
    public private(set) var unit = UsageUnit.month
    /// The local start of the shown period, starting with the current one.
    public private(set) var shownStart: Date
    /// Period loads on their way.
    private var loads = 0
    /// The popover shows the breakdown instead of the chart.
    public private(set) var showsDetails = false
    /// The `[usage]` settings; nil until loaded.
    public private(set) var settings: UsageSettings?
    /// The latest `usage.warning` not dismissed yet, for the in-app notice (B81).
    public private(set) var warning: UsageWarning?

    /// Minutes between automatic refreshes (0 is off); nil until loaded.
    public var refreshMinutes: Int? { settings?.refreshMinutes }

    let api: any NestAPI
    let now: @Sendable () -> Date
    let calendar: Calendar

    public init(
        api: any NestAPI, calendar: Calendar = .current,
        now: @escaping @Sendable () -> Date = { Date() }
    ) {
        self.api = api
        self.calendar = calendar
        self.now = now
        shownStart = UsageText.periodStart(of: now(), unit: .month, calendar: calendar)
    }

    public var isLoading: Bool { loads > 0 }

    public func loadPeriod() async throws {
        let shown = (unit, shownStart)
        let parts = calendar.dateComponents([.year, .month, .day], from: shownStart)
        let day = CalendarDay(year: parts.year!, month: parts.month!, day: parts.day!)
        loads += 1
        defer { loads -= 1 }
        let loaded = try await api.usagePeriod(unit: unit, date: day)
        // A newer navigation may have moved on while this one loaded.
        if (unit, shownStart) == shown {
            period = loaded
        }
    }

    /// Switches the chart to another unit, at its current period.
    public func choose(_ unit: UsageUnit) async throws {
        self.unit = unit
        try await show(UsageText.periodStart(of: now(), unit: unit, calendar: calendar))
    }

    /// Later periods than the current one are not shown.
    public var canShowNext: Bool {
        shownStart < UsageText.periodStart(of: now(), unit: unit, calendar: calendar)
    }

    public func showPrevious() async throws {
        try await show(UsageText.shift(shownStart, unit: unit, by: -1, calendar: calendar))
    }

    public func showNext() async throws {
        guard canShowNext else { return }
        try await show(UsageText.shift(shownStart, unit: unit, by: 1, calendar: calendar))
    }

    private func show(_ start: Date) async throws {
        shownStart = start
        period = nil
        try await loadPeriod()
    }

    /// "October", "12 to 18 Oct", "Today".
    public var periodTitle: String {
        UsageText.periodTitle(start: shownStart, unit: unit, now: now(), calendar: calendar)
    }

    /// "October tokens", over the breakdown.
    public var breakdownTitle: String { "\(periodTitle) tokens" }

    public var bars: [UsageBarCell] {
        guard let period else { return [] }
        let peak = period.bars.reduce(0) { max($0, $1.tokens) }
        let date = now()
        return period.bars.enumerated().map { index, bar in
            let future = bar.start > date
            return UsageBarCell(
                id: index,
                height: UsageText.barHeight(tokens: bar.tokens, peak: peak, full: Self.barsHeight),
                isFuture: future,
                tip: future ? nil : UsageText.barTip(bar, unit: unit, calendar: calendar))
        }
    }

    public var ticks: [String] {
        let count =
            period?.bars.count
            ?? calendar.range(of: .day, in: .month, for: shownStart)!.count
        return UsageText.ticks(unit: unit, bars: count)
    }

    /// The chats' own tokens, without their subagents'; "-" while loading.
    public var chatsText: String {
        period.map { UsageText.tokens($0.tokens.total - $0.subagents.total) } ?? "-"
    }

    public var subagentsText: String {
        period.map { UsageText.tokens($0.subagents.total) } ?? "-"
    }

    public var totalText: String { period.map { UsageText.tokens($0.tokens.total) } ?? "-" }

    /// "Total · 74 chats".
    public var totalLabel: String {
        period.map { "Total · \(UsageText.chats($0.sessions))" } ?? "Total"
    }

    /// The Details of the shown period, split by the engines `providers` lists.
    public func breakdown(providers: ProvidersStore) -> UsageBreakdown? {
        period.map { UsageBreakdown($0, engines: providers.providers) }
    }

    public func showDetails() {
        showsDetails = true
    }

    public func hideDetails() {
        showsDetails = false
    }

    public func loadSettings() async throws {
        settings = try await api.usageSettings()
    }

    public func setRefreshMinutes(_ minutes: Int) async throws {
        try await changeSettings { $0.refreshMinutes = minutes }
    }

    /// The warning level in percent, or nil to turn the warning off.
    public func setWarnPercent(_ percent: Int?) async throws {
        try await changeSettings { $0.warnPercent = percent }
    }

    public func setWarnNotify(_ notify: Bool) async throws {
        try await changeSettings { $0.warnNotify = notify }
    }

    /// Shows the change at once and restores the old settings if the daemon refuses it. The
    /// whole section is sent, so it is read first when it was not yet.
    private func changeSettings(_ change: (inout UsageSettings) -> Void) async throws {
        if settings == nil {
            try await loadSettings()
        }
        guard let previous = settings else { return }
        var changed = previous
        change(&changed)
        settings = changed
        do {
            settings = try await api.updateUsageSettings(changed)
        } catch {
            settings = previous
            throw error
        }
    }

    /// Whether a usage warning should also be a notification on this Mac: the setting as
    /// last read, read now when it was not yet.
    public func warningNotifies() async -> Bool {
        if settings == nil {
            try? await loadSettings()
        }
        return settings?.warnNotify ?? false
    }

    public func dismissWarning() {
        warning = nil
    }

    /// "You have used 82% of your 5 hour limit. Resets 18:30."
    public func warningText(_ warning: UsageWarning) -> String {
        UsageText.warning(warning, now: now(), calendar: calendar)
    }

    /// When a limit window resets, in this store's calendar.
    public func resetText(_ window: LimitWindow?) -> String {
        UsageText.reset(window, now: now(), calendar: calendar)
    }

    public func apply(_ event: Event) {
        if case .usageWarning(let warning) = event.body {
            self.warning = warning
        }
    }
}
