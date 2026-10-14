import Foundation

/// The status colors of the Mac look: running, needs you, ready for review and failed in
/// their quiet colors, interrupted and done in greys. A tone's dot and its word share one
/// color.
public enum StatusTone: Sendable, Hashable, CaseIterable {
    case running, waiting, review, failed, interrupted, done

    public var themedColor: ThemedColor {
        typealias Mac = DesignTokens.Colors.Mac
        return switch self {
        case .running: Mac.run
        case .waiting: Mac.wait
        case .review: Mac.ok
        case .failed: Mac.bad
        case .interrupted: Mac.textSecondary
        case .done: Mac.textTertiary
        }
    }

    /// The tone of a session's dot; `hasReview` is true while work waits for review, or a
    /// pull request to merge.
    public static func of(_ state: SessionState, hasReview: Bool) -> StatusTone {
        switch state {
        case .starting, .running: .running
        case .waiting: .waiting
        case .failed: .failed
        case .interrupted: .interrupted
        default: hasReview ? .review : .done
        }
    }
}

public enum Theme {
    public static func accent(_ name: AccentName) -> AccentColor {
        switch name {
        case .graphite: DesignTokens.Accent.graphite
        case .ocean: DesignTokens.Accent.ocean
        case .teal: DesignTokens.Accent.teal
        case .moss: DesignTokens.Accent.moss
        case .clay: DesignTokens.Accent.clay
        case .rose: DesignTokens.Accent.rose
        }
    }
}
