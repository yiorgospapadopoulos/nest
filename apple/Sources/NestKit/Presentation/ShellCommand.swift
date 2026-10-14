import Foundation

/// A piece of an assistant message: markdown, or a code block holding a shell command
/// that gets Copy and Run in terminal buttons.
public enum MessageSegment: Sendable, Hashable {
    case markdown(String)
    case command(String)
}

/// Finds the shell commands in assistant messages: fenced blocks marked as shell, or an
/// unmarked block of one line that starts with a common command.
public enum ShellCommand {
    static let languages: Set<String> = ["sh", "bash", "zsh", "shell"]

    static let commonCommands: Set<String> = [
        "brew", "bun", "cargo", "cat", "cd", "chmod", "claude", "cp", "curl", "deno", "docker",
        "echo", "export", "find", "gh", "git", "go", "grep", "kill", "launchctl", "ls", "lsof",
        "make", "mkdir", "mv", "node", "npm", "npx", "open", "pip", "pip3", "pnpm", "ps",
        "pytest", "python", "python3", "rm", "ruff", "rsync", "scp", "sed", "source", "ssh",
        "sudo", "swift", "tail", "tailscale", "tar", "touch", "uv", "uvx", "which", "xcodebuild",
        "xcrun", "yarn",
    ]

    /// The command a code block holds, without "$ " prompts; nil when it is not one.
    public static func command(language: String?, code: String) -> String? {
        let lines = code.components(separatedBy: "\n")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        guard !lines.isEmpty else { return nil }
        let prompted = lines.allSatisfy { $0.hasPrefix("$ ") }
        let commands = prompted ? lines.map { String($0.dropFirst(2)) } : lines
        if let language, languages.contains(language.lowercased()) {
            return commands.joined(separator: "\n")
        }
        guard language == nil, commands.count == 1, let first = commands.first else {
            return nil
        }
        let word = first.prefix { !$0.isWhitespace }
        return commonCommands.contains(String(word)) || word.hasPrefix("./") ? first : nil
    }

    /// The message split around its shell command blocks; a message without any is one
    /// markdown segment. A block still streaming (not closed) stays markdown.
    public static func segments(_ markdown: String) -> [MessageSegment] {
        var segments: [MessageSegment] = []
        var pending: [String] = []
        var block: (language: String?, lines: [String])?

        func flush() {
            let text = pending.joined(separator: "\n")
            if !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                segments.append(.markdown(text))
            }
            pending = []
        }

        for line in markdown.components(separatedBy: "\n") {
            let isFence = line.trimmingCharacters(in: .whitespaces).hasPrefix("```")
            guard let open = block else {
                if isFence {
                    let info = line.trimmingCharacters(in: .whitespaces).dropFirst(3)
                        .trimmingCharacters(in: .whitespaces)
                    block = (info.isEmpty ? nil : info, [line])
                } else {
                    pending.append(line)
                }
                continue
            }
            guard isFence else {
                block?.lines.append(line)
                continue
            }
            let code = open.lines.dropFirst().joined(separator: "\n")
            if let command = command(language: open.language, code: code) {
                flush()
                segments.append(.command(command))
            } else {
                pending += open.lines + [line]
            }
            block = nil
        }
        pending += block?.lines ?? []
        flush()
        return segments
    }
}
