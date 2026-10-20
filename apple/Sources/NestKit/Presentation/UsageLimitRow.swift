import Foundation

/// One window of an engine's usage, as the popover and the meter show it: Claude's
/// five-hour and weekly windows, or another engine's by length (B91).
public struct UsageLimitRow: Sendable, Equatable, Identifiable {
    /// The popover's name: "5 hour", "Weekly", "30 day".
    public let title: String
    /// The meter tooltip's name: "5-hour" for Claude's, else the title.
    public let name: String
    /// The meter's size when the reset time is not reported: "5h", "wk", "30d".
    public let size: String
    public let window: LimitWindow?

    public var id: String { title }

    /// "5h", "wk", "30d", "90m" from a window's length; empty without one.
    public static func size(_ minutes: Int?) -> String {
        guard let minutes else { return "" }
        if minutes == week { return "wk" }
        if minutes % day == 0 { return "\(minutes / day)d" }
        if minutes % 60 == 0 { return "\(minutes / 60)h" }
        return "\(minutes)m"
    }

    /// An engine's one row before it reported any window.
    static let unreported = UsageLimitRow(title: "Usage", name: "Usage", size: "", window: nil)

    private static let day = 24 * 60
    private static let week = 7 * day
}

extension UsageLimits {
    /// Another engine's windows as they come; else Claude's two, reported or not.
    public var rows: [UsageLimitRow] {
        guard let windows else {
            return [
                UsageLimitRow(title: "5 hour", name: "5-hour", size: "5h", window: fiveHour),
                UsageLimitRow(title: "Weekly", name: "Weekly", size: "wk", window: sevenDay),
            ]
        }
        return windows.map { window in
            let title = window.label ?? UsageLimitRow.unreported.title
            return UsageLimitRow(
                title: title, name: title, size: UsageLimitRow.size(window.minutes), window: window)
        }
    }
}

extension UsageLimitGroup {
    /// The popover's rows: Claude's two always; another engine's windows, or one row
    /// without numbers before it reported any.
    public var rows: [UsageLimitRow] {
        if provider != ProviderInfo.claude, limits?.windows?.isEmpty ?? true {
            return [.unreported]
        }
        return (limits ?? UsageLimits()).rows
    }
}
