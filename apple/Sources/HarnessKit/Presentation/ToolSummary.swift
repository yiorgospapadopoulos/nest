import Foundation

/// How a tool call reads in one line: an icon kind, its telling argument and a short
/// note about the result.
public enum ToolSummary {
    public enum Kind: Sendable, Hashable {
        case read, edit, terminal, search, agent, web, other
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
        default: .other
        }
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
        default:
            let keys = ["command", "file_path", "notebook_path", "path", "pattern", "url", "query"]
            return keys.lazy.compactMap(text).first ?? ""
        }
    }

    public static func result(of call: ToolCall) -> String {
        guard let result = call.result else { return "running" }
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
