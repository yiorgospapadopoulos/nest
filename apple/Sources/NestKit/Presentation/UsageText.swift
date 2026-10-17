import Foundation

/// The words and numbers of the usage button and popover.
public enum UsageText {
    static let months = [
        "January", "February", "March", "April", "May", "June", "July", "August", "September",
        "October", "November", "December",
    ]
    static let weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    static let shortMonths = months.map { String($0.prefix(3)) }

    /// Calendar column heads, Monday first.
    public static let weekdayHeads = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]

    /// "30%", or "-" before Claude reported the window.
    public static func percent(_ window: LimitWindow?) -> String {
        window.map { "\(Int(($0.utilization * 100).rounded()))%" } ?? "-"
    }

    /// "Resets 18:30" today, "Resets Mon 09:00" within a week, else "Resets 14 Oct".
    public static func reset(_ window: LimitWindow?, now: Date, calendar: Calendar) -> String {
        guard let window else { return "Not reported yet" }
        guard let date = window.resetsAt else { return "Reset time not reported" }
        let parts = calendar.dateComponents([.month, .day, .weekday, .hour, .minute], from: date)
        let time = String(format: "%02d:%02d", parts.hour!, parts.minute!)
        if calendar.isDate(date, inSameDayAs: now) {
            return "Resets \(time)"
        }
        if date > now, date.timeIntervalSince(now) < 6 * 24 * 3600 {
            return "Resets \(weekdays[parts.weekday! - 1]) \(time)"
        }
        return "Resets \(parts.day!) \(shortMonths[parts.month! - 1])"
    }

    /// Limits reported longer ago than this are shown dimmed.
    public static let staleAfter: TimeInterval = 10 * 60

    /// "as of 14:05", when the window was last reported; nil before it was.
    public static func asOf(_ window: LimitWindow?, calendar: Calendar) -> String? {
        guard let date = window?.updatedAt else { return nil }
        let parts = calendar.dateComponents([.hour, .minute], from: date)
        return String(format: "as of %02d:%02d", parts.hour!, parts.minute!)
    }

    /// Whether the window's numbers are more than 10 minutes old.
    public static func isStale(_ window: LimitWindow?, now: Date) -> Bool {
        guard let date = window?.updatedAt else { return false }
        return now.timeIntervalSince(date) > staleAfter
    }

    /// "You have used 82% of your 5 hour limit. Resets 18:30." for a `usage.warning`.
    public static func warning(_ warning: UsageWarning, now: Date, calendar: Calendar) -> String {
        let percent = Int((warning.utilization * 100).rounded())
        let limit = warning.window == .fiveHour ? "5 hour" : "weekly"
        let window = LimitWindow(utilization: warning.utilization, resetsAt: warning.resetsAt)
        let reset =
            warning.resetsAt == nil
            ? "" : " \(UsageText.reset(window, now: now, calendar: calendar))."
        return "You have used \(percent)% of your \(limit) limit.\(reset)"
    }

    /// The warning levels offered in Settings, in percent; nil is off.
    public static let warnChoices: [Int?] = [70, 80, 90, nil]

    /// "80%", or "Off".
    public static func warnLevel(_ percent: Int?) -> String {
        percent.map { "\($0)%" } ?? "Off"
    }

    /// The refresh intervals offered in Settings, in minutes; 0 is off.
    public static let refreshChoices = [0, 1, 3, 5, 10, 15]

    /// "Off", "Every minute", "Every 3 minutes"; "-" before the setting loaded.
    public static func refreshInterval(_ minutes: Int?) -> String {
        switch minutes {
        case nil: "-"
        case 0: "Off"
        case 1: "Every minute"
        case let minutes?: "Every \(minutes) minutes"
        }
    }

    /// "12 usage checks used 5k tokens, not counted above."; nil when there were none.
    public static func probes(_ probes: ProbeTotals?) -> String? {
        guard let probes, probes.count > 0 else { return nil }
        let checks = probes.count == 1 ? "1 usage check" : "\(probes.count) usage checks"
        return "\(checks) used \(tokens(probes.tokens)) tokens, not counted above."
    }

    /// "October 2026".
    public static func monthTitle(year: Int, month: Int) -> String {
        "\(months[month - 1]) \(year)"
    }

    /// Compact token counts: "940", "340k", "1.2M", "12M".
    public static func tokens(_ count: Int) -> String {
        if count < 1000 {
            return "\(count)"
        }
        if count < 999_500 {
            return "\(Int((Double(count) / 1000).rounded()))k"
        }
        let millions = (Double(count) / 1_000_000 * 10).rounded() / 10
        return millions == millions.rounded() ? "\(Int(millions))M" : "\(millions)M"
    }

    /// The hover detail of a calendar day: "Tue 6 Oct" and "1,234,567 tokens, 3 sessions".
    public static func dayDetail(_ cell: UsageDayCell, calendar: Calendar) -> (
        title: String, detail: String
    ) {
        let date = calendar.date(
            from: DateComponents(year: cell.day.year, month: cell.day.month, day: cell.day.day))!
        let weekday = weekdays[calendar.component(.weekday, from: date) - 1]
        let title = "\(weekday) \(cell.day.day) \(shortMonths[cell.day.month - 1])"
        guard cell.tokens > 0 else { return (title, "No sessions") }
        let grouped = cell.tokens.formatted(
            .number.grouping(.automatic).locale(Locale(identifier: "en_US")))
        let sessions = cell.sessions == 1 ? "1 session" : "\(cell.sessions) sessions"
        return (title, "\(grouped) tokens, \(sessions)")
    }

    /// How strongly a day is shaded, from 0 (no tokens) up to 0.68 for the busiest day.
    public static func shade(tokens: Int, peak: Int) -> Double {
        guard tokens > 0, peak > 0 else { return 0 }
        return 0.08 + 0.6 * Double(tokens) / Double(peak)
    }

    /// Strongly shaded days draw their text on the accent.
    public static func isStrong(shade: Double) -> Bool {
        shade > 0.45
    }
}
