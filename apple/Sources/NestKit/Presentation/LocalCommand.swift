import Foundation

/// A slash command Claude Code runs as an interactive screen of its own, which the SDK
/// cannot run: Nest opens its equivalent instead of sending it (B59). `/model` opens the
/// model picker, or with a name sets it; `/permissions` the permission mode picker; `/mcp`
/// the connectors; `/resume` the chat search. Other commands, `/clear` among them, go to
/// Claude Code as typed.
public enum LocalCommand: Sendable, Hashable {
    case model(String?)
    case permissions
    case mcp
    case resume(String?)

    /// The message as a command Nest runs; nil for anything to send as usual, including
    /// `/mcp` and `/permissions` with an argument, which go to Claude Code.
    public init?(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.hasPrefix("/") else { return nil }
        let name = trimmed.dropFirst().prefix { !$0.isWhitespace }
        let rest = trimmed.dropFirst(1 + name.count).trimmingCharacters(in: .whitespaces)
        let argument = rest.isEmpty ? nil : rest
        switch name {
        case "model": self = .model(argument)
        case "resume": self = .resume(argument)
        case "permissions" where argument == nil: self = .permissions
        case "mcp" where argument == nil: self = .mcp
        default: return nil
        }
    }

    /// The command picked from the suggestion list, without an argument.
    public init?(named name: String) {
        self.init("/\(name)")
    }

    /// The suggestion list's entries, in name order.
    public static let commands: [SlashCommand] = [
        SlashCommand(name: "mcp", description: "Show MCP servers and connectors"),
        SlashCommand(
            name: "model", description: "Choose the model", argumentHint: "[model]"),
        SlashCommand(name: "permissions", description: "Choose the permission mode"),
        SlashCommand(
            name: "resume", description: "Search and open another chat", argumentHint: "[search]"
        ),
    ]

    /// Claude Code's commands with Nest's, in name order; Nest's entry replaces one of the
    /// same name, since Nest runs it.
    public static func merged(_ known: [SlashCommand]) -> [SlashCommand] {
        let ours = Set(commands.map(\.name))
        return (known.filter { !ours.contains($0.name) } + commands).sorted { $0.name < $1.name }
    }

    /// The model `/model <name>` means: its value or name exactly, ignoring case, else the
    /// first whose value or name starts with it. Nil when none does.
    public static func model(named name: String, in models: [ModelInfo]) -> ModelInfo? {
        let wanted = name.lowercased()
        func names(_ info: ModelInfo) -> [String] {
            [info.value.lowercased(), info.displayName.lowercased()]
        }
        return models.first { names($0).contains(wanted) }
            ?? models.first { names($0).contains { $0.hasPrefix(wanted) } }
    }
}
