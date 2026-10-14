import Foundation

/// What a pane's header and composer show at the pane's width, as the mockup's container
/// queries: the elapsed time goes first, then the branch, then the status label (the dot
/// stays) and the pull request chip. The composer shortens, then hides, the context and
/// shortens the model's name; attach, dictation and send always stay.
public struct PaneFit: Sendable, Equatable {
    public enum ContextStyle: Sendable, Equatable {
        case full, percent, hidden

        public func label(_ context: SessionContext) -> String? {
            switch self {
            case .full: context.label
            case .percent: "\(Int(context.percent.rounded()))%"
            case .hidden: nil
            }
        }
    }

    public let showsElapsed: Bool
    public let showsBranch: Bool
    public let showsStatusLabel: Bool
    public let showsPullRequest: Bool
    public let context: ContextStyle
    /// Tighter composer selectors with short labels: "Sonnet" for "Sonnet 5.5", "Med"
    /// for "Medium", "Edits" for "Accept edits".
    public let compact: Bool

    public init(width: Double) {
        showsElapsed = width >= 470
        showsBranch = width >= 420
        showsStatusLabel = width >= 380
        showsPullRequest = width >= 330
        context = width >= 460 ? .full : width >= 360 ? .percent : .hidden
        compact = width < 380
    }

    /// A model's name without its version.
    public static func shortModel(_ label: String) -> String {
        label.split(separator: " ").first.map(String.init) ?? label
    }
}

extension Effort {
    /// The compact composer's label.
    public var shortLabel: String {
        switch self {
        case .medium: "Med"
        case .xhigh: "X-high"
        default: label
        }
    }
}

extension PermissionMode {
    /// The compact composer's label.
    public var shortLabel: String {
        self == .acceptEdits ? "Edits" : label
    }

    /// The compact label of a mode, or "Default" for Claude Code's own setting (nil).
    public static func shortLabel(_ mode: PermissionMode?) -> String {
        mode?.shortLabel ?? "Default"
    }
}
