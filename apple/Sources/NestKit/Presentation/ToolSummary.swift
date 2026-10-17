import Foundation

/// How a tool call reads in one line: an icon kind, its telling argument and a short
/// note about the result.
public enum ToolSummary {
    public enum Kind: Sendable, Hashable {
        case read, edit, terminal, search, agent, web, artifact, other
    }

    static let resultLimit = 40

    public static func kind(of tool: String) -> Kind {
        switch tool {
        case "Read": .read
        case "Edit", "MultiEdit", "Write", "NotebookEdit": .edit
        case "Bash": .terminal
        case "Grep", "Glob": .search
        case "Task", "Agent": .agent
        case "WebFetch", "WebSearch": .web
        case ArtifactTools.create, ArtifactTools.update: .artifact
        default: .other
        }
    }

    /// The tool's name as a row shows it: Nest's artifact tools in words.
    public static func name(of tool: String) -> String {
        kind(of: tool) == .artifact ? ArtifactText.toolTitle(tool) : tool
    }

    public static func argument(of call: ToolCall) -> String {
        argument(tool: call.name, input: call.input)
    }

    /// The argument of a tool call that is only described, such as a permission prompt's.
    public static func argument(tool: String, input: JSONValue) -> String {
        func text(_ key: String) -> String? { input[key]?.stringValue }
        switch kind(of: tool) {
        case .search where text("pattern") != nil:
            return (["\"\(text("pattern")!)\""] + [text("path")].compactMap { $0 })
                .joined(separator: " ")
        case .agent:
            return [text("subagent_type"), text("description")].compactMap { $0 }
                .joined(separator: ": ")
        // Never the content, which can be a whole document.
        case .artifact:
            return text("title") ?? ""
        default:
            let keys = ["command", "file_path", "notebook_path", "path", "pattern", "url", "query"]
            return keys.lazy.compactMap(text).first ?? ""
        }
    }

    /// What a call answered, as shown: an agent's report without Claude Code's hand-back
    /// frame (`SubagentReport`); nil while it runs.
    public static func output(of call: ToolCall) -> String? {
        guard let result = call.result else { return nil }
        return kind(of: call.name) == .agent ? SubagentReport.clean(result) : result
    }

    public static func result(of call: ToolCall) -> String {
        guard let result = output(of: call) else { return call.stopped ? "stopped" : "running" }
        if call.isError {
            return "failed"
        }
        if kind(of: call.name) == .edit {
            return "done"
        }
        if kind(of: call.name) == .read {
            let lines = result.components(separatedBy: "\n").count
            return lines == 1 ? "1 line" : "\(lines) lines"
        }
        let first = result.components(separatedBy: "\n")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .first { !$0.isEmpty }
        guard let first else { return "done" }
        return first.count > resultLimit ? first.prefix(resultLimit - 1) + "…" : first
    }
}

/// A subagent's answer as Claude Code hands it back: a frame saying the report is model
/// output, the report indented two spaces, then the agent's id and its usage.
public enum SubagentReport {
    static let frame = "[Subagent hand-back]"
    static let follows = "The report follows:\n"
    static let agentLine = "agentId: "

    /// The report alone: what follows the frame's "The report follows:" line, without
    /// the trailing `<usage>` block and the `agentId: ` line (and anything after it), each
    /// line's two-space indent removed, trimmed. The text as it was when nothing is left.
    public static func clean(_ text: String) -> String {
        var body = Substring(text)
        if body.hasPrefix(frame), let start = body.range(of: follows) {
            body = body[start.upperBound...]
        }
        if let usage = body.range(of: "<usage>", options: .backwards),
            body[usage.lowerBound...].trimmingCharacters(in: .whitespacesAndNewlines)
                .hasSuffix("</usage>")
        {
            body = body[..<usage.lowerBound]
        }
        let lines = body.split(separator: "\n", omittingEmptySubsequences: false)
        let report = lines.prefix { !$0.hasPrefix(agentLine) }
            .map { $0.hasPrefix("  ") ? $0.dropFirst(2) : $0 }
            .joined(separator: "\n")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return report.isEmpty ? text : report
    }
}
