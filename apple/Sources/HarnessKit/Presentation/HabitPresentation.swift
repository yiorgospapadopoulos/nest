import Foundation

// How the app shows a pixie's habits, their runs and its reports (B42).

extension HabitTrigger {
    /// The triggers in the order the editor lists them.
    public static var choices: [HabitTrigger] { [.stuck, .failed, .reviewReady, .ciFailed] }

    /// The editor's checkbox.
    public var label: String {
        switch self {
        case .stuck: "A chat is stuck"
        case .failed: "A chat fails"
        case .reviewReady: "A chat is ready for review"
        case .ciFailed: "A pull request's checks fail"
        case .unknown: ""
        }
    }

    /// What follows "When a chat".
    var phrase: String? {
        switch self {
        case .stuck: "is stuck"
        case .failed: "fails"
        case .reviewReady: "is ready for review"
        case .ciFailed: "fails CI"
        case .unknown: nil
        }
    }
}

extension HabitRunOutcome {
    public var label: String {
        switch self {
        case .queued: "Queued"
        case .running: "Running"
        case .reported: "Reported"
        case .quiet: "Quiet"
        case .failed: "Failed"
        case .stalled: "Stalled"
        case .timedOut: "Timed out"
        case .skipped: "Skipped"
        case .unknown: "Unknown"
        }
    }

    public var tone: StatusTone {
        switch self {
        case .queued, .running: .running
        case .reported: .review
        case .failed, .timedOut: .failed
        case .stalled: .waiting
        case .skipped: .interrupted
        case .quiet, .unknown: .done
        }
    }

    /// Waiting its turn or running now.
    public var isActive: Bool {
        self == .queued || self == .running
    }
}

extension PixieHabit {
    /// "Weekdays at 09:00 · When a chat is stuck".
    public var summary: String {
        HabitText.summary(schedule: schedule, triggers: triggers)
    }
}

extension HabitSuggestion {
    public var summary: String {
        HabitText.summary(schedule: schedule, triggers: triggers)
    }

    /// A habit of the same name exists, so the card shows "Started".
    public func isStarted(among habits: [PixieHabit]?) -> Bool {
        habits?.contains { $0.name == name } ?? false
    }
}

/// The words of the Habits page and its history.
public enum HabitText {
    public static let emptyList =
        "No habits yet. A habit runs on a schedule or when chats need attention, and reports what it finds."
    public static let emptyHistory = "No runs yet."

    /// "Every hour at :15", "Every day at 07:30", "Weekdays at 09:00", "Mondays at 08:00".
    public static func schedule(_ schedule: HabitSchedule) -> String {
        let time = schedule.time ?? "00:00"
        switch schedule.kind {
        case .hourly: return "Every hour at :" + String(format: "%02d", schedule.minute ?? 0)
        case .daily: return "Every day at \(time)"
        case .weekdays: return "Weekdays at \(time)"
        case .weekly:
            guard let day = schedule.weekday, HabitDraft.weekdayNames.indices.contains(day) else {
                return "Weekly at \(time)"
            }
            return "\(HabitDraft.weekdayNames[day])s at \(time)"
        case .unknown: return "On a schedule"
        }
    }

    /// "When a chat is stuck, fails or fails CI"; nil without known triggers.
    public static func triggers(_ triggers: [HabitTrigger]) -> String? {
        let phrases = triggers.compactMap(\.phrase)
        guard let last = phrases.last else { return nil }
        let rest = phrases.dropLast()
        return "When a chat "
            + (rest.isEmpty ? last : rest.joined(separator: ", ") + " or " + last)
    }

    static func summary(schedule: HabitSchedule?, triggers: [HabitTrigger]) -> String {
        [schedule.map(Self.schedule), Self.triggers(triggers)].compactMap { $0 }
            .joined(separator: " · ")
    }

    /// The list's last outcome: "Reported 09:02", "Running since 09:00", "Skipped 09:00
    /// (late)", "Queued" or "Not run yet".
    public static func lastRun(_ run: HabitRun?, now: Date, calendar: Calendar = .current)
        -> String
    {
        guard let run else { return "Not run yet" }
        func time(_ date: Date) -> String {
            PixieActivityText.time(date, now: now, calendar: calendar)
        }
        switch run.outcome {
        case .queued: return run.outcome.label
        case .running: return "Running since " + (run.startedAt.map(time) ?? "now")
        default:
            let when = (run.endedAt ?? run.startedAt ?? run.dueAt).map { " " + time($0) } ?? ""
            let why = run.reason.map { " (\($0))" } ?? ""
            return run.outcome.label + when + why
        }
    }

    /// "Next 09:00", "Paused", or "Runs on events" for a habit with no time due.
    public static func nextRun(_ habit: PixieHabit, now: Date, calendar: Calendar = .current)
        -> String
    {
        guard habit.enabled else { return "Paused" }
        guard let due = habit.nextDueAt else { return "Runs on events" }
        return "Next " + PixieActivityText.time(due, now: now, calendar: calendar)
    }

    /// A history row's time: when it started, else "Due 09:00" for one that never did.
    public static func started(_ run: HabitRun, now: Date, calendar: Calendar = .current)
        -> String
    {
        if let start = run.startedAt {
            return PixieActivityText.time(start, now: now, calendar: calendar)
        }
        return run.dueAt.map { "Due " + PixieActivityText.time($0, now: now, calendar: calendar) }
            ?? ""
    }

    /// How long it ran, or runs so far; nil for one that never started.
    public static func duration(_ run: HabitRun, now: Date) -> String? {
        guard let start = run.startedAt, let end = run.endedAt ?? (run.outcome.isActive ? now : nil)
        else { return nil }
        return Elapsed.duration(from: start, to: end)
    }
}

/// The New habit and Edit form, as values: what the user chose and what it sends.
public struct HabitDraft: Sendable, Hashable {
    public enum Repeat: String, Sendable, CaseIterable {
        case never, hourly, daily, weekdays, weekly

        public var label: String {
            switch self {
            case .never: "No schedule"
            case .hourly: "Every hour"
            case .daily: "Every day"
            case .weekdays: "Weekdays"
            case .weekly: "Weekly"
            }
        }
    }

    public static let maxMinutesRange = 1...120
    /// Monday first, as the daemon numbers them.
    public static let weekdayNames = [
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    ]

    public var name = ""
    public var prompt = ""
    public var repeats = Repeat.daily
    /// The minute of an hourly habit.
    public var hourlyMinute = 0
    public var hour = 9
    public var minute = 0
    public var weekday = 0
    public var triggers: Set<HabitTrigger> = []
    public var maxMinutes = 20

    public init() {}

    public init(habit: PixieHabit) {
        name = habit.name
        prompt = habit.prompt
        triggers = Set(habit.triggers)
        maxMinutes = habit.maxMinutes
        use(habit.schedule)
    }

    public init(suggestion: HabitSuggestion) {
        name = suggestion.name
        prompt = suggestion.prompt
        triggers = Set(suggestion.triggers)
        use(suggestion.schedule)
    }

    private mutating func use(_ schedule: HabitSchedule?) {
        guard let schedule else {
            repeats = .never
            return
        }
        switch schedule.kind {
        case .hourly:
            repeats = .hourly
            hourlyMinute = schedule.minute ?? 0
        case .daily: repeats = .daily
        case .weekdays: repeats = .weekdays
        case .weekly:
            repeats = .weekly
            weekday = schedule.weekday ?? 0
        case .unknown: break
        }
        let parts = (schedule.time ?? "").split(separator: ":").compactMap { Int($0) }
        if parts.count == 2, (0..<24).contains(parts[0]), (0..<60).contains(parts[1]) {
            hour = parts[0]
            minute = parts[1]
        }
    }

    /// "HH:MM".
    public var time: String {
        String(format: "%02d:%02d", hour, minute)
    }

    public var schedule: HabitSchedule? {
        switch repeats {
        case .never: nil
        case .hourly: .hourly(minute: hourlyMinute)
        case .daily: .daily(time)
        case .weekdays: .weekdays(time)
        case .weekly: .weekly(weekday: weekday, time: time)
        }
    }

    /// Why it cannot be saved yet, as the daemon would refuse it.
    public var problem: String? {
        let name = trimmedName
        let prompt = trimmedPrompt
        if name.isEmpty { return "Name the habit" }
        if name.count > 60 { return "A name has at most 60 characters" }
        if prompt.isEmpty { return "Say what it should check" }
        if prompt.count > 4000 { return "The instructions have at most 4000 characters" }
        if schedule == nil && triggers.isEmpty {
            return "Choose a schedule or at least one trigger"
        }
        return nil
    }

    public var create: CreateHabitRequest {
        CreateHabitRequest(
            name: trimmedName, prompt: trimmedPrompt, schedule: schedule,
            triggers: orderedTriggers, maxMinutes: maxMinutes)
    }

    /// Only what changed from the habit.
    public func update(from habit: PixieHabit) -> UpdateHabitRequest {
        var request = UpdateHabitRequest()
        if trimmedName != habit.name { request.name = trimmedName }
        if trimmedPrompt != habit.prompt { request.prompt = trimmedPrompt }
        if schedule != habit.schedule {
            request.schedule = schedule
            request.clearsSchedule = schedule == nil
        }
        if orderedTriggers != habit.triggers { request.triggers = orderedTriggers }
        if maxMinutes != habit.maxMinutes { request.maxMinutes = maxMinutes }
        return request
    }

    /// The time as a date on `base`'s day, for a time picker.
    public func date(on base: Date, calendar: Calendar = .current) -> Date {
        // Hours and minutes in range always give a date; a wall time skipped by daylight
        // saving moves to the next one.
        calendar.date(bySettingHour: hour, minute: minute, second: 0, of: base)!
    }

    public mutating func setTime(_ date: Date, calendar: Calendar = .current) {
        hour = calendar.component(.hour, from: date)
        minute = calendar.component(.minute, from: date)
    }

    private var trimmedName: String { name.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var trimmedPrompt: String { prompt.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var orderedTriggers: [HabitTrigger] { HabitTrigger.choices.filter(triggers.contains) }
}

extension ReportSeverity {
    public var label: String {
        switch self {
        case .info: "Info"
        case .warn: "Warning"
        case .action: "Needs action"
        case .unknown: ""
        }
    }

    /// The severity mark: info grey, warn amber, action red.
    public var tone: StatusTone {
        switch self {
        case .warn: .waiting
        case .action: .failed
        case .info, .unknown: .done
        }
    }

    public static let pushTitle = "Phone alerts"
    /// The Phone alerts choices, from the fewest alerts.
    public static var pushChoices: [ReportSeverity] { [.action, .warn, .info] }

    public var pushLabel: String {
        switch self {
        case .action: "Needs action"
        case .warn: "Warnings and up"
        case .info: "Everything"
        case .unknown: ""
        }
    }
}

/// The words around a report.
public enum ReportText {
    public static let missing = "A report that is no longer here"
    /// The inbox section of unread warnings and actions.
    public static let inboxTitle = "Reports"

    /// "From habit Morning check" for a habit's report, by its current name, else the one
    /// the daemon sent; nil for one made in the chat.
    public static func from(_ report: PixieReport, habits: [PixieHabit]?) -> String? {
        guard let id = report.habitID else { return nil }
        let name = habits?.first { $0.id == id }?.name ?? report.habitName
        return name.map { "From habit \($0)" } ?? "From a habit"
    }
}

/// The row for the message that starts a pixie's turn after a habit reported.
public enum HabitReportNote {
    public static let title = "Habit report"
    static let prefix = "Report from habit "

    /// The message's first line, "Morning check (action): CI is red", without the words
    /// the row's title says; the report card above shows the details.
    public static func text(_ message: String) -> String {
        let line = String(message.prefix { $0 != "\n" })
        return line.hasPrefix(prefix) ? String(line.dropFirst(prefix.count)) : line
    }
}

public enum PixieCards {
    /// The choices cards with a user message after them: their buttons are spent.
    public static func answered(_ items: [TranscriptItem]) -> Set<String> {
        var later = false
        var answered: Set<String> = []
        for item in items.reversed() {
            switch item.content {
            case .user: later = true
            case .pixieCard(let card) where card.kind == .choices && later:
                answered.insert(item.id)
            default: break
            }
        }
        return answered
    }
}
