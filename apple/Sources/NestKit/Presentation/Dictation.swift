import Foundation

/// What dictation puts in a composer: the committed text (what was typed plus finalized
/// speech) and the volatile text still being recognized, shown lighter after it.
public struct DictationBuffer: Sendable, Equatable {
    public private(set) var committed: String
    /// The in-progress guess; replaced by each result and cleared by a final one.
    public private(set) var volatile = ""

    public init(text: String) {
        committed = text
    }

    /// Applies a recognition result. `current` is the field's text right now: what the
    /// user typed since the last result is kept, and speech continues after it.
    public mutating func apply(_ text: String, isFinal: Bool, current: String) {
        committed = current
        let words = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if isFinal {
            committed = Self.join(committed, words)
            volatile = ""
        } else {
            volatile = words
        }
    }

    /// Ends dictation: the volatile guess is kept as it is.
    public mutating func commit(current: String) {
        apply(volatile, isFinal: true, current: current)
    }

    /// The volatile text as shown after the committed text, with the space between them.
    public var volatileSuffix: String {
        volatile.isEmpty ? "" : String(Self.join(committed, volatile).dropFirst(committed.count))
    }

    /// Appends speech to text with one space between, none before punctuation or after
    /// whitespace.
    static func join(_ text: String, _ words: String) -> String {
        guard !words.isEmpty else { return text }
        guard let last = text.last, !last.isWhitespace else { return text + words }
        return ".,;:!?)]}'".contains(words.first!) ? text + words : text + " " + words
    }
}

/// Words that help speech recognition with this chat's vocabulary: the project, branch,
/// recent file names and common coding terms.
public enum DictationVocabulary {
    /// SFSpeechRecognizer suggests keeping contextual strings to about a hundred.
    public static let limit = 100

    public static let common = [
        "Nest", "Claude", "Claude Code", "worktree", "worktrees", "commit", "pull request",
        "branch", "merge", "rebase", "diff", "repo", "daemon", "SwiftUI", "TypeScript",
        "Python", "PWA", "API", "JSON", "README", "CLAUDE.md", "MCP", "npm", "uv",
    ]

    static let fileExtensions = [
        "swift", "py", "ts", "tsx", "js", "jsx", "json", "md", "toml", "yaml", "yml", "html",
        "css", "scss", "sh", "txt", "rs", "go", "kt", "java", "c", "h", "m", "mm", "cpp", "rb",
        "sql", "lock", "plist", "xml", "csv",
    ]

    /// Terms for one chat, most specific first, without duplicates.
    public static func terms(
        repo: String?, branch: String?, files: [String], limit: Int = Self.limit
    ) -> [String] {
        var terms: [String] = []
        if let repo {
            terms += [repo] + words(of: repo)
        }
        if let branch {
            terms += [branch] + words(of: (branch as NSString).lastPathComponent)
        }
        terms += recentFiles(files)
        terms += common
        var seen = Set<String>()
        let unique = terms.filter { seen.insert($0.lowercased()).inserted }
        return Array(unique.prefix(limit))
    }

    /// File names (and their stems) mentioned in the transcript, newest first.
    static func recentFiles(_ names: [String]) -> [String] {
        names.flatMap { name in
            let stem = (name as NSString).deletingPathExtension
            return stem.isEmpty || stem == name ? [name] : [name, stem]
        }
    }

    /// Words such as `SessionsStore.swift` or `models.py` in text, in order.
    static func fileNames(in text: String) -> [String] {
        let pattern = "[A-Za-z_][A-Za-z0-9_\\-]*\\.(?:\(fileExtensions.joined(separator: "|")))"
        let regex = try! NSRegularExpression(pattern: "\\b\(pattern)\\b")
        let range = NSRange(text.startIndex..., in: text)
        return regex.matches(in: text, range: range).map {
            (text as NSString).substring(with: $0.range)
        }
    }

    /// `map-viewer` and `fix_dark-mode` read as their words.
    static func words(of name: String) -> [String] {
        let words = name.split { $0 == "-" || $0 == "_" || $0 == "." }.map(String.init)
        return words.count > 1 ? [words.joined(separator: " ")] : []
    }
}
