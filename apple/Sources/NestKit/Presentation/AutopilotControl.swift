import Foundation

/// The words and options of Autopilot (B120).
public enum AutopilotText {
    public static let title = "Autopilot"
    public static let decided = "Decided while you were away"

    public static let stopAfter: [(AutopilotStopAfter, String)] = [
        (.done, "Done only"), (.time, "Time"),
    ]

    /// In minutes.
    public static let times: [(Int, String)] = [1, 2, 4, 8].map { ($0 * 60, "\($0) h") }

    public static let weeklyCaps: [(Int?, String)] = {
        let caps = [50, 60, 70, 80, 90]
        return [(nil, "Off")] + caps.map { cap in (cap, "\(cap)%") }
    }()

    public static func ended(_ end: AutopilotEnd) -> String {
        switch end {
        case .done: "Finished"
        case .time: "Time ran out"
        case .weeklyCap: "Weekly cap reached"
        case .stuck: "Got stuck"
        case .errors: "Kept failing"
        case .stopped: "Stopped"
        case .off: "Turned off"
        case .unknown: "Ended"
        }
    }

    /// "Step 3 of 5: Writing the first tests"; nil with no step left in the task list.
    public static func step(_ tasks: [TrackedTask]) -> String? {
        let shown = tasks.filter { $0.status != .deleted }
        guard
            let index = shown.firstIndex(where: { $0.status == .inProgress })
                ?? shown.firstIndex(where: { $0.status == .pending })
        else { return nil }
        let task = shown[index]
        return "Step \(index + 1) of \(shown.count): \(task.activeForm ?? task.subject)"
    }

    /// "12m 4s running", or "1h 12m left · 3 decisions" on a run with a time budget.
    public static func line(_ run: AutopilotRun, now: Date) -> String {
        let time =
            if let until = run.until {
                "\(Elapsed.duration(from: now, to: until)) left"
            } else {
                "\(Elapsed.duration(from: run.startedAt, to: now)) running"
            }
        switch run.decisions.count {
        case 0: return time
        case 1: return "\(time) · 1 decision"
        case let count: return "\(time) · \(count) decisions"
        }
    }
}

public enum AutopilotStopAfter: Sendable, Hashable {
    case done, time
}

/// What the user chose in a composer. It is all a new chat has; a chat that exists keeps it
/// for going on later, and a run's own budget replaces it while it runs.
public struct AutopilotChoice: Sendable, Hashable {
    public var on: Bool
    public var budget: AutopilotBudget

    public init(on: Bool = false, budget: AutopilotBudget = AutopilotBudget()) {
        self.on = on
        self.budget = budget
    }

    /// What a new chat's request says.
    public var request: SetAutopilotRequest? {
        on ? SetAutopilotRequest(on: true, budget: budget) : nil
    }

    /// Where a new chat works: the place the user chose, else a new worktree on Autopilot,
    /// else the default.
    public func place(chosen: NewChatChoice?, fallback: NewChatChoice) -> NewChatChoice {
        chosen ?? (on ? .newWorktree(from: nil) : fallback)
    }
}

/// One change made in the popover: what the composer keeps, and what goes to the daemon at
/// once for a chat that exists.
public struct AutopilotChange: Sendable, Hashable {
    public let choice: AutopilotChoice
    public let request: SetAutopilotRequest?
}

/// Autopilot for an open chat, or for the new chat being written.
public struct AutopilotControl: Sendable, Hashable {
    public let choice: AutopilotChoice
    /// False for a new chat, whose choice goes with its request.
    public let chatExists: Bool
    public let run: AutopilotRun?

    public init(choice: AutopilotChoice, chatExists: Bool, run: AutopilotRun?) {
        self.choice = choice
        self.chatExists = chatExists
        self.run = run
    }

    public var on: Bool { run != nil || (!chatExists && choice.on) }

    public var budget: AutopilotBudget { run.map(AutopilotBudget.init(run:)) ?? choice.budget }

    public var stopAfter: AutopilotStopAfter { budget.stopAfterMinutes == nil ? .done : .time }

    public func turning(on: Bool) -> AutopilotChange {
        change(on: on, budget: budget)
    }

    public func stopping(after: AutopilotStopAfter) -> AutopilotChange {
        var next = budget
        next.stopAfterMinutes =
            switch after {
            case .done: nil
            case .time: next.stopAfterMinutes ?? AutopilotText.times[0].0
            }
        return change(on: on, budget: next)
    }

    public func stopping(afterMinutes minutes: Int) -> AutopilotChange {
        var next = budget
        next.stopAfterMinutes = minutes
        return change(on: on, budget: next)
    }

    public func capping(at cap: Int?) -> AutopilotChange {
        var next = budget
        next.weeklyCap = cap
        return change(on: on, budget: next)
    }

    private func change(on: Bool, budget: AutopilotBudget) -> AutopilotChange {
        let choice = AutopilotChoice(on: on, budget: budget)
        guard chatExists else { return AutopilotChange(choice: choice, request: nil) }
        if on {
            return AutopilotChange(
                choice: choice, request: SetAutopilotRequest(on: true, budget: budget))
        }
        return AutopilotChange(
            choice: choice, request: run == nil ? nil : SetAutopilotRequest(on: false))
    }
}
