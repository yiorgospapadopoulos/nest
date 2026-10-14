import Foundation

/// The block structure of an assistant message; inline markdown inside paragraphs,
/// headings and list items is left for `RichText` to read.
public enum MarkdownBlock: Sendable, Hashable {
    case paragraph(String)
    case heading(level: Int, text: String)
    /// One list line; `marker` is "•" for bullets or "3." for numbered items, and `level`
    /// the nesting depth from the line's indentation.
    case listItem(marker: String, level: Int, text: String)
    case code(language: String?, text: String)

    public static func parse(_ text: String) -> [MarkdownBlock] {
        var blocks: [MarkdownBlock] = []
        var paragraph: [String] = []
        var item: (marker: String, level: Int, lines: [String])?
        var code: (language: String?, lines: [String])?

        func flush() {
            if !paragraph.isEmpty {
                blocks.append(.paragraph(paragraph.joined(separator: "\n")))
                paragraph = []
            }
            if let open = item {
                blocks.append(
                    .listItem(
                        marker: open.marker, level: open.level,
                        text: open.lines.joined(separator: "\n")))
                item = nil
            }
        }

        for line in text.components(separatedBy: "\n") {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if let open = code {
                if trimmed.hasPrefix("```") {
                    blocks.append(
                        .code(language: open.language, text: open.lines.joined(separator: "\n")))
                    code = nil
                } else {
                    code?.lines.append(line)
                }
            } else if trimmed.hasPrefix("```") {
                flush()
                let language = trimmed.dropFirst(3).trimmingCharacters(in: .whitespaces)
                code = (language.isEmpty ? nil : language, [])
            } else if let heading = heading(trimmed) {
                flush()
                blocks.append(heading)
            } else if trimmed.isEmpty {
                flush()
            } else if let list = listItem(line) {
                flush()
                item = (list.marker, list.level, [list.text])
            } else if item != nil {
                // A line under a list item continues it, as in CommonMark's lazy continuation.
                item?.lines.append(trimmed)
            } else {
                paragraph.append(line)
            }
        }
        flush()
        if let open = code {
            blocks.append(.code(language: open.language, text: open.lines.joined(separator: "\n")))
        }
        return blocks
    }

    private static func heading(_ line: String) -> MarkdownBlock? {
        let hashes = line.prefix { $0 == "#" }.count
        guard (1...6).contains(hashes), line.dropFirst(hashes).first == " " else { return nil }
        return .heading(
            level: hashes, text: line.dropFirst(hashes).trimmingCharacters(in: .whitespaces))
    }

    /// "- text", "* text", "+ text", "1. text" or "1) text", indented two spaces per level.
    private static func listItem(_ line: String) -> (marker: String, level: Int, text: String)? {
        let indent = line.prefix { $0 == " " }.count
        let rest = line.dropFirst(indent)
        let level = min(indent / 2, 4)
        if let first = rest.first, "-*+".contains(first), rest.dropFirst().first == " " {
            return ("•", level, rest.dropFirst(2).trimmingCharacters(in: .whitespaces))
        }
        let digits = rest.prefix { $0.isASCII && $0.isNumber }
        let after = rest.dropFirst(digits.count)
        guard !digits.isEmpty, let close = after.first, ".)".contains(close),
            after.dropFirst().first == " "
        else { return nil }
        return ("\(digits).", level, after.dropFirst(2).trimmingCharacters(in: .whitespaces))
    }
}
