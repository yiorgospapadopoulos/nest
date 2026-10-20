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

/// One engine's line of the usage meter at the top right (B91): its name and its windows,
/// nil before the engine reported any.
public struct UsageMeterLine: Sendable, Equatable, Identifiable {
    public let provider: String
    public let name: String
    public let chip: UsageChip?

    public var id: String { provider }
}

/// One engine's windows in the usage popover; `title` names the engine when there is more
/// than one.
public struct UsageLimitGroup: Sendable, Equatable, Identifiable {
    public let provider: String
    public let title: String?
    public let limits: UsageLimits?

    public var id: String { provider }
}

/// Subscription limits and the token chart of the usage popover: a day, week, month or
/// year at a time, with its breakdown. Claude's windows, and since B91 those of the other
/// engines the daemon keeps.
@MainActor @Observable
public final class UsageStore {
    /// The tallest bar, in points.
    public static let barsHeight = 64.0
    /// The engines besides Claude whose windows the daemon keeps (B91).
    public static let otherEngines = ["codex"]

    /// Claude's windows.
    public private(set) var limits: UsageLimits?
    /// The other engines' windows, by engine name.
    public private(set) var engineLimits: [String: UsageLimits] = [:]
    /// The shown period's numbers; nil while it loads.
    public private(set) var period: UsagePeriod?
    public private(set) var unit = UsageUnit.month
    /// The local start of the shown period, starting with the current one.
    public private(set) var shownStart: Date
    /// Period loads on their way.
    private var loads = 0
    /// The popover shows the breakdown instead of the chart.
    public private(set) var showsDetails = false
    /// A manual refresh is on its way.
    public private(set) var isRefreshing = false
    /// The daemon refuses another refresh until then.
    public private(set) var retryAt: Date?
    /// Why the last manual refresh failed, other than being too soon.
    public private(set) var refreshFailure: String?
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

    /// Another engine's windows the daemon cannot give keep their last value.
    public func load() async throws {
        limits = try await api.usageLimits()
        for engine in Self.otherEngines {
            if let loaded = try? await api.usageLimits(provider: engine) {
                engineLimits[engine] = loaded
            }
        }
        try await loadPeriod()
    }

    /// The meter's lines: Claude's always, then each other engine signed in.
    public func meter(providers: ProvidersStore, now: Date) -> [UsageMeterLine] {
        shownEngines(providers).map { provider, name in
            UsageMeterLine(
                provider: provider, name: name,
                chip: UsageChip.of(limits(of: provider), now: now))
        }
    }

    /// "Claude: 5-hour: 30%, resets in 2h. Codex: not reported yet".
    public func meterTooltip(_ lines: [UsageMeterLine]) -> String {
        lines.map { "\($0.name): \($0.chip?.tooltip ?? "not reported yet")" }
            .joined(separator: ". ")
    }

    /// The popover's windows: Claude's alone without a heading, else each shown engine's
    /// under its name.
    public func limitGroups(providers: ProvidersStore) -> [UsageLimitGroup] {
        let engines = shownEngines(providers)
        return engines.map { provider, name in
            UsageLimitGroup(
                provider: provider, title: engines.count > 1 ? name : nil,
                limits: limits(of: provider))
        }
    }

    private func limits(of provider: String) -> UsageLimits? {
        provider == ProviderInfo.claude ? limits : engineLimits[provider]
    }

    /// Claude, then the other engines that said they are signed in.
    private func shownEngines(_ providers: ProvidersStore) -> [(String, String)] {
        let others = providers.providers.filter {
            $0.name != ProviderInfo.claude && $0.signedIn == true
        }
        return [(ProviderInfo.claude, providers.displayName(nil))]
            + others.map { ($0.name, $0.displayName) }
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

    /// When Claude last reported either window.
    private var reportedAt: Date? {
        [limits?.fiveHour?.updatedAt, limits?.sevenDay?.updatedAt].compactMap { $0 }.max()
    }

    /// The Refresh button's words: "as of 14:05" once Claude reported the limits.
    public var refreshTitle: String {
        UsageText.asOf(LimitWindow(utilization: 0, updatedAt: reportedAt), calendar: calendar)
            ?? "Refresh"
    }

    /// The limits were last reported more than 10 minutes before `date`.
    public func limitsAreStale(at date: Date) -> Bool {
        UsageText.isStale(LimitWindow(utilization: 0, updatedAt: reportedAt), now: date)
    }

    /// Asks Claude for the limits now. Too soon after the last ask, it notes when to try
    /// again instead.
    public func refresh() async {
        guard !isRefreshing else { return }
        isRefreshing = true
        defer { isRefreshing = false }
        for engine in Self.otherEngines {
            // An engine signed out or asked too soon keeps its windows; Claude's note stays.
            if let refreshed = try? await api.refreshUsage(provider: engine) {
                engineLimits[engine] = refreshed
            }
        }
        do {
            limits = try await api.refreshUsage()
            retryAt = nil
            refreshFailure = nil
        } catch APIError.rateLimited(_, let retryAfter) {
            retryAt = now().addingTimeInterval(TimeInterval(retryAfter ?? 20))
            refreshFailure = nil
        } catch APIError.badGateway {
            refreshFailure = "Claude did not report the limits"
        } catch {
            refreshFailure = "Could not refresh"
        }
    }

    /// "Try again in 12 s" while the daemon refuses a refresh, else the last failure.
    public func refreshNote(at date: Date) -> String? {
        if let retryAt, retryAt > date {
            return "Try again in \(Int(retryAt.timeIntervalSince(date).rounded(.up))) s"
        }
        return refreshFailure
    }

    /// "as of 14:05" for a window, in this store's calendar.
    public func asOfText(_ window: LimitWindow?) -> String? {
        UsageText.asOf(window, calendar: calendar)
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

    /// Windows from the engine replace the shown ones; Claude may report only one of them,
    /// another engine reports all of its windows at once.
    public func apply(_ event: Event) {
        if case .usageWarning(let warning) = event.body {
            self.warning = warning
            return
        }
        switch event.body {
        case .usageUpdated(let update):
            limits = Self.merge(update, into: limits, at: event.ts)
        case .providerUsageUpdated(let provider, let update):
            engineLimits[provider] = Self.merge(update, into: engineLimits[provider], at: event.ts)
        default:
            return
        }
    }

    private static func merge(_ update: UsageLimits, into limits: UsageLimits?, at ts: Date)
        -> UsageLimits
    {
        var merged = limits ?? UsageLimits()
        if let windows = update.windows {
            // Another engine reports its windows whole (B91).
            merged.windows = windows.map { window in
                var window = window
                window.updatedAt = ts
                return window
            }
        }
        if var window = update.fiveHour {
            window.updatedAt = ts
            merged.fiveHour = window
        }
        if var window = update.sevenDay {
            window.updatedAt = ts
            merged.sevenDay = window
        }
        return merged
    }
}
