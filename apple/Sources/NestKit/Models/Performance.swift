import Foundation

/// Settings > Performance (B115): `GET /api/perf`. The daemon owns every label, unit,
/// order and formatted text; the app only lays them out and scales the bars.
public struct PerfView: Codable, Sendable, Hashable {
    /// The run in progress, if any; one runs at a time.
    public var running: PerfRunning?
    public var lastRun: PerfLastRun?
    /// The four cards at the top.
    public var cards: [PerfMetric]
    public var sections: [PerfSection]
    /// "What changed", worst first.
    public var changes: [PerfChange]
    /// How many runs are kept.
    public var runs: Int

    public init(
        running: PerfRunning? = nil, lastRun: PerfLastRun? = nil, cards: [PerfMetric] = [],
        sections: [PerfSection] = [], changes: [PerfChange] = [], runs: Int = 0
    ) {
        self.running = running
        self.lastRun = lastRun
        self.cards = cards
        self.sections = sections
        self.changes = changes
        self.runs = runs
    }

    public func section(_ id: String) -> PerfSection? {
        sections.first { $0.id == id }
    }

    enum CodingKeys: String, CodingKey {
        case running, cards, sections, changes, runs
        case lastRun = "last_run"
    }
}

public struct PerfRunning: Codable, Sendable, Hashable {
    public var id: String
    public var sections: [String]
    public var startedAt: Date

    public init(id: String, sections: [String], startedAt: Date) {
        self.id = id
        self.sections = sections
        self.startedAt = startedAt
    }

    enum CodingKeys: String, CodingKey {
        case id, sections
        case startedAt = "started_at"
    }
}

public struct PerfLastRun: Codable, Sendable, Hashable {
    public var finishedAt: Date
    public var durationMs: Double

    public init(finishedAt: Date, durationMs: Double) {
        self.finishedAt = finishedAt
        self.durationMs = durationMs
    }

    enum CodingKeys: String, CodingKey {
        case finishedAt = "finished_at"
        case durationMs = "duration_ms"
    }
}

/// Who measures a section: the daemon, or the Mac app (`mac`, C14).
public enum PerfRunner: String, UnknownSafeEnum {
    case daemon, mac, unknown
}

public enum PerfUnit: String, UnknownSafeEnum {
    case tokens, ms, bytes, percent, count, unknown
}

/// Whether a change is good news; `same` is neutral grey.
public enum PerfTone: String, UnknownSafeEnum {
    case better, worse, same, unknown
}

public struct PerfSection: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var title: String
    /// Shown under Advanced.
    public var advanced: Bool
    public var runner: PerfRunner
    /// A run spends usage.
    public var live: Bool
    /// When its latest run finished; nil before the first.
    public var ranAt: Date?
    /// Why its latest run failed.
    public var error: String?
    public var note: String?
    public var metrics: [PerfMetric]
    public var series: PerfSeries?

    public init(
        id: String, title: String, advanced: Bool = false, runner: PerfRunner = .daemon,
        live: Bool = false, ranAt: Date? = nil, error: String? = nil, note: String? = nil,
        metrics: [PerfMetric] = [], series: PerfSeries? = nil
    ) {
        self.id = id
        self.title = title
        self.advanced = advanced
        self.runner = runner
        self.live = live
        self.ranAt = ranAt
        self.error = error
        self.note = note
        self.metrics = metrics
        self.series = series
    }

    enum CodingKeys: String, CodingKey {
        case id, title, advanced, runner, live, error, note, metrics, series
        case ranAt = "ran_at"
    }
}

public struct PerfMetric: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var label: String
    /// A quiet word beside the label, such as the chat's size.
    public var sub: String?
    public var value: Double?
    public var unit: PerfUnit
    /// The value as the daemon formats it, "-" when there is none.
    public var text: String
    public var previous: Double?
    public var previousText: String?
    public var change: PerfChangeMark?
    /// A breakdown, such as the context cost's parts.
    public var parts: [PerfPart]?
    /// The chat the metric measured, such as the load section's biggest chat, when the
    /// daemon names it.
    public var chatID: String?

    public init(
        id: String, label: String, sub: String? = nil, value: Double?, unit: PerfUnit,
        text: String, previous: Double? = nil, previousText: String? = nil,
        change: PerfChangeMark? = nil, parts: [PerfPart]? = nil, chatID: String? = nil
    ) {
        self.id = id
        self.label = label
        self.sub = sub
        self.value = value
        self.unit = unit
        self.text = text
        self.previous = previous
        self.previousText = previousText
        self.change = change
        self.parts = parts
        self.chatID = chatID
    }

    enum CodingKeys: String, CodingKey {
        case id, label, sub, value, unit, text, previous, change, parts
        case previousText = "previous_text"
        case chatID = "chat_id"
    }
}

/// "▼ 25%", in the tone's colour.
public struct PerfChangeMark: Codable, Sendable, Hashable {
    public var text: String
    /// "up", "down" or "same".
    public var direction: String
    public var tone: PerfTone

    public init(text: String, direction: String, tone: PerfTone) {
        self.text = text
        self.direction = direction
        self.tone = tone
    }
}

public struct PerfPart: Codable, Sendable, Hashable {
    public var label: String
    public var value: Double
    public var text: String

    public init(label: String, value: Double, text: String) {
        self.label = label
        self.value = value
        self.text = text
    }
}

/// A day series, such as turns per day over 14 days.
public struct PerfSeries: Codable, Sendable, Hashable {
    public var label: String
    public var points: [PerfPoint]

    public init(label: String, points: [PerfPoint]) {
        self.label = label
        self.points = points
    }
}

public struct PerfPoint: Codable, Sendable, Hashable {
    /// A plain date, `YYYY-MM-DD`.
    public var day: String
    public var value: Double

    public init(day: String, value: Double) {
        self.day = day
        self.value = value
    }
}

/// A line of "What changed".
public struct PerfChange: Codable, Sendable, Hashable {
    public var text: String
    public var tone: PerfTone

    public init(text: String, tone: PerfTone) {
        self.text = text
        self.tone = tone
    }
}

/// `POST /api/perf/runs`; no sections runs every daemon section.
struct PerfRunRequest: Encodable {
    let sections: [String]
}

/// `POST /api/perf/client`: a section a client measured itself, such as the Mac app's.
struct PerfClientRequest: Encodable {
    let section: String
    let metrics: [String: Double]
}
