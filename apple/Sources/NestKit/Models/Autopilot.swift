import Foundation

/// Why an Autopilot run ended (B120).
public enum AutopilotEnd: String, UnknownSafeEnum {
    case done, time, stuck, errors, stopped, off
    case weeklyCap = "weekly_cap"
    case unknown
}

/// What Nest settled for the user during a run.
public enum AutopilotDecisionKind: String, UnknownSafeEnum {
    case question, plan, allowed, denied
    case unknown
}

/// An option a question offered.
public struct DecisionOption: Codable, Sendable, Hashable {
    public var label: String
    public var description: String?
    public var picked: Bool

    public init(label: String, description: String? = nil, picked: Bool = false) {
        self.label = label
        self.description = description
        self.picked = picked
    }
}

public struct AutopilotDecision: Codable, Sendable, Hashable {
    public var kind: AutopilotDecisionKind
    /// The question, the plan's first line or the tool call.
    public var title: String
    /// The answer chosen. A denied call stored before `reason` says why here.
    public var answer: String
    public var at: Date
    /// What a question offered; empty for a permission or a plan.
    public var options: [DecisionOption]
    /// Why, in words that come only from what the agent or the engine gave.
    public var reason: String?
    /// A plan's text.
    public var detail: String?

    public init(
        kind: AutopilotDecisionKind, title: String, answer: String, at: Date,
        options: [DecisionOption] = [], reason: String? = nil, detail: String? = nil
    ) {
        self.kind = kind
        self.title = title
        self.answer = answer
        self.at = at
        self.options = options
        self.reason = reason
        self.detail = detail
    }

    enum CodingKeys: String, CodingKey {
        case kind, title, answer, at, options, reason, detail
    }

    /// Decisions stored before the run kept the options, the reason and the plan's text.
    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        kind = try container.decode(AutopilotDecisionKind.self, forKey: .kind)
        title = try container.decode(String.self, forKey: .title)
        answer = try container.decode(String.self, forKey: .answer)
        at = try container.decode(Date.self, forKey: .at)
        options = try container.decodeIfPresent([DecisionOption].self, forKey: .options) ?? []
        reason = try container.decodeIfPresent(String.self, forKey: .reason)
        detail = try container.decodeIfPresent(String.self, forKey: .detail)
    }

    /// What its line shows after the title.
    public var shownAnswer: String { kind == .denied ? "Denied" : answer }

    /// Why it went this way.
    public var why: String? { reason ?? (kind == .denied ? answer : nil) }

    /// Whether its line has anything to open to.
    public var opens: Bool { !options.isEmpty || detail != nil || why != nil }
}

/// A run in progress; the chat stays in Bypass meanwhile.
public struct AutopilotRun: Codable, Sendable, Hashable {
    public var startedAt: Date
    /// When the time budget runs out; nil without one.
    public var until: Date?
    /// The percentage of the weekly usage window at which the run stops.
    public var weeklyCap: Int?
    public var decisions: [AutopilotDecision]

    public init(
        startedAt: Date, until: Date? = nil, weeklyCap: Int? = nil,
        decisions: [AutopilotDecision] = []
    ) {
        self.startedAt = startedAt
        self.until = until
        self.weeklyCap = weeklyCap
        self.decisions = decisions
    }

    enum CodingKeys: String, CodingKey {
        case until, decisions
        case startedAt = "started_at"
        case weeklyCap = "weekly_cap"
    }
}

/// What a finished run did; it stays in the chat like a message.
public struct AutopilotReport: Codable, Sendable, Hashable {
    public var ended: AutopilotEnd
    public var summary: String?
    public var decisions: [AutopilotDecision]

    public init(ended: AutopilotEnd, summary: String?, decisions: [AutopilotDecision]) {
        self.ended = ended
        self.summary = summary
        self.decisions = decisions
    }
}

/// What may stop a run earlier than done; empty, it runs until the task is done.
public struct AutopilotBudget: Sendable, Hashable {
    public var stopAfterMinutes: Int?
    public var weeklyCap: Int?

    public init(stopAfterMinutes: Int? = nil, weeklyCap: Int? = nil) {
        self.stopAfterMinutes = stopAfterMinutes
        self.weeklyCap = weeklyCap
    }

    /// The daemon counts `until` from the run's start, also for a budget given later.
    public init(run: AutopilotRun) {
        stopAfterMinutes = run.until.map {
            Int(($0.timeIntervalSince(run.startedAt) / 60).rounded())
        }
        weeklyCap = run.weeklyCap
    }
}

/// `PUT /api/sessions/{id}/autopilot`, and `autopilot` on a new chat. Both budget fields are
/// always sent: on a run in progress this budget replaces its budget whole.
public struct SetAutopilotRequest: Encodable, Sendable, Hashable {
    public var on: Bool
    public var budget: AutopilotBudget

    public init(on: Bool, budget: AutopilotBudget = AutopilotBudget()) {
        self.on = on
        self.budget = budget
    }

    enum CodingKeys: String, CodingKey {
        case on
        case stopAfterMinutes = "stop_after_minutes"
        case weeklyCap = "weekly_cap"
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(on, forKey: .on)
        try container.encode(budget.stopAfterMinutes, forKey: .stopAfterMinutes)
        try container.encode(budget.weeklyCap, forKey: .weeklyCap)
    }
}
