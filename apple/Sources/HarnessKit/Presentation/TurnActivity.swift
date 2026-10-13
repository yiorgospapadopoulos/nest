import Foundation

/// The lines that say how long the agent works and thinks.
public enum TurnText {
    /// The live line under a running turn: "Working... 12s", or "Thinking... 4s" while the
    /// latest content is thinking; without a known start, no time.
    public static func working(since start: Date?, at now: Date, thinking: Bool) -> String {
        let verb = thinking ? "Thinking..." : "Working..."
        guard let start else { return verb }
        return "\(verb) \(Elapsed.duration(from: start, to: now))"
    }

    /// "Worked for 1m 12s", or "Stopped after 40s" for an interrupted or failed turn.
    public static func ended(_ end: TurnEnd) -> String {
        let length = Elapsed.duration(seconds: Double(end.durationMS) / 1000)
        return end.stopped ? "Stopped after \(length)" : "Worked for \(length)"
    }

    /// A thinking block's title: "Thought for 8s", or "Thought" when its length is unknown.
    public static func thought(durationMS: Int?) -> String {
        durationMS.map { "Thought for \(Elapsed.duration(seconds: Double($0) / 1000))" }
            ?? "Thought"
    }
}

/// One line for a run of tool calls: "Running 2 commands, reading 1 file" while any runs,
/// then "Ran 3 commands, read 2 files, edited 1 file".
public enum ToolActivity {
    private enum Part: Hashable {
        case commands, reads, edits, searches, fetches, agents
        case other(String)

        init(_ tool: String) {
            switch ToolSummary.kind(of: tool) {
            case .terminal: self = .commands
            case .read: self = .reads
            case .edit: self = .edits
            case .search: self = .searches
            case .web: self = .fetches
            case .agent: self = .agents
            case .other:
                // An MCP tool, "mcp__server__tool", goes by its own name.
                let name = tool.range(of: "__", options: .backwards).map {
                    String(tool[$0.upperBound...])
                }
                self = .other(name ?? tool)
            }
        }

        /// The verb and the counted noun, in the present or past tense.
        func phrase(_ count: Int, done: Int, running: Bool) -> String {
            func counted(_ noun: String) -> String { "\(count) \(noun)\(count == 1 ? "" : "s")" }
            switch self {
            case .commands: return "\(running ? "running" : "ran") \(counted("command"))"
            case .reads: return "\(running ? "reading" : "read") \(counted("file"))"
            case .edits: return "\(running ? "editing" : "edited") \(counted("file"))"
            case .searches:
                return "\(running ? "searching" : "searched") for \(counted("pattern"))"
            case .fetches: return "\(running ? "fetching" : "fetched") \(counted("page"))"
            case .agents:
                let agents = "\(running ? "running" : "ran") \(counted("agent"))"
                return running && done > 0 ? "\(agents), \(done) done" : agents
            case .other(let name):
                let times = count > 1 ? " \(count) times" : ""
                return "\(running ? "using" : "used") \(name)\(times)"
            }
        }
    }

    /// `background` holds the calls whose background task still runs: they are not done.
    public static func summary(
        _ calls: [ToolCall], running: Bool, background: Set<String> = []
    ) -> String {
        var order: [Part] = []
        var counts: [Part: (count: Int, done: Int)] = [:]
        for call in calls {
            let part = Part(call.name)
            if counts[part] == nil {
                order.append(part)
            }
            counts[part, default: (0, 0)].count += 1
            counts[part]!.done += call.result == nil || background.contains(call.id) ? 0 : 1
        }
        var phrases = order.map { part in
            part.phrase(counts[part]!.count, done: counts[part]!.done, running: running)
        }
        let failed = calls.count { $0.isError }
        if failed > 0 {
            phrases.append("\(failed) failed")
        }
        let line = phrases.joined(separator: ", ")
        return line.prefix(1).uppercased() + line.dropFirst()
    }
}

/// Consecutive tool calls of a turn, with any thinking between them, shown as one row.
public struct ToolGroup: Sendable, Hashable, Identifiable {
    public let id: String
    /// The tool calls and the thinking between them, in order.
    public let items: [TranscriptItem]
    /// A call still runs: it has no result and its turn is open, or its background task
    /// runs.
    public let isRunning: Bool
    /// The calls whose background task still runs.
    public let background: Set<String>

    public var calls: [ToolCall] {
        items.compactMap { if case .tool(let call) = $0.content { call } else { nil } }
    }

    public var summary: String {
        ToolActivity.summary(calls, running: isRunning, background: background)
    }
}

/// A transcript row: an item, or a group of tool calls.
public enum TranscriptEntry: Sendable, Hashable, Identifiable {
    case item(TranscriptItem)
    case tools(ToolGroup)

    public var id: String {
        switch self {
        case .item(let item): item.id
        case .tools(let group): group.id
        }
    }
}

public enum TranscriptGrouping {
    /// The rows for these items: two or more tool calls with nothing but thinking between
    /// them become a group; anything else, assistant text above all, ends it. `live` says
    /// the session's turn is running, so calls after the last turn end can still run.
    /// `background` holds the tool use ids of background tasks still running: a call that
    /// started one runs until it ends (D045). Other calls without a result that can no
    /// longer run are marked stopped (D054).
    public static func entries(
        _ items: [TranscriptItem], live: Bool, background: Set<String> = []
    ) -> [TranscriptEntry] {
        // A turn's end line, or a user message starting the next turn.
        let lastEnd = items.lastIndex {
            switch $0.content {
            case .turnEnd, .user: true
            default: false
            }
        }
        var entries: [TranscriptEntry] = []
        var run: [TranscriptItem] = []
        var runIsOpen = false

        func flush() {
            let open = runIsOpen && live
            if !open {
                run = run.map { $0.stoppingCall(unless: background) }
            }
            let tail = run.reversed().prefix { !$0.isTool }.count
            let grouped = run.dropLast(tail)
            if grouped.count(where: \.isTool) > 1 {
                let working = Set(grouped.map(\.id)).intersection(background)
                let running =
                    !working.isEmpty
                    || open && grouped.contains { $0.isTool && $0.toolResult == nil }
                entries.append(
                    .tools(
                        ToolGroup(
                            id: "tools-\(grouped[grouped.startIndex].id)", items: Array(grouped),
                            isRunning: running, background: working)))
            } else {
                entries += grouped.map(TranscriptEntry.item)
            }
            entries += run.suffix(tail).map(TranscriptEntry.item)
            run = []
        }

        for (index, item) in items.enumerated() {
            switch item.content {
            case .tool:
                run.append(item)
                runIsOpen = index > (lastEnd ?? -1)
            case .thinking where !run.isEmpty:
                run.append(item)
            default:
                flush()
                entries.append(.item(item))
            }
        }
        flush()
        return entries
    }

    /// The group an item was folded into, if any.
    public static func group(containing itemID: String, in entries: [TranscriptEntry]) -> String? {
        for case .tools(let group) in entries where group.items.contains(where: { $0.id == itemID })
        {
            return group.id
        }
        return nil
    }
}

extension TranscriptItem {
    fileprivate var isTool: Bool {
        if case .tool = content { true } else { false }
    }

    /// A tool call's result: nil while it runs, and for other items.
    fileprivate var toolResult: String? {
        if case .tool(let call) = content { call.result } else { nil }
    }

    /// A call without a result, marked stopped unless its background task still runs.
    fileprivate func stoppingCall(unless background: Set<String>) -> TranscriptItem {
        guard case .tool(var call) = content, call.result == nil, !background.contains(id)
        else { return self }
        call.stopped = true
        var item = self
        item.content = .tool(call)
        return item
    }
}
