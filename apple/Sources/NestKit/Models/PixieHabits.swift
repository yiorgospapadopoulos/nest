import Foundation

// A pixie's habits, their runs and the reports pixies make (B42).

public enum HabitScheduleKind: String, Codable, Sendable, CaseIterable, UnknownSafeEnum {
    case hourly, daily, weekdays, weekly
    case unknown
}

/// When a habit runs, in the Mac's local time: hourly at a minute, daily or on weekdays at
/// "HH:MM", or weekly on a weekday (Monday is 0) at "HH:MM".
public struct HabitSchedule: Codable, Sendable, Hashable {
    public var kind: HabitScheduleKind
    public var minute: Int?
    public var time: String?
    public var weekday: Int?

    public init(kind: HabitScheduleKind, minute: Int?, time: String?, weekday: Int?) {
        self.kind = kind
        self.minute = minute
        self.time = time
        self.weekday = weekday
    }

    public static func hourly(minute: Int?) -> HabitSchedule {
        HabitSchedule(kind: .hourly, minute: minute, time: nil, weekday: nil)
    }

    public static func daily(_ time: String?) -> HabitSchedule {
        HabitSchedule(kind: .daily, minute: nil, time: time, weekday: nil)
    }

    public static func weekdays(_ time: String?) -> HabitSchedule {
        HabitSchedule(kind: .weekdays, minute: nil, time: time, weekday: nil)
    }

    public static func weekly(weekday: Int?, time: String?) -> HabitSchedule {
        HabitSchedule(kind: .weekly, minute: nil, time: time, weekday: weekday)
    }
}

/// What in the pixie's projects starts a habit.
public enum HabitTrigger: String, Codable, Sendable, CaseIterable, UnknownSafeEnum {
    case stuck, failed
    case reviewReady = "review_ready"
    case ciFailed = "ci_failed"
    case unknown
}

public enum HabitRunOutcome: String, Codable, Sendable, CaseIterable, UnknownSafeEnum {
    case queued, running, reported, quiet, failed, stalled
    case timedOut = "timed_out"
    case skipped
    case unknown
}

/// One run of a habit, from `GET .../runs` and `habit.run_updated`.
public struct HabitRun: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var habitID: String
    public var pixieID: String
    /// The run's own session, read-only, for Open transcript.
    public var sessionID: String?
    public var dueAt: Date?
    public var startedAt: Date?
    public var endedAt: Date?
    public var outcome: HabitRunOutcome
    /// Why it was skipped or failed, such as "late" or "usage".
    public var reason: String?
    public var reportTitle: String?

    enum CodingKeys: String, CodingKey {
        case id, outcome, reason
        case habitID = "habit_id"
        case pixieID = "pixie_id"
        case sessionID = "session_id"
        case dueAt = "due_at"
        case startedAt = "started_at"
        case endedAt = "ended_at"
        case reportTitle = "report_title"
    }
}

/// A recurring or event-triggered task a pixie runs in a fresh background session.
public struct PixieHabit: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var pixieID: String
    public var name: String
    public var prompt: String
    public var schedule: HabitSchedule?
    public var triggers: [HabitTrigger]
    public var maxMinutes: Int
    public var enabled: Bool
    public var createdAt: Date
    public var updatedAt: Date
    public var nextDueAt: Date?
    public var lastRun: HabitRun?

    enum CodingKeys: String, CodingKey {
        case id, name, prompt, schedule, triggers, enabled
        case pixieID = "pixie_id"
        case maxMinutes = "max_minutes"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case nextDueAt = "next_due_at"
        case lastRun = "last_run"
    }
}

/// A habit a pixie proposes in its chat; nothing runs until the user starts it.
public struct HabitSuggestion: Codable, Sendable, Hashable {
    public var name: String
    public var prompt: String
    public var schedule: HabitSchedule?
    public var triggers: [HabitTrigger]

    public init(
        name: String, prompt: String, schedule: HabitSchedule?, triggers: [HabitTrigger]
    ) {
        self.name = name
        self.prompt = prompt
        self.schedule = schedule
        self.triggers = triggers
    }

    enum CodingKeys: String, CodingKey {
        case name, prompt, schedule, triggers
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        name = try container.decode(String.self, forKey: .name)
        prompt = try container.decode(String.self, forKey: .prompt)
        schedule = try container.decodeIfPresent(HabitSchedule.self, forKey: .schedule)
        triggers = try container.decodeIfPresent([HabitTrigger].self, forKey: .triggers) ?? []
    }
}

/// How much a report matters; `report_push` names the least that reaches the phone.
public enum ReportSeverity: String, Codable, Sendable, CaseIterable, UnknownSafeEnum,
    Comparable
{
    case info, warn, action
    case unknown

    var rank: Int {
        switch self {
        case .unknown: 0
        case .info: 1
        case .warn: 2
        case .action: 3
        }
    }

    public static func < (lhs: ReportSeverity, rhs: ReportSeverity) -> Bool {
        lhs.rank < rhs.rank
    }
}

/// What a pixie told the user with its `report` tool.
public struct PixieReport: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var pixieID: String
    public var severity: ReportSeverity
    public var title: String
    public var body: String
    public var link: String?
    public var habitID: String?
    /// The habit's name when it was made, from the daemon.
    public var habitName: String?
    public var runID: String?
    public var createdAt: Date
    public var readAt: Date?

    public var isUnread: Bool { readAt == nil }

    enum CodingKeys: String, CodingKey {
        case id, severity, title, body, link
        case pixieID = "pixie_id"
        case habitID = "habit_id"
        case habitName = "habit_name"
        case runID = "run_id"
        case createdAt = "created_at"
        case readAt = "read_at"
    }
}
