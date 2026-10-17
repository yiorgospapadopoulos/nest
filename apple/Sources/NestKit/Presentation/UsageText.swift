import Foundation

/// The words and numbers of the usage button and popover.
public enum UsageText {
    static let months = [
        "January", "February", "March", "April", "May", "June", "July", "August", "September",
        "October", "November", "December",
    ]
    static let weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    static let shortMonths = months.map { String($0.prefix(3)) }

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

    /// "12 usage checks, 5k tokens, not counted above"; nil when there were none.
    public static func probes(_ probes: ProbeTotals?) -> String? {
        guard let probes, probes.count > 0 else { return nil }
        let checks = probes.count == 1 ? "1 usage check" : "\(probes.count) usage checks"
        return "\(checks), \(tokens(probes.tokens)) tokens, not counted above"
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

    /// "1 chat", "74 chats".
    public static func chats(_ count: Int) -> String {
        count == 1 ? "1 chat" : "\(count) chats"
    }

    /// A part of a total in percent: "89%", "0.7%", "0.01%", "<0.01%"; "0%" for nothing.
    public static func share(_ part: Int, of total: Int) -> String {
        guard part > 0, total > 0 else { return "0%" }
        let percent = Double(part) / Double(total) * 100
        if percent >= 1 {
            return "\(Int(percent.rounded()))%"
        }
        if percent >= 0.1 {
            return String(format: "%.1f%%", percent)
        }
        return percent >= 0.005 ? String(format: "%.2f%%", percent) : "<0.01%"
    }

    /// Where the period of `unit` holding `date` starts: its day, its Monday, the 1st of
    /// its month or 1 January.
    public static func periodStart(of date: Date, unit: UsageUnit, calendar: Calendar) -> Date {
        let day = calendar.startOfDay(for: date)
        switch unit {
        case .day:
            return day
        case .week:
            let sinceMonday = (calendar.component(.weekday, from: day) + 5) % 7
            return calendar.date(byAdding: .day, value: -sinceMonday, to: day)!
        case .month:
            return calendar.date(from: calendar.dateComponents([.year, .month], from: day))!
        case .year:
            return calendar.date(from: calendar.dateComponents([.year], from: day))!
        }
    }

    /// A period's start moved by `count` periods.
    public static func shift(_ start: Date, unit: UsageUnit, by count: Int, calendar: Calendar)
        -> Date
    {
        let component: Calendar.Component =
            switch unit {
            case .day: .day
            case .week: .weekOfYear
            case .month: .month
            case .year: .year
            }
        return calendar.date(byAdding: component, value: count, to: start)!
    }

    /// "Today", "Fri 16 Oct", "12 to 18 Oct", "28 Sep to 4 Oct", "October", "October 2025"
    /// for a month of another year, "2026".
    public static func periodTitle(start: Date, unit: UsageUnit, now: Date, calendar: Calendar)
        -> String
    {
        let parts = calendar.dateComponents([.year, .month, .day], from: start)
        switch unit {
        case .day:
            return calendar.isDate(start, inSameDayAs: now) ? "Today" : day(start, calendar)
        case .week:
            let end = calendar.date(byAdding: .day, value: 6, to: start)!
            let last = calendar.dateComponents([.month, .day], from: end)
            let first =
                last.month == parts.month
                ? "\(parts.day!)" : "\(parts.day!) \(shortMonths[parts.month! - 1])"
            return "\(first) to \(last.day!) \(shortMonths[last.month! - 1])"
        case .month:
            let month = months[parts.month! - 1]
            let thisYear = calendar.component(.year, from: now)
            return parts.year == thisYear ? month : "\(month) \(parts.year!)"
        case .year:
            return "\(parts.year!)"
        }
    }

    /// "Wed 14 Oct".
    static func day(_ date: Date, _ calendar: Calendar) -> String {
        let parts = calendar.dateComponents([.month, .day, .weekday], from: date)
        return "\(weekdays[parts.weekday! - 1]) \(parts.day!) \(shortMonths[parts.month! - 1])"
    }

    /// A bar's hover detail: "Wed 14 Oct: 3.4M tokens, 12 chats", "14:00: ..." for an hour,
    /// "October: ..." for a month.
    public static func barTip(_ bar: PeriodBar, unit: UsageUnit, calendar: Calendar) -> String {
        let label =
            switch unit {
            case .day:
                String(format: "%02d:00", calendar.component(.hour, from: bar.start))
            case .week, .month:
                day(bar.start, calendar)
            case .year:
                months[calendar.component(.month, from: bar.start) - 1]
            }
        return "\(label): \(tokens(bar.tokens)) tokens, \(chats(bar.sessions))"
    }

    /// The labels under a period's bars, spread from the first bar to the last.
    public static func ticks(unit: UsageUnit, bars: Int) -> [String] {
        switch unit {
        case .day: ["0", "6", "12", "18", "23"]
        case .week: ["Mo", "We", "Fr", "Su"]
        case .month: ["1", "8", "15", "22", "\(bars)"]
        case .year: ["Jan", "Apr", "Jul", "Oct", "Dec"]
        }
    }

    /// A bar's height in points: 1 for no tokens, at least 3 for any, `full` for the peak.
    public static func barHeight(tokens: Int, peak: Int, full: Double) -> Double {
        guard tokens > 0, peak > 0 else { return 1 }
        return max(3, (full * Double(tokens) / Double(peak)).rounded())
    }
}
