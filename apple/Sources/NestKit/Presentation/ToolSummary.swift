import Foundation

/// How a tool call reads in one line: an icon kind, its telling argument and a short
/// note about the result.
public enum ToolSummary {
    public enum Kind: Sendable, Hashable {
        case read, edit, terminal, search, agent, web, artifact, other
    }

    static let resultLimit = 40
    /// Nest's tool that calls a pixie on another engine, or from or to an ACP engine
    /// (B112): an agent call like Claude's Agent tool, the pixie's slug its subagent.
    public static let callPixie = "mcp__nest__call_pixie"

    public static func kind(of tool: String) -> Kind {
        switch tool {
        case "Read": .read
        case "Edit", "MultiEdit", "Write", "NotebookEdit": .edit
        case "Bash": .terminal
        case "Grep", "Glob": .search
        case "Task", "Agent", callPixie: .agent
        case "WebFetch", "WebSearch": .web
        case ArtifactTools.create, ArtifactTools.update: .artifact
        default: .other
        }
    }

    /// The tool's name as a row shows it: Nest's artifact tools in words.
    public static func name(of tool: String) -> String {
        switch tool {
        case _ where kind(of: tool) == .artifact: ArtifactText.toolTitle(tool)
        // A pixie call reads as Claude's own agent call on every engine (B112).
        case callPixie: "Agent"
        default: tool
        }
    }

    /// The subagent an agent call runs: its `subagent_type`, or the pixie a call_pixie
    /// call names.
    public static func subagent(tool: String, input: JSONValue) -> String? {
        guard kind(of: tool) == .agent else { return nil }
        return input[tool == callPixie ? "pixie" : "subagent_type"]?.stringValue
    }

    /// The argument of a tool call that is only described, such as a permission prompt's.
    public static func argument(tool: String, input: JSONValue) -> String {
        func text(_ key: String) -> String? { input[key]?.stringValue }
        switch kind(of: tool) {
        case .search where text("pattern") != nil:
            return (["\"\(text("pattern")!)\""] + [text("path")].compactMap { $0 })
                .joined(separator: " ")
        case .agent:
            return [subagent(tool: tool, input: input), text("description")].compactMap { $0 }
                .joined(separator: ": ")
        // Never the content, which can be a whole document.
        case .artifact:
            return text("title") ?? ""
        default:
            let keys = ["command", "file_path", "notebook_path", "path", "pattern", "url", "query"]
            return keys.lazy.compactMap(text).first ?? ""
        }
    }
}
