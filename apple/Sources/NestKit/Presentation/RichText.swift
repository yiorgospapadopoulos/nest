import Foundation

/// Inline styles of a run of message text.
public struct TextStyle: OptionSet, Sendable, Hashable {
    public let rawValue: Int

    public init(rawValue: Int) {
        self.rawValue = rawValue
    }

    public static let bold = TextStyle(rawValue: 1 << 0)
    public static let italic = TextStyle(rawValue: 1 << 1)
    public static let code = TextStyle(rawValue: 1 << 2)
    public static let strikethrough = TextStyle(rawValue: 1 << 3)
}

/// A stretch of text with one style and, for links, where it points.
public struct TextRun: Sendable, Hashable {
    public var text: String
    public var style: TextStyle
    public var link: URL?
    /// The file it names, as the message wrote it; not checked yet (`FileReference`).
    public var file: String?

    public init(_ text: String, style: TextStyle = [], link: URL? = nil, file: String? = nil) {
        self.text = text
        self.style = style
        self.link = link
        self.file = file
    }
}

/// A table with its cells read into runs.
public struct RichTable: Sendable, Hashable {
    public let aligns: [MarkdownTable.Alignment]
    public let header: [[TextRun]]
    public let rows: [[[TextRun]]]

    public init(aligns: [MarkdownTable.Alignment], header: [[TextRun]], rows: [[[TextRun]]]) {
        self.aligns = aligns
        self.header = header
        self.rows = rows
    }
}

/// One paragraph of a message as the transcript lays it out.
public struct RichParagraph: Sendable, Hashable {
    public enum Role: Sendable, Hashable {
        case body
        case heading(level: Int)
        case listItem(marker: String, level: Int)
        /// A whole fenced block; its runs hold every line.
        case code(language: String?)
        /// A whole table; it has no runs of its own.
        case table(RichTable)
        /// A horizontal rule; its one run is what it copies as.
        case rule
    }

    /// The list item a block sits under, which sets its indent.
    public struct Under: Sendable, Hashable {
        public let level: Int
        public let marker: String

        public init(level: Int, marker: String) {
            self.level = level
            self.marker = marker
        }
    }

    /// The space above a paragraph.
    public enum Spacing: Sendable, Hashable {
        /// The first paragraph.
        case none
        /// Between items of one list.
        case tight
        /// Between blocks.
        case block
    }

    public let role: Role
    public let runs: [TextRun]
    public let spacing: Spacing
    public let under: Under?
    /// Part of a block quote; neighbouring quoted paragraphs share one box.
    public let quoted: Bool

    public init(
        role: Role, runs: [TextRun], spacing: Spacing, under: Under? = nil, quoted: Bool = false
    ) {
        self.role = role
        self.runs = runs
        self.spacing = spacing
        self.under = under
        self.quoted = quoted
    }

    /// What precedes the runs on screen: a list marker and a tab to the hanging indent.
    public var prefix: String {
        if case .listItem(let marker, _) = role {
            return marker + "\t"
        }
        return ""
    }
}

/// Turns an assistant message's markdown into styled paragraphs, so the app can lay a
/// whole message out as one selectable text.
public enum RichText {
    public static func paragraphs(_ markdown: String) -> [RichParagraph] {
        var paragraphs: [RichParagraph] = []
        add(MarkdownBlock.parse(markdown), under: nil, quoted: false, to: &paragraphs)
        return paragraphs
    }

    private static func add(
        _ blocks: [MarkdownBlock], under: RichParagraph.Under?, quoted: Bool,
        to paragraphs: inout [RichParagraph]
    ) {
        for block in blocks {
            let role: RichParagraph.Role
            let runs: [TextRun]
            switch block {
            case .paragraph(let text):
                (role, runs) = (.body, self.runs(text))
            case .heading(let level, let text):
                (role, runs) = (.heading(level: level), self.runs(text))
            case .listItem(let marker, let level, let text):
                let depth = level + (under.map { $0.level + 1 } ?? 0)
                let inner = RichParagraph.Role.listItem(marker: marker, level: depth)
                (role, runs) = (inner, self.runs(text))
            case .code(let language, let text):
                (role, runs) = (.code(language: language), [TextRun(text, style: .code)])
            case .table(let table):
                (role, runs) = (.table(self.table(table)), [])
            case .rule:
                (role, runs) = (.rule, [TextRun("---")])
            case .quote(let inner):
                add(inner, under: under, quoted: true, to: &paragraphs)
                continue
            case .underItem(let level, let marker, let inner):
                let depth = level + (under.map { $0.level + 1 } ?? 0)
                add(
                    inner, under: .init(level: depth, marker: marker), quoted: quoted,
                    to: &paragraphs)
                continue
            }
            let spacing: RichParagraph.Spacing =
                switch (paragraphs.last?.role, role) {
                case (nil, _): .none
                case (.listItem?, .listItem): .tight
                default: .block
                }
            paragraphs.append(
                RichParagraph(
                    role: role, runs: runs, spacing: spacing, under: under, quoted: quoted))
        }
    }

    private static func table(_ table: MarkdownTable) -> RichTable {
        RichTable(
            aligns: table.aligns, header: table.header.map { runs($0) },
            rows: table.rows.map { $0.map { runs($0) } })
    }

    /// Inline markdown as runs. Foundation's parser also links bare web addresses; text
    /// it cannot read is shown as written, and links of other schemes as plain text. What
    /// names a file carries it: never as a link, so `SafeLink` stays the only way to one.
    static func runs(
        _ text: String, parse: (String) throws -> AttributedString = parseInline
    ) -> [TextRun] {
        let attributed = (try? parse(text)) ?? AttributedString(text)
        return attributed.runs.flatMap { run -> [TextRun] in
            let intent = run.inlinePresentationIntent ?? []
            var style: TextStyle = []
            if intent.contains(.stronglyEmphasized) { style.insert(.bold) }
            if intent.contains(.emphasized) { style.insert(.italic) }
            if intent.contains(.code) { style.insert(.code) }
            if intent.contains(.strikethrough) { style.insert(.strikethrough) }
            let shown = String(attributed[run.range].characters)
            if let link = run.link {
                // Only links the app may open stay links (`SafeLink`).
                return SafeLink.allows(link)
                    ? [TextRun(shown, style: style, link: link)]
                    : [
                        TextRun(
                            shown, style: style, file: FileReference.inLink(link.relativeString))
                    ]
            }
            if style.contains(.code) {
                return [TextRun(shown, style: style, file: FileReference.inCode(shown))]
            }
            return plainRuns(shown, style: style)
        }
    }

    /// Text with no marks of its own, split where it names a file.
    private static func plainRuns(_ text: String, style: TextStyle) -> [TextRun] {
        let found = FileReference.inText(text)
        guard !found.isEmpty else { return [TextRun(text, style: style)] }
        let units = Array(text.utf16)
        func part(_ range: Range<Int>) -> String {
            String(decoding: units[range], as: UTF16.self)
        }
        var runs: [TextRun] = []
        var last = 0
        for reference in found {
            if reference.start > last {
                runs.append(TextRun(part(last..<reference.start), style: style))
            }
            runs.append(
                TextRun(part(reference.start..<reference.end), style: style, file: reference.path))
            last = reference.end
        }
        if last < units.count {
            runs.append(TextRun(part(last..<units.count), style: style))
        }
        return runs
    }

    private static func parseInline(_ text: String) throws -> AttributedString {
        try AttributedString(
            markdown: text,
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))
    }
}
