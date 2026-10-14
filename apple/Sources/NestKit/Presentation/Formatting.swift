import Foundation

/// Short elapsed times such as "now", "9m", "1h 12m" or "3d".
public enum Elapsed {
    public static func short(_ seconds: TimeInterval) -> String {
        let minutes = Int(max(0, seconds) / 60)
        if minutes < 1 {
            return "now"
        }
        if minutes < 60 {
            return "\(minutes)m"
        }
        if minutes < 24 * 60 {
            let rest = minutes % 60
            return "\(minutes / 60)h" + (rest > 0 ? " \(rest)m" : "")
        }
        return "\(minutes / (24 * 60))d"
    }

    public static func short(from start: Date, to end: Date) -> String {
        short(end.timeIntervalSince(start))
    }

    /// A run time with seconds while short: "8s", "3m 4s", then as `short`, "1h 12m".
    public static func duration(from start: Date, to end: Date) -> String {
        duration(seconds: end.timeIntervalSince(start))
    }

    /// As `duration(from:to:)`, for a number of seconds.
    public static func duration(seconds interval: TimeInterval) -> String {
        let seconds = Int(max(0, interval))
        if seconds < 60 {
            return "\(seconds)s"
        }
        if seconds < 3600 {
            let rest = seconds % 60
            return "\(seconds / 60)m" + (rest > 0 ? " \(rest)s" : "")
        }
        return short(Double(seconds))
    }
}

/// Up to two capital letters for avatars and project marks.
public enum Initials {
    public static func of(_ text: String) -> String {
        let words = text.split { !$0.isLetter && !$0.isNumber }
        guard let first = words.first?.first else { return "?" }
        let second = words.dropFirst().first?.first.map(String.init) ?? ""
        return (String(first) + second).uppercased()
    }
}

/// The color of a project's mark, stable for its name.
public enum ProjectMark {
    public static func colorIndex(for name: String, count: Int) -> Int {
        guard count > 0 else { return 0 }
        let sum = name.unicodeScalars.reduce(0) { $0 + Int($1.value) }
        return sum % count
    }
}

extension Effort {
    public var label: String {
        switch self {
        case .low: "Low"
        case .medium: "Medium"
        case .high: "High"
        case .xhigh: "Extra high"
        case .max: "Max"
        case .unknown: "Unknown"
        }
    }
}

extension PermissionMode {
    /// What nil reads as: no mode is passed, so Claude Code's own `defaultMode` applies.
    public static let claudeCodeDefaultLabel = "Claude Code default"
    public static let claudeCodeDefaultSummary = "Your Claude Code setting applies"

    /// A mode's label, or the Claude Code default's for nil.
    public static func label(_ mode: PermissionMode?) -> String {
        mode?.label ?? claudeCodeDefaultLabel
    }

    /// The one-line description the permission menu shows.
    public var summary: String {
        switch self {
        case .default: "Asks before edits and commands"
        case .acceptEdits: "Edits files without asking"
        case .plan: "Reads and plans only"
        case .bypassPermissions: "Runs everything without asking"
        case .auto: "Asks only when Claude Code judges an action risky"
        case .unknown: ""
        }
    }
}

extension PermissionMode {
    /// How a chat can go on once its plan is approved: auto-accepting edits (the default),
    /// asking before each edit, or Auto where the model supports it.
    public static func planChoices(supportsAuto: Bool) -> [PermissionMode] {
        supportsAuto ? [.acceptEdits, .default, .auto] : [.acceptEdits, .default]
    }

    /// A plan choice's words on the plan card.
    public var planChoiceLabel: String {
        switch self {
        case .default: "Approve edits manually"
        case .auto: "Auto"
        default: "Auto-accept edits"
        }
    }
}
