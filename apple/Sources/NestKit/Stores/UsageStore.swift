import Foundation
import Observation

/// One day of the usage calendar.
public struct UsageDayCell: Sendable, Hashable, Identifiable {
    public let day: CalendarDay
    public let tokens: Int
    public let sessions: Int
    public let isToday: Bool
    public let isFuture: Bool

    public var id: CalendarDay { day }
}

/// Subscription limits and the monthly token calendar of the usage popover.
@MainActor @Observable
public final class UsageStore {
    public private(set) var limits: UsageLimits?
    public private(set) var month: UsageMonth?
    /// The month shown, starting with the current one.
    public private(set) var year: Int
    public private(set) var monthNumber: Int
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
        let today = calendar.dateComponents([.year, .month], from: now())
        year = today.year!
        monthNumber = today.month!
    }

    public func load() async throws {
        limits = try await api.usageLimits()
        try await loadMonth()
    }

    public func loadMonth() async throws {
        let shown = (year, monthNumber)
        let loaded = try await api.usageMonth(year: shown.0, month: shown.1)
        // A newer navigation may have moved on while this one loaded.
        if (year, monthNumber) == shown {
            month = loaded
        }
    }

    /// Asks Claude for the limits now. Too soon after the last ask, it notes when to try
    /// again instead.
    public func refresh() async {
        guard !isRefreshing else { return }
        isRefreshing = true
        defer { isRefreshing = false }
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

    /// Later months are not shown beyond the current one.
    public var canShowNextMonth: Bool {
        let today = calendar.dateComponents([.year, .month], from: now())
        return (year, monthNumber) < (today.year!, today.month!)
    }

    public func showPreviousMonth() async throws {
        (year, monthNumber) = monthNumber == 1 ? (year - 1, 12) : (year, monthNumber - 1)
        month = nil
        try await loadMonth()
    }

    public func showNextMonth() async throws {
        guard canShowNextMonth else { return }
        (year, monthNumber) = monthNumber == 12 ? (year + 1, 1) : (year, monthNumber + 1)
        month = nil
        try await loadMonth()
    }

    /// Weeks start on Monday; leading nils fill the days before the 1st.
    public var cells: [UsageDayCell?] {
        guard let month else { return [] }
        let first = calendar.date(
            from: DateComponents(year: month.year, month: month.month, day: 1))!
        let leading = (calendar.component(.weekday, from: first) + 5) % 7
        let parts = calendar.dateComponents([.year, .month, .day], from: now())
        let today = CalendarDay(year: parts.year!, month: parts.month!, day: parts.day!)
        let days = month.days.map { day in
            UsageDayCell(
                day: day.date, tokens: day.tokens, sessions: day.sessions,
                isToday: day.date == today, isFuture: day.date > today)
        }
        return Array(repeating: nil, count: leading) + days
    }

    public var totalTokens: Int { month?.tokens.total ?? 0 }
    public var totalSessions: Int { month?.sessions ?? 0 }

    /// The month's usage checks, counted apart.
    public var probesText: String? { UsageText.probes(month?.probes) }

    /// The busiest day's tokens, to scale the calendar's shading.
    public var peakDayTokens: Int { month?.days.map(\.tokens).max() ?? 0 }

    public var monthTitle: String { UsageText.monthTitle(year: year, month: monthNumber) }

    /// When a limit window resets, in this store's calendar.
    public func resetText(_ window: LimitWindow?) -> String {
        UsageText.reset(window, now: now(), calendar: calendar)
    }

    /// The hover detail of a calendar day.
    public func detail(of cell: UsageDayCell) -> (title: String, detail: String) {
        UsageText.dayDetail(cell, calendar: calendar)
    }

    /// Windows from the engine replace the shown ones; it may report only one of them.
    public func apply(_ event: Event) {
        if case .usageWarning(let warning) = event.body {
            self.warning = warning
            return
        }
        guard case .usageUpdated(let update) = event.body else { return }
        var merged = limits ?? UsageLimits(fiveHour: nil, sevenDay: nil)
        if var window = update.fiveHour {
            window.updatedAt = event.ts
            merged.fiveHour = window
        }
        if var window = update.sevenDay {
            window.updatedAt = event.ts
            merged.sevenDay = window
        }
        limits = merged
    }
}
