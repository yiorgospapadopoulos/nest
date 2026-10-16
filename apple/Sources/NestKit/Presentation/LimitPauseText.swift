import Foundation

/// The words of a paused chat's notice above the composer (B78).
public enum LimitPauseText {
    /// "5-hour", "weekly", "weekly Opus", "weekly Sonnet", "extra usage", or "usage" when
    /// Claude Code did not say which limit it was.
    public static func windowLabel(_ window: LimitPauseWindow?) -> String {
        switch window {
        case .fiveHour: "5-hour"
        case .sevenDay: "weekly"
        case .sevenDayOpus: "weekly Opus"
        case .sevenDaySonnet: "weekly Sonnet"
        case .overage: "extra usage"
        case .unknown, nil: "usage"
        }
    }

    /// "Paused at the 5-hour limit".
    public static func title(_ pause: LimitPause) -> String {
        "Paused at the \(windowLabel(pause.window)) limit"
    }

    /// "in 2 d 5 h", "in 1 h 12 min", "in 45 min", "in 4 min 12 s" (seconds only in the last
    /// five minutes), "in 45 s", floored to whole units; "any moment now" once due.
    public static func countdown(to date: Date, now: Date) -> String {
        let total = Int(date.timeIntervalSince(now).rounded(.down))
        guard total >= 1 else { return "any moment now" }
        let (days, hours, minutes, seconds) =
            (total / 86_400, total % 86_400 / 3600, total % 3600 / 60, total % 60)
        func pair(_ big: Int, _ bigUnit: String, _ small: Int, _ smallUnit: String) -> String {
            small > 0 ? "in \(big) \(bigUnit) \(small) \(smallUnit)" : "in \(big) \(bigUnit)"
        }
        if days > 0 {
            return pair(days, "d", hours, "h")
        }
        if hours > 0 {
            return pair(hours, "h", minutes, "min")
        }
        if minutes >= 5 {
            return "in \(minutes) min"
        }
        return minutes > 0 ? pair(minutes, "min", seconds, "s") : "in \(seconds) s"
    }

    /// A local time: "14:05" on the same day, "Wed 11:00" within six days, else
    /// "12 Oct 12:00".
    public static func time(_ date: Date, now: Date, calendar: Calendar) -> String {
        let parts = calendar.dateComponents([.month, .day, .weekday, .hour, .minute], from: date)
        let clock = String(format: "%02d:%02d", parts.hour!, parts.minute!)
        if calendar.isDate(date, inSameDayAs: now) {
            return clock
        }
        if date > now, date.timeIntervalSince(now) < 6 * 86_400 {
            return "\(UsageText.weekdays[parts.weekday! - 1]) \(clock)"
        }
        return "\(parts.day!) \(UsageText.shortMonths[parts.month! - 1]) \(clock)"
    }

    /// "Resets 14:00, goes on in 1 h 12 min"; without a reported reset time the daemon
    /// only tries again: "Reset time not reported, tries again in 28 min".
    public static func schedule(_ pause: LimitPause, now: Date, calendar: Calendar) -> String {
        let left = countdown(to: pause.resumeAt, now: now)
        guard let resetsAt = pause.resetsAt else {
            return "Reset time not reported, tries again \(left)"
        }
        return "Resets \(time(resetsAt, now: now, calendar: calendar)), goes on \(left)"
    }

    /// What the chat does once it goes on: send the queued messages, else continue.
    public static func plan(queued: Int) -> String {
        switch queued {
        case 0: "Then it continues where it left off."
        case 1: "Then your queued message sends."
        default: "Then your \(queued) queued messages send, in order."
        }
    }
}

/// Nest's continue message after the usage limit reset, shown as Nest's (B78).
public enum LimitResumeNote {
    public static let title = "Resumed after the usage limit"

    /// "Nest: Continue where you left off."
    public static func text(_ message: String) -> String {
        "Nest: \(message)"
    }
}
