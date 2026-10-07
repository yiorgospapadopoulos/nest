import Foundation

/// Why a running chat looks stuck (D036).
public enum StuckReason: String, UnknownSafeEnum {
    /// On a permission prompt, question or plan for too long.
    case waiting
    /// Running without any new output.
    case silent
    /// The same tool call with the same input, over and over.
    case repeating
    /// One turn running very long.
    case longTurn = "long_turn"
    case unknown

    public var label: String {
        switch self {
        case .waiting: "Waiting too long"
        case .silent: "No new output"
        case .repeating: "Repeating a call"
        case .longTurn: "Very long turn"
        case .unknown: "Looks stuck"
        }
    }
}

/// A session's stuck flag, as its `stuck` field and `session.stuck` events carry it.
public struct StuckFlag: Codable, Sendable, Hashable {
    public var reason: StuckReason
    /// When the condition began.
    public var since: Date
    /// One sentence, such as "Called Bash 5 times in a row with the same input".
    public var details: String

    public init(reason: StuckReason, since: Date, details: String) {
        self.reason = reason
        self.since = since
        self.details = details
    }

    /// The tooltip of the Stuck badge.
    public var help: String { "\(reason.label): \(details)" }

    /// What Send a nudge sends, interrupting the turn.
    public var nudge: String {
        "You seem stuck: \(details.prefix(1).lowercased() + details.dropFirst()). "
            + "Step back and try a different approach."
    }
}

/// The `[stuck]` thresholds of the daemon's settings; 0 turns a check off.
public struct StuckSettings: Codable, Sendable, Hashable {
    public var waitingMinutes: Int
    public var silentMinutes: Int
    public var repeatedCalls: Int
    public var turnMinutes: Int

    public init(waitingMinutes: Int, silentMinutes: Int, repeatedCalls: Int, turnMinutes: Int) {
        self.waitingMinutes = waitingMinutes
        self.silentMinutes = silentMinutes
        self.repeatedCalls = repeatedCalls
        self.turnMinutes = turnMinutes
    }

    enum CodingKeys: String, CodingKey {
        case waitingMinutes = "waiting_minutes"
        case silentMinutes = "silent_minutes"
        case repeatedCalls = "repeated_calls"
        case turnMinutes = "turn_minutes"
    }
}

/// One threshold of the Settings section, with its label and choices.
public enum StuckThreshold: Sendable, CaseIterable {
    case waiting, silent, repeated, turn

    public var title: String {
        switch self {
        case .waiting: "Waiting on a prompt"
        case .silent: "No new output"
        case .repeated: "Same call repeated"
        case .turn: "One turn running"
        }
    }

    public var keyPath: WritableKeyPath<StuckSettings, Int> {
        switch self {
        case .waiting: \.waitingMinutes
        case .silent: \.silentMinutes
        case .repeated: \.repeatedCalls
        case .turn: \.turnMinutes
        }
    }

    /// The menu's values, with the current one added when it is not among them.
    public func choices(including current: Int) -> [Int] {
        let base =
            switch self {
            case .waiting, .silent: [0, 5, 10, 15, 20, 30, 45, 60]
            case .repeated: [0, 3, 4, 5, 6, 8, 10]
            case .turn: [0, 30, 45, 60, 90, 120, 180]
            }
        return base.contains(current) ? base : (base + [current]).sorted()
    }

    /// "Off", "15 minutes", "1 hour 30 minutes" or "More than 4 times".
    public func label(_ value: Int) -> String {
        guard value > 0 else { return "Off" }
        if self == .repeated {
            return "More than \(value) times"
        }
        let hours = value / 60
        let minutes = value % 60
        let hourText = hours == 1 ? "1 hour" : "\(hours) hours"
        let minuteText = minutes == 1 ? "1 minute" : "\(minutes) minutes"
        if hours == 0 {
            return minuteText
        }
        return minutes == 0 ? hourText : "\(hourText) \(minuteText)"
    }
}
