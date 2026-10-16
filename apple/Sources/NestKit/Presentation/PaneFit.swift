import Foundation

/// What a pane's header and composer show at the pane's width. A chat's header keeps its
/// name first (B60): it drops the pull request chip, then shortens who started the chat.
/// A pixie's header shortens its Details button to the icon, then drops its status word
/// and @slug. The composer shortens where the chat works to its icon (B71), shortens,
/// then hides, the context and shortens the model's name; attach, dictation and send
/// always stay.
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

    /// The word beside the icon of a pixie's Details button.
    public let showsDetailsLabel: Bool
    /// Who started a chat in full and a pixie's @slug, in a header.
    public let showsHeaderDetails: Bool
    /// The branch or worktree name beside its icon in the composer, where the model,
    /// thinking, permission and full context still fit beside it; narrower panes show the
    /// icon only.
    public let showsPlaceName: Bool
    /// The status word beside its dot, in a pixie's header; a chat's header shows the dot.
    public let showsStatusLabel: Bool
    public let showsPullRequest: Bool
    public let context: ContextStyle
    /// Tighter composer selectors with short labels: "Sonnet" for "Sonnet 5.5", "Med"
    /// for "Medium", "Edits" for "Accept edits".
    public let compact: Bool

    public init(width: Double) {
        showsDetailsLabel = width >= 480
        showsPullRequest = width >= 420
        showsHeaderDetails = width >= 360
        showsPlaceName = width >= 560
        showsStatusLabel = width >= 380
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
