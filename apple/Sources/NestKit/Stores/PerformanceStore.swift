import Foundation
import Observation

/// What the Performance page shows as a whole.
public enum PerfPageState: Sendable, Hashable {
    case loading
    /// Nothing has run yet.
    case neverRun
    case running
    case finished
}

/// One metric's bars, as shares of the tallest of its unit in its section: the previous
/// run's and this one's, nil where there is no value.
public struct PerfBar: Sendable, Hashable {
    public let previous: Double?
    public let current: Double?

    public init(previous: Double?, current: Double?) {
        self.previous = previous
        self.current = current
    }
}

/// Settings > Performance (B115): the daemon's latest results, its runs, and the Mac app's
/// own section, which this app measures itself (C14).
@MainActor @Observable
public final class PerformanceStore {
    /// Measures the Mac app and answers its metrics by id; set by the app.
    public typealias MacMeasurement = @MainActor () async throws -> [String: Double]

    /// The section the Mac app measures.
    public static let macSection = "mac"
    /// The load section, whose biggest chat the Mac measurement opens.
    static let loadSection = "load"
    static let biggestChatMetric = "biggest_chat"
    /// How many times a Mac result waits for a daemon run to finish before giving up.
    static let recordWaits = 300

    /// Nil until loaded.
    public private(set) var view: PerfView?
    /// Why the last load, run or clear failed; cleared by the next one.
    public private(set) var failure: String?
    /// The Mac measurement is under way.
    public private(set) var measuringMac = false

    @ObservationIgnored public var measureMac: MacMeasurement?
    @ObservationIgnored private var reload: Task<Void, Never>?

    let api: any NestAPI
    let pause: @Sendable (Duration) async throws -> Void

    public init(
        api: any NestAPI,
        pause: @escaping @Sendable (Duration) async throws -> Void = {
            try await Task.sleep(for: $0)
        }
    ) {
        self.api = api
        self.pause = pause
    }

    public func load() async {
        await act("Could not read the results") { try await self.api.perf() }
    }

    /// Runs every daemon section, then, on the Mac, measures the Mac app too.
    public func runAll() async {
        let started = await act("Could not start the run") {
            try await self.api.runPerf(sections: [])
        }
        if started, measureMac != nil {
            await runMac()
        }
    }

    /// Runs one section: the Mac app's here, any other on the daemon.
    public func run(_ section: PerfSection) async {
        if section.runner == .mac {
            await runMac()
        } else {
            await act("Could not start the run") {
                try await self.api.runPerf(sections: [section.id])
            }
        }
    }

    public func clearOldRuns() async {
        await act("Could not clear old runs") { try await self.api.clearPerf() }
    }

    /// Measures the Mac app and records the result. While a daemon run holds the results,
    /// the record waits for it to finish.
    public func runMac() async {
        guard let measure = measureMac, !measuringMac else { return }
        measuringMac = true
        defer { measuringMac = false }
        failure = nil
        do {
            let metrics = try await measure()
            view = try await record(metrics)
        } catch {
            failure = "Could not measure the Mac app: \(Self.describe(error))"
        }
    }

    private func record(_ metrics: [String: Double]) async throws -> PerfView {
        var waits = 0
        while true {
            do {
                return try await api.recordPerf(section: Self.macSection, metrics: metrics)
            } catch let error as APIError where error.isConflict && waits < Self.recordWaits {
                waits += 1
                try await pause(.seconds(2))
                if let latest = try? await api.perf() {
                    view = latest
                }
            }
        }
    }

    /// Answers whether the call succeeded; a failure says what failed.
    @discardableResult
    private func act(_ doing: String, _ call: @escaping () async throws -> PerfView) async
        -> Bool
    {
        do {
            view = try await call()
            failure = nil
            return true
        } catch {
            failure = "\(doing): \(Self.describe(error))"
            return false
        }
    }

    static func describe(_ error: any Error) -> String {
        (error as? APIError)?.message ?? error.localizedDescription
    }

    // MARK: State

    public var state: PerfPageState {
        guard let view else { return .loading }
        if isRunning {
            return .running
        }
        if view.lastRun == nil && view.sections.allSatisfy({ $0.ranAt == nil }) {
            return .neverRun
        }
        return .finished
    }

    /// A daemon run or the Mac measurement is under way.
    public var isRunning: Bool { view?.running != nil || measuringMac }

    public func isRunning(_ section: PerfSection) -> Bool {
        if section.runner == .mac {
            return measuringMac
        }
        return view?.running?.sections.contains(section.id) == true
    }

    /// Whether the section's Run button works: a daemon section while no daemon run runs,
    /// the Mac app's on the Mac while it is not being measured. Other devices' sections
    /// have none.
    public func canRun(_ section: PerfSection) -> Bool {
        switch section.runner {
        case .mac: measureMac != nil && !measuringMac
        case .daemon: view?.running == nil
        case .unknown: false
        }
    }

    public var mainSections: [PerfSection] { (view?.sections ?? []).filter { !$0.advanced } }
    public var advancedSections: [PerfSection] { (view?.sections ?? []).filter(\.advanced) }

    // MARK: Events

    /// A run started or finished somewhere: the open page reads the results again.
    public func apply(_ event: Event) {
        guard event.type == EventType.perfRun, view != nil else { return }
        reload?.cancel()
        reload = Task { [weak self] in
            guard let self, let latest = try? await self.api.perf() else { return }
            self.view = latest
        }
    }

    // MARK: Mac measurement

    /// The chat the Mac measurement opens: the load section's biggest chat when the daemon
    /// names it, else the listed chat that has used the most context, which grows with the
    /// transcript.
    public static func biggestChat(in view: PerfView?, sessions: [Session]) -> String? {
        let load = view?.section(loadSection)
        if let named = load?.metrics.first(where: { $0.id == biggestChatMetric })?.chatID {
            return named
        }
        return sessions.max { lhs, rhs in
            (lhs.context?.used ?? 0, lhs.updatedAt) < (rhs.context?.used ?? 0, rhs.updatedAt)
        }?.id
    }
}

/// The bars of a section: each metric's previous and current value against the largest
/// value or previous among its section's metrics of the same unit.
public enum PerfBars {
    public static func scale(_ metrics: [PerfMetric]) -> [String: PerfBar] {
        // A share is drawn against the whole: 13% of the context window is a short bar.
        var peaks: [PerfUnit: Double] = [.percent: 100]
        for metric in metrics {
            let top = max(metric.value ?? 0, metric.previous ?? 0)
            peaks[metric.unit] = max(peaks[metric.unit] ?? 0, top)
        }
        var bars: [String: PerfBar] = [:]
        for metric in metrics {
            let peak = peaks[metric.unit] ?? 0
            func share(_ value: Double?) -> Double? {
                guard let value else { return nil }
                return peak > 0 ? min(max(value / peak, 0), 1) : 0
            }
            bars[metric.id] = PerfBar(
                previous: share(metric.previous), current: share(metric.value))
        }
        return bars
    }

    /// A day series' bars as shares of its largest day.
    public static func days(_ series: PerfSeries) -> [Double] {
        let peak = series.points.map(\.value).max() ?? 0
        return series.points.map { peak > 0 ? min(max($0.value / peak, 0), 1) : 0 }
    }
}

/// The page's own words; the daemon formats everything else.
public enum PerfText {
    /// "Last run today 10:58 · 1 min 42 s", "Running since 10:58", "Not run yet".
    public static func header(
        _ view: PerfView?, measuringMac: Bool, now: Date, calendar: Calendar = .current
    ) -> String {
        if let running = view?.running {
            return "Running since \(time(running.startedAt, now: now, calendar: calendar))"
        }
        if measuringMac {
            return "Measuring the Mac app"
        }
        guard let last = view?.lastRun else { return "Not run yet" }
        let when = time(last.finishedAt, now: now, calendar: calendar)
        return "Last run \(when) · \(duration(ms: last.durationMs))"
    }

    /// "today 10:58", "yesterday 18:02", "12 Oct 09:30".
    static func time(_ date: Date, now: Date, calendar: Calendar) -> String {
        let parts = calendar.dateComponents([.month, .day, .hour, .minute], from: date)
        let clock = String(format: "%02d:%02d", parts.hour!, parts.minute!)
        if calendar.isDate(date, inSameDayAs: now) {
            return "today \(clock)"
        }
        if let yesterday = calendar.date(byAdding: .day, value: -1, to: now),
            calendar.isDate(date, inSameDayAs: yesterday)
        {
            return "yesterday \(clock)"
        }
        return "\(parts.day!) \(UsageText.shortMonths[parts.month! - 1]) \(clock)"
    }

    /// "1 min 42 s", "42 s", "0.8 s", "1 h 3 min".
    static func duration(ms: Double) -> String {
        if ms < 10_000 {
            return String(format: "%.1f s", ms / 1000)
        }
        let total = Int((ms / 1000).rounded())
        let (hours, minutes, seconds) = (total / 3600, total % 3600 / 60, total % 60)
        if hours > 0 {
            return minutes > 0 ? "\(hours) h \(minutes) min" : "\(hours) h"
        }
        if minutes > 0 {
            return seconds > 0 ? "\(minutes) min \(seconds) s" : "\(minutes) min"
        }
        return "\(seconds) s"
    }
}
