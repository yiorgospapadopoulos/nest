import Foundation

/// The change an Edit, MultiEdit or Write call makes, built from its input as the
/// transcript shows it under the call, like Claude's apps (B59): the replaced lines in
/// red, the new ones in green, unchanged lines of the edit as context. A Write is all
/// added, since its input does not hold what the file held before.
public struct EditDiff: Sendable, Hashable {
    public struct Line: Sendable, Hashable {
        /// `.context`, `.delete` or `.add`.
        public let kind: DiffLineKind
        public let text: String
    }

    /// Lines shown before "Show N more lines".
    public static let previewLines = 8

    public let path: String
    /// One run of lines per edit; only a MultiEdit has several.
    public let hunks: [[Line]]
    public let additions: Int
    public let deletions: Int

    /// Nil for other tools, a failed call (nothing changed), and a call without a path
    /// or without any changed line.
    public init?(_ call: ToolCall) {
        guard !call.isError, let path = call.input["file_path"]?.stringValue else { return nil }
        let input = call.input
        let hunks: [[Line]]
        switch call.name {
        case "Edit":
            hunks = [Self.lines(input)]
        case "MultiEdit":
            hunks = (input["edits"]?.arrayValue ?? []).map(Self.lines)
        case "Write":
            hunks = [Self.split(input["content"]?.stringValue).map { Line(kind: .add, text: $0) }]
        default:
            return nil
        }
        let changed = hunks.filter { $0.contains { $0.kind != .context } }
        guard !changed.isEmpty else { return nil }
        let all = changed.joined()
        self.path = path
        self.hunks = changed
        additions = all.count { $0.kind == .add }
        deletions = all.count { $0.kind == .delete }
    }

    /// "+3 -1"
    public var stat: String { "+\(additions) -\(deletions)" }

    /// The lines left out while collapsed.
    public var hiddenLines: Int {
        max(hunks.reduce(0) { $0 + $1.count } - Self.previewLines, 0)
    }

    /// "Show 7 more lines"; nil when the whole diff shows.
    public var expandLabel: String? {
        hiddenLines == 0 ? nil : "Show \(hiddenLines) more line\(hiddenLines == 1 ? "" : "s")"
    }

    /// The hunks to draw: all of them, or while collapsed the first `previewLines` lines.
    public func shown(expanded: Bool) -> [[Line]] {
        guard !expanded, hiddenLines > 0 else { return hunks }
        var left = Self.previewLines
        var shown: [[Line]] = []
        for hunk in hunks where left > 0 {
            shown.append(Array(hunk.prefix(left)))
            left -= min(hunk.count, left)
        }
        return shown
    }

    /// One edit's lines: a line diff of `old_string` against `new_string`, removals of a
    /// run before its additions.
    private static func lines(_ edit: JSONValue) -> [Line] {
        let old = split(edit["old_string"]?.stringValue)
        let new = split(edit["new_string"]?.stringValue)
        let difference = new.difference(from: old)
        var removed = Set<Int>()
        var inserted = Set<Int>()
        for change in difference {
            switch change {
            case .remove(let offset, _, _): removed.insert(offset)
            case .insert(let offset, _, _): inserted.insert(offset)
            }
        }
        var lines: [Line] = []
        var oldIndex = 0
        var newIndex = 0
        while oldIndex < old.count || newIndex < new.count {
            if removed.contains(oldIndex) {
                lines.append(Line(kind: .delete, text: old[oldIndex]))
                oldIndex += 1
            } else if inserted.contains(newIndex) {
                lines.append(Line(kind: .add, text: new[newIndex]))
                newIndex += 1
            } else {
                lines.append(Line(kind: .context, text: old[oldIndex]))
                oldIndex += 1
                newIndex += 1
            }
        }
        return lines
    }

    /// The text's lines; an empty text has none, and a final line break adds none.
    private static func split(_ text: String?) -> [String] {
        guard let text, !text.isEmpty else { return [] }
        var lines = text.components(separatedBy: "\n")
        if text.hasSuffix("\n") {
            lines.removeLast()
        }
        return lines
    }
}
