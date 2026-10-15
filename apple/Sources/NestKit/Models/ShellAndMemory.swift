import Foundation

/// `POST /api/sessions/{id}/shell`: a `!` command run in the chat's folder (B59).
public struct ShellRun: Decodable, Sendable, Hashable {
    public var command: String
    /// Nil when it timed out.
    public var exitCode: Int?
    /// Stdout and stderr merged, cut at 30,000 characters.
    public var output: String
    public var truncated: Bool
    public var timedOut: Bool
    /// What the next message tells Claude about the command.
    public var context: String

    public init(
        command: String, exitCode: Int?, output: String, truncated: Bool, timedOut: Bool,
        context: String
    ) {
        self.command = command
        self.exitCode = exitCode
        self.output = output
        self.truncated = truncated
        self.timedOut = timedOut
        self.context = context
    }

    enum CodingKeys: String, CodingKey {
        case command, output, truncated, context
        case exitCode = "exit_code"
        case timedOut = "timed_out"
    }

    /// The muted notes of the bash row: a failed exit, a timeout, a cut output.
    public var notes: [String] {
        var notes: [String] = []
        if let exitCode, exitCode != 0 {
            notes.append("exit \(exitCode)")
        }
        if timedOut {
            notes.append("timed out after 2 minutes")
        }
        if truncated {
            notes.append("output cut")
        }
        return notes
    }
}

/// Where a `#` memory is written.
public enum MemoryScope: String, Codable, Sendable, CaseIterable {
    /// `CLAUDE.md` in the project folder.
    case project
    /// `~/.claude/CLAUDE.md`, for all projects.
    case user

    public var label: String {
        switch self {
        case .project: "Project memory"
        case .user: "User memory"
        }
    }

    /// A pixie's chat has no project memory.
    public static func choices(pixie: Bool) -> [MemoryScope] {
        pixie ? [.user] : [.project, .user]
    }
}

/// `POST /api/sessions/{id}/memory`: the file the line was appended to.
public struct SavedMemory: Decodable, Sendable, Hashable {
    public var path: String
    public var scope: MemoryScope
    public var line: String

    public init(path: String, scope: MemoryScope, line: String) {
        self.path = path
        self.scope = scope
        self.line = line
    }

    /// "Saved to project memory".
    public var confirmation: String {
        "Saved to \(scope.label.lowercased())"
    }
}

/// An image a tool result carries, stored as a chat attachment.
public struct ToolImage: Decodable, Sendable, Hashable, Identifiable {
    public var attachmentID: String
    public var mediaType: String

    public var id: String { attachmentID }

    public init(attachmentID: String, mediaType: String) {
        self.attachmentID = attachmentID
        self.mediaType = mediaType
    }

    enum CodingKeys: String, CodingKey {
        case attachmentID = "attachment_id"
        case mediaType = "media_type"
    }
}

/// What the composer's text is: a message, a `!` shell command or a `#` memory, as in
/// Claude Code.
public enum ComposerInput: Sendable, Hashable {
    case message
    /// The command, without the `!`.
    case bash(String)
    /// The memory, without the `#`.
    case memory(String)

    /// `!` first is a command where `bash` is offered; `#` first and not `##` is a memory
    /// where `memory` is offered. Otherwise the text is a message.
    public static func of(_ text: String, bash: Bool, memory: Bool) -> ComposerInput {
        let rest = text.dropFirst().trimmingCharacters(in: .whitespacesAndNewlines)
        if bash && text.hasPrefix("!") {
            return .bash(rest)
        }
        if memory && text.hasPrefix("#") && !text.hasPrefix("##") {
            return .memory(rest)
        }
        return .message
    }

    /// The daemon runs commands in the user's own chats, not a pixie's or one a pixie
    /// started.
    public static func canRunShell(in session: Session?) -> Bool {
        guard let session else { return false }
        return session.pixieID == nil && session.startedByPixie == nil
    }
}

/// A command and its output as a sent message carries them for Claude.
public struct BashBlock: Sendable, Hashable {
    public var command: String
    public var stdout: String
    public var stderr: String

    public init(command: String, stdout: String, stderr: String) {
        self.command = command
        self.stdout = stdout
        self.stderr = stderr
    }

    /// Stdout, then stderr.
    public var output: String {
        [stdout, stderr].filter { !$0.isEmpty }.joined(separator: "\n")
    }
}

/// The `<bash-input>` blocks a message starts with, which the transcript shows as bash
/// rows (B59).
public enum BashBlocks {
    /// The leading blocks and the typed text after them; text that does not start with a
    /// whole block stays as it is.
    public static func split(_ text: String) -> (blocks: [BashBlock], rest: String) {
        var blocks: [BashBlock] = []
        var rest = Substring(text)
        while let (block, after) = block(at: rest) {
            blocks.append(block)
            rest = after
            if rest.hasPrefix("\n<bash-input>") {
                rest = rest.dropFirst()
            } else {
                break
            }
        }
        guard !blocks.isEmpty else { return ([], text) }
        return (blocks, String(rest.drop { $0 == "\n" }))
    }

    private static func block(at text: Substring) -> (BashBlock, Substring)? {
        guard text.hasPrefix("<bash-input>"),
            let (command, afterInput) = take(text.dropFirst(12), "</bash-input>\n<bash-stdout>"),
            let (stdout, afterOut) = take(afterInput, "</bash-stdout><bash-stderr>"),
            let (stderr, after) = take(afterOut, "</bash-stderr>")
        else { return nil }
        return (BashBlock(command: command, stdout: stdout, stderr: stderr), after)
    }

    /// The text before the first `end`, and what follows it.
    private static func take(_ text: Substring, _ end: String) -> (String, Substring)? {
        guard let range = text.range(of: end) else { return nil }
        return (String(text[..<range.lowerBound]), text[range.upperBound...])
    }

    /// The message Claude gets: the commands' contexts, then the typed text.
    public static func message(_ text: String, contexts: [String]) -> String {
        contexts.isEmpty ? text : contexts.joined(separator: "\n") + "\n\n" + text
    }
}
