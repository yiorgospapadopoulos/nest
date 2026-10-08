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

    public init(_ text: String, style: TextStyle = [], link: URL? = nil) {
        self.text = text
        self.style = style
        self.link = link
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

    public init(role: Role, runs: [TextRun], spacing: Spacing) {
        self.role = role
        self.runs = runs
        self.spacing = spacing
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
        for block in MarkdownBlock.parse(markdown) {
            let role: RichParagraph.Role
            let runs: [TextRun]
            switch block {
            case .paragraph(let text):
                (role, runs) = (.body, self.runs(text))
            case .heading(let level, let text):
                (role, runs) = (.heading(level: level), self.runs(text))
            case .listItem(let marker, let level, let text):
                (role, runs) = (.listItem(marker: marker, level: level), self.runs(text))
            case .code(let language, let text):
                (role, runs) = (.code(language: language), [TextRun(text, style: .code)])
            }
            let spacing: RichParagraph.Spacing =
                switch (paragraphs.last?.role, role) {
                case (nil, _): .none
                case (.listItem?, .listItem): .tight
                default: .block
                }
            paragraphs.append(RichParagraph(role: role, runs: runs, spacing: spacing))
        }
        return paragraphs
    }

    /// Inline markdown as runs. Foundation's parser also links bare web addresses; text
    /// it cannot read is shown as written.
    static func runs(
        _ text: String, parse: (String) throws -> AttributedString = parseInline
    ) -> [TextRun] {
        let attributed = (try? parse(text)) ?? AttributedString(text)
        return attributed.runs.map { run in
            let intent = run.inlinePresentationIntent ?? []
            var style: TextStyle = []
            if intent.contains(.stronglyEmphasized) { style.insert(.bold) }
            if intent.contains(.emphasized) { style.insert(.italic) }
            if intent.contains(.code) { style.insert(.code) }
            if intent.contains(.strikethrough) { style.insert(.strikethrough) }
            return TextRun(String(attributed[run.range].characters), style: style, link: run.link)
        }
    }

    private static func parseInline(_ text: String) throws -> AttributedString {
        try AttributedString(
            markdown: text,
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))
    }
}
