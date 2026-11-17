import Foundation

/// The installer's steps, in the order it runs them (release/install.sh, `@step` lines).
public enum InstallStep: String, CaseIterable, Sendable {
    case download, service, engines, check, start

    public var title: String {
        switch self {
        case .download: "Downloading Nest"
        case .service: "Setting up the background service"
        case .engines: "Getting the newest engines"
        case .check: "Checking the engines"
        case .start: "Starting Nest"
        }
    }

    /// How long the step usually takes, for its estimated percent.
    var typical: TimeInterval {
        switch self {
        case .download: 15
        case .service: 45
        case .engines: 40
        case .check: 15
        case .start: 10
        }
    }
}

/// Where Set up Nest is: the step under way since when, and its measured percent where the
/// installer can measure one (downloads). The other steps count up from how long they usually
/// take and hold at 95% until the installer moves on.
public struct SetupProgress: Sendable, Equatable {
    public internal(set) var current: InstallStep
    public internal(set) var startedAt: Date
    public internal(set) var measured: Int?

    /// Where an estimate stops until the step really ends.
    static let estimateCap = 95

    public init(current: InstallStep = .download, startedAt: Date, measured: Int? = nil) {
        self.current = current
        self.startedAt = startedAt
        self.measured = measured
    }

    public func mark(of step: InstallStep) -> SetupMark {
        let order = InstallStep.allCases
        let here = order.firstIndex(of: current) ?? 0
        let there = order.firstIndex(of: step) ?? 0
        return there < here ? .ok : there == here ? .now : .todo
    }

    public func percent(of step: InstallStep, at now: Date) -> Int {
        switch mark(of: step) {
        case .ok: return 100
        case .todo, .skipped: return 0
        case .now:
            if let measured { return min(max(measured, 0), 100) }
            let elapsed = max(now.timeIntervalSince(startedAt), 0)
            return min(Int(elapsed / step.typical * 100), Self.estimateCap)
        }
    }

    /// One of the installer's lines for the app: `@step <name>` moves on, never back, and
    /// `@progress <percent>` measures the step under way. False for any other line.
    mutating func read(_ line: String, at now: Date) -> Bool {
        if let name = line.wholeMatch(of: /@step (\w+)/)?.output.1 {
            if let step = InstallStep(rawValue: String(name)), mark(of: step) == .todo {
                current = step
                startedAt = now
                measured = nil
            }
            return true
        }
        if let value = line.wholeMatch(of: /@progress (\d+)/)?.output.1 {
            measured = Int(value)
            return true
        }
        return false
    }
}
