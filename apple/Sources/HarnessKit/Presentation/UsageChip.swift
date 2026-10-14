import Foundation

/// The usage chip at the top right of the tab strip, as the approved design's footer chip shows a
/// provider's limits: each window as "30% 2h 5m" (used, then the time to its reset), a
/// bar for the tightest window, and a tooltip naming each reset.
public struct UsageChip: Sendable, Equatable {
    public enum Tone: Sendable, Equatable {
        /// Under 80 percent used.
        case neutral
        /// From 80 percent.
        case amber
        /// From 90 percent.
        case red
    }

    public struct Entry: Sendable, Equatable {
        /// "30% 2h 5m", or "30% 5h" when the reset time is not reported.
        public let text: String
        /// "30% used · Resets in 2h 5m".
        public let tooltip: String
    }

    public let entries: [Entry]
    /// The tightest window's used fraction, 0 to 1.
    public let used: Double

    public var tone: Tone { Self.tone(used: used) }
    public var tooltip: String { entries.map(\.tooltip).joined(separator: " · ") }

    /// Nil before Claude reported any window.
    public static func of(_ limits: UsageLimits?, now: Date) -> UsageChip? {
        let windows = [(limits?.fiveHour, "5h"), (limits?.sevenDay, "wk")]
            .compactMap { window, size in window.map { ($0, size) } }
        guard !windows.isEmpty else { return nil }
        let entries = windows.map { window, size in
            let percent = "\(Int((clamped(window.utilization) * 100).rounded()))%"
            guard let resetsAt = window.resetsAt else {
                return Entry(
                    text: "\(percent) \(size)", tooltip: "\(percent) used · \(size) window")
            }
            let left = duration(resetsAt.timeIntervalSince(now))
            let countdown = left == "now" ? "Resets now" : "Resets in \(left)"
            return Entry(text: "\(percent) \(left)", tooltip: "\(percent) used · \(countdown)")
        }
        let used = windows.map { clamped($0.0.utilization) }.reduce(0, max)
        return UsageChip(entries: entries, used: used)
    }

    public static func tone(used: Double) -> Tone {
        used >= 0.9 ? .red : used >= 0.8 ? .amber : .neutral
    }

    private static func clamped(_ used: Double) -> Double {
        min(max(used, 0), 1)
    }

    /// "45m", "2h 5m", "2h", "3d 4h", "3d", floored to whole units; "now" once due.
    public static func duration(_ interval: TimeInterval) -> String {
        guard interval > 0 else { return "now" }
        let minutes = Int(interval / 60)
        guard minutes >= 60 else { return "\(minutes)m" }
        let hours = minutes / 60
        if hours >= 24 {
            let rest = hours % 24
            return rest > 0 ? "\(hours / 24)d \(rest)h" : "\(hours / 24)d"
        }
        return minutes % 60 > 0 ? "\(hours)h \(minutes % 60)m" : "\(hours)h"
    }
}
