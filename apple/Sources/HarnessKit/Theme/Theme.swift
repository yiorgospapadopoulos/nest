import Foundation

/// The fixed status colors: running blue, needs you amber, review green, failed red,
/// interrupted grey-brown, done grey.
public enum StatusTone: Sendable, Hashable, CaseIterable {
    case running, waiting, review, failed, interrupted, done

    public var fill: ThemedColor {
        switch self {
        case .running: DesignTokens.Status.Running.fill
        case .waiting: DesignTokens.Status.Waiting.fill
        case .review: DesignTokens.Status.Review.fill
        case .failed: DesignTokens.Status.Failed.fill
        case .interrupted: DesignTokens.Status.Interrupted.fill
        case .done: DesignTokens.Status.Done.fill
        }
    }

    public var text: ThemedColor {
        switch self {
        case .running: DesignTokens.Status.Running.text
        case .waiting: DesignTokens.Status.Waiting.text
        case .review: DesignTokens.Status.Review.text
        case .failed: DesignTokens.Status.Failed.text
        case .interrupted: DesignTokens.Status.Interrupted.text
        case .done: DesignTokens.Status.Done.text
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
