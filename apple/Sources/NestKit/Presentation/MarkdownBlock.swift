import Foundation

/// A table of a message: its cells are inline markdown for `RichText` to read.
public struct MarkdownTable: Sendable, Hashable {
    public enum Alignment: Sendable, Hashable {
        case leading, center, trailing
    }

    public var aligns: [Alignment]
    public var header: [String]
    /// Every row has as many cells as the header.
    public var rows: [[String]]

    public init(aligns: [Alignment], header: [String], rows: [[String]]) {
        self.aligns = aligns
        self.header = header
        self.rows = rows
    }
}

/// The block structure of an assistant message; inline markdown inside paragraphs,
/// headings, list items and table cells is left for `RichText` to read. The rules are those
/// of the web reader (`web/src/ui/markdownBlocks.ts`). Lists stay flat, each item with its
/// depth; what sits under an item (a fence, a table, another paragraph) is a block of its own.
public enum MarkdownBlock: Sendable, Hashable {
    case paragraph(String)
    case heading(level: Int, text: String)
    /// One list line; `marker` is "•" for bullets, "3." for numbered items or a task box,
    /// and `level` the nesting depth from the items around it.
    case listItem(marker: String, level: Int, text: String)
    /// Blocks under the list item of this `level` and `marker`.
    case underItem(level: Int, marker: String, blocks: [MarkdownBlock])
    case code(language: String?, text: String)
    case quote([MarkdownBlock])
    case table(MarkdownTable)
    case rule

    public static let openTask = "☐"
    public static let doneTask = "☑"
    static let maxLevel = 4

    public static func parse(_ text: String) -> [MarkdownBlock] {
        let unified =
            text.contains("\r")
            ? text.replacingOccurrences(of: "\r\n", with: "\n")
                .replacingOccurrences(of: "\r", with: "\n")
            : text
        return blocks(of: unified.components(separatedBy: "\n"))
    }

    private static func blocks(of lines: [String]) -> [MarkdownBlock] {
        var blocks: [MarkdownBlock] = []
        var at = 0
        while at < lines.count {
            let line = lines[at]
            if isBlank(line) {
                at += 1
            } else if fence(line) != nil {
                let (block, next) = fenced(lines, from: at)
                blocks.append(block)
                at = next
            } else if let heading = heading(line) {
                blocks.append(heading)
                at += 1
            } else if isRule(line) {
                blocks.append(.rule)
                at += 1
            } else if isQuote(line) {
                let (block, next) = quoted(lines, from: at)
                blocks.append(block)
                at = next
            } else if item(line) != nil {
                let (items, next) = listed(lines, from: at)
                blocks += items
                at = next
            } else if opensTable(line, following(lines, at)) {
                let (block, next) = table(lines, from: at)
                blocks.append(block)
                at = next
            } else {
                let (block, next) = paragraph(lines, from: at)
                blocks.append(block)
                at = next
            }
        }
        return blocks
    }

    private static func following(_ lines: [String], _ at: Int) -> String {
        at + 1 < lines.count ? lines[at + 1] : ""
    }

    /// Whether a line ends the text before it.
    private static func startsBlock(_ line: String, next: String) -> Bool {
        fence(line) != nil || heading(line) != nil || isRule(line) || isQuote(line)
            || item(line) != nil || opensTable(line, next)
    }

    private static func paragraph(_ lines: [String], from start: Int) -> (MarkdownBlock, Int) {
        var text = [trimmed(lines[start])]
        var at = start + 1
        while at < lines.count, !isBlank(lines[at]),
            !startsBlock(lines[at], next: following(lines, at))
        {
            text.append(trimmed(lines[at]))
            at += 1
        }
        return (.paragraph(text.joined(separator: "\n")), at)
    }

    // MARK: Lines

    private static func isSpace(_ character: Character) -> Bool {
        character == " " || character == "\t"
    }

    private static func isBlank(_ line: String) -> Bool {
        line.allSatisfy(\.isWhitespace)
    }

    private static func trimmed(_ line: String) -> String {
        line.trimmingCharacters(in: .whitespaces)
    }

    private static func withoutIndent(_ line: String) -> Substring {
        line.drop(while: isSpace)
    }

    private static func indent(of line: String) -> Int {
        var column = 0
        for character in line {
            if character == " " {
                column += 1
            } else if character == "\t" {
                column += 4
            } else {
                break
            }
        }
        return column
    }

    /// The line without up to `columns` of its leading space.
    private static func dedent(_ line: String, _ columns: Int) -> String {
        var column = 0
        var rest = Substring(line)
        while column < columns, let first = rest.first, isSpace(first) {
            column += first == " " ? 1 : 4
            rest = rest.dropFirst()
        }
        return String(rest)
    }

    private static func heading(_ line: String) -> MarkdownBlock? {
        let flush = trimmed(line)
        let hashes = flush.prefix { $0 == "#" }.count
        guard (1...6).contains(hashes), let space = flush.dropFirst(hashes).first, isSpace(space)
        else { return nil }
        var text = trimmed(String(flush.dropFirst(hashes)))
        let closing = text.reversed().prefix { $0 == "#" }.count
        if closing > 0, closing < text.count, let before = text.dropLast(closing).last,
            isSpace(before)
        {
            text = trimmed(String(text.dropLast(closing)))
        }
        return .heading(level: hashes, text: text)
    }

    private static func isRule(_ line: String) -> Bool {
        let marks = line.filter { !$0.isWhitespace }
        guard marks.count >= 3, let first = marks.first, "-*_".contains(first) else { return false }
        return marks.allSatisfy { $0 == first }
    }

    // MARK: Code

    /// The run of marks a fence line opens with.
    static func fence(_ line: String) -> String? {
        let flush = withoutIndent(line)
        guard let first = flush.first, first == "`" || first == "~" else { return nil }
        let marks = flush.prefix { $0 == first }
        return marks.count >= 3 ? String(marks) : nil
    }

    /// A code block, its lines without the fence's indent; unclosed, it runs to the end.
    private static func fenced(_ lines: [String], from start: Int) -> (MarkdownBlock, Int) {
        let open = lines[start]
        let marks = fence(open) ?? "```"
        let language = trimmed(String(withoutIndent(open).dropFirst(marks.count)))
        let indent = indent(of: open)
        var code: [String] = []
        var at = start + 1
        while at < lines.count {
            if withoutIndent(lines[at]).hasPrefix(marks) {
                at += 1
                break
            }
            code.append(dedent(lines[at], indent))
            at += 1
        }
        return (
            .code(language: language.isEmpty ? nil : language, text: code.joined(separator: "\n")),
            at
        )
    }

    // MARK: Quotes

    private static func isQuote(_ line: String) -> Bool {
        let spaces = line.prefix { $0 == " " }.count
        return spaces <= 3 && line.dropFirst(spaces).first == ">"
    }

    /// A quote inside a quote shows as one quote, which also keeps this from nesting endlessly.
    private static func quoted(_ lines: [String], from start: Int) -> (MarkdownBlock, Int) {
        var inner: [String] = []
        var at = start
        while at < lines.count, isQuote(lines[at]) {
            var rest = Substring(lines[at])
            while isQuote(String(rest)) {
                rest = rest.drop { $0 == " " }.dropFirst()
                if let first = rest.first, isSpace(first) {
                    rest = rest.dropFirst()
                }
            }
            inner.append(String(rest))
            at += 1
        }
        return (.quote(blocks(of: inner)), at)
    }

    // MARK: Lists

    /// "- text", "* text", "+ text", "1. text" or "1) text" at any indent, with a task box
    /// when the text opens with one.
    private static func item(_ line: String) -> (marker: String, text: String)? {
        guard !isRule(line) else { return nil }
        let rest = withoutIndent(line)
        var marker = "•"
        var after = rest.dropFirst()
        if let first = rest.first, !"-*+".contains(first) {
            let digits = rest.prefix { $0.isASCII && $0.isNumber }
            after = rest.dropFirst(digits.count)
            guard !digits.isEmpty, let close = after.first, ".)".contains(close) else { return nil }
            after = after.dropFirst()
            marker = "\(digits)."
        }
        guard let space = after.first, isSpace(space) else { return nil }
        let text = trimmed(String(after))
        if let box = taskBox(text) {
            return (box, trimmed(String(text.dropFirst(3))))
        }
        return (marker, text)
    }

    private static func taskBox(_ text: String) -> String? {
        let open = text.prefix(3)
        guard open.count == 3, open.first == "[", open.last == "]" else { return nil }
        if let after = text.dropFirst(3).first, !isSpace(after) { return nil }
        switch open.dropFirst().first {
        case " ": return openTask
        case "x", "X": return doneTask
        default: return nil
        }
    }

    /// The items of a list. An item's depth comes from the items around it, not from a fixed
    /// indent width: it goes under the nearest one whose marker it is indented past, so
    /// agents' 3 and 4 space sublists are one level deeper, as 2 space ones are.
    private static func listed(_ lines: [String], from start: Int) -> ([MarkdownBlock], Int) {
        var entries: [MarkdownBlock] = []
        var levels: [(indent: Int, marker: String)] = []
        var at = start
        while at < lines.count {
            let line = lines[at]
            if isBlank(line) {
                at += 1
                continue
            }
            let column = indent(of: line)
            if let item = item(line) {
                while let last = levels.last, last.indent >= column {
                    levels.removeLast()
                }
                entries.append(
                    .listItem(
                        marker: item.marker, level: min(maxLevel, levels.count), text: item.text))
                levels.append((column, item.marker))
                at += 1
                continue
            }
            let gap = isBlank(lines[at - 1])
            let flush = String(withoutIndent(line))
            let next = String(withoutIndent(following(lines, at)))
            if !gap, case .listItem(let marker, let level, let text)? = entries.last,
                !startsBlock(flush, next: next)
            {
                // A line under a list item continues it, as in CommonMark's lazy continuation.
                entries[entries.count - 1] = .listItem(
                    marker: marker, level: level, text: text + "\n" + trimmed(line))
                at += 1
                continue
            }
            guard let owner = levels.lastIndex(where: { $0.indent < column }) else { break }
            levels.removeSubrange((owner + 1)...)
            let (body, end) = underItem(lines, from: at, floor: levels[owner].indent)
            entries.append(
                .underItem(
                    level: min(maxLevel, owner), marker: levels[owner].marker,
                    blocks: blocks(of: body)))
            at = end
        }
        return (entries, at)
    }

    /// The lines under an item, without their indent, up to the next item or less indented line.
    private static func underItem(_ lines: [String], from start: Int, floor: Int) -> ([String], Int)
    {
        let column = indent(of: lines[start])
        var body: [String] = []
        var close: String?
        var at = start
        while at < lines.count {
            let line = lines[at]
            if let marks = close {
                if withoutIndent(line).hasPrefix(marks) {
                    close = nil
                }
            } else if !isBlank(line) {
                if indent(of: line) <= floor || item(line) != nil { break }
                close = fence(line)
            }
            body.append(dedent(line, column))
            at += 1
        }
        return (body, at)
    }

    // MARK: Tables

    private static func hasPipe(_ line: String) -> Bool {
        var previous: Character?
        for character in line {
            if character == "|", previous != "\\" { return true }
            previous = character
        }
        return false
    }

    /// Whether these two lines start a table: its header and a delimiter of as many columns.
    private static func opensTable(_ header: String, _ delimiter: String) -> Bool {
        guard delimiter.contains("-"), hasPipe(header) else { return false }
        return aligns(delimiter)?.count == cells(header).count
    }

    private static func aligns(_ delimiter: String) -> [MarkdownTable.Alignment]? {
        guard delimiter.contains("|") else { return nil }
        let cells = cells(delimiter)
        guard !cells.isEmpty else { return nil }
        var aligns: [MarkdownTable.Alignment] = []
        for cell in cells {
            let left = cell.hasPrefix(":")
            let right = cell.hasSuffix(":")
            let dashes = cell.dropFirst(left ? 1 : 0).dropLast(right ? 1 : 0)
            guard !dashes.isEmpty, dashes.allSatisfy({ $0 == "-" }) else { return nil }
            aligns.append(right ? (left ? .center : .trailing) : .leading)
        }
        return aligns
    }

    private static func table(_ lines: [String], from start: Int) -> (MarkdownBlock, Int) {
        let header = cells(lines[start])
        var rows: [[String]] = []
        var at = start + 2
        while at < lines.count, hasPipe(lines[at]),
            !startsBlock(lines[at], next: following(lines, at))
        {
            let row = cells(lines[at])
            rows.append(header.indices.map { $0 < row.count ? row[$0] : "" })
            at += 1
        }
        let table = MarkdownTable(
            aligns: aligns(lines[start + 1]) ?? [], header: header, rows: rows)
        return (.table(table), at)
    }

    /// A row's cells. A pipe splits a cell unless it is escaped or inside a code span. GFM does
    /// split inside code, but agents write `curl x | sh` in tables, escaped or not. In code an
    /// escaped pipe loses its backslash here, since inline code reads no escapes.
    private static func cells(_ row: String) -> [String] {
        let text = Array(trimmed(row))
        var cells: [String] = []
        var cell = ""
        var at = text.first == "|" ? 1 : 0
        while at < text.count {
            let character = text[at]
            if character == "\\" {
                cell += String(text[at..<min(at + 2, text.count)])
                at += 2
            } else if character == "`" {
                let end = codeEnd(text, from: at)
                cell += String(text[at..<end]).replacingOccurrences(of: "\\|", with: "|")
                at = end
            } else if character == "|" {
                cells.append(trimmed(cell))
                cell = ""
                at += 1
            } else {
                cell.append(character)
                at += 1
            }
        }
        if !isBlank(cell) {
            cells.append(trimmed(cell))
        }
        return cells
    }

    /// Where the code span opening at `start` ends; past its backticks alone when it never closes.
    private static func codeEnd(_ text: [Character], from start: Int) -> Int {
        func run(at index: Int) -> Int {
            var size = 0
            while index + size < text.count, text[index + size] == "`" {
                size += 1
            }
            return size
        }
        let size = run(at: start)
        let from = start + size
        var at = from
        while at < text.count {
            let found = run(at: at)
            if found == size { return at + size }
            at += max(found, 1)
        }
        return from
    }
}
