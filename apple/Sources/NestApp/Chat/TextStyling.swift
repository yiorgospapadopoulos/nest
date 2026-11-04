import AppKit
import NestKit

/// The AppKit side of the transcript's selectable text: fonts, colors and paragraph
/// styles applied to `RichText` paragraphs and to plain output.
enum TextStyling {
    typealias Colors = DesignTokens.Colors
    typealias Mac = DesignTokens.Colors.Mac

    static let primary = NSColor(Mac.textPrimary)
    static let secondary = NSColor(Mac.textSecondary)
    static let tertiary = NSColor(Mac.textTertiary)
    /// Code blocks and inline code: the look's soft fill, no border.
    static let codeBackground = NSColor(Mac.soft)

    static func ui(_ size: Double, _ weight: NSFont.Weight = .regular) -> NSFont {
        .systemFont(ofSize: size, weight: weight)
    }

    static func mono(_ size: Double, _ weight: NSFont.Weight = .regular) -> NSFont {
        .monospacedSystemFont(ofSize: size, weight: weight)
    }

    // MARK: Messages

    private static let blockGap: CGFloat = 9
    private static let listGap: CGFloat = 3
    private static let codePadding: CGFloat = 8
    /// Reading text at about 1.6 line height, as the mockup sets it.
    private static let lineSpacing: CGFloat = 4.5
    private static let codeInset: CGFloat = 10
    private static let listIndent: CGFloat = 16

    /// An assistant message: headings, paragraphs, lists, quotes, tables and code blocks in
    /// one text. With `fileLinks`, what names a file reads as a link and carries
    /// `fileReference`; where nothing could open it, such as a remote daemon, it stays text.
    static func message(_ paragraphs: [RichParagraph], fileLinks: Bool = false)
        -> NSAttributedString
    {
        let result = NSMutableAttributedString()
        var previous: RichParagraph?
        var quote: (start: Int, leading: CGFloat)?
        for (index, paragraph) in paragraphs.enumerated() {
            if let open = quote, !paragraph.quoted {
                closeQuote(from: open.start, leading: open.leading, in: result)
                quote = nil
            }
            let sameQuote = previous?.quoted == true && paragraph.quoted
            let afterBox = previous.map { isBox($0) && !sameQuote } ?? false
            let boxed = isBox(paragraph) && !sameQuote
            var gap: CGFloat =
                switch paragraph.spacing {
                case .none: 0
                case .tight: listGap
                case .block: blockGap
                }
            if afterBox {
                gap += codePadding
            }
            if boxed, paragraph.spacing != .none {
                gap += codePadding
            }
            if previous?.role.isTable == false {
                result.append(NSAttributedString(string: "\n"))
            }
            if paragraph.quoted, quote == nil {
                // Its box reaches past the text like a code block's.
                quote = (result.length, blockIndent(paragraph))
            }
            if case .table(let table) = paragraph.role {
                if previous?.role.isTable == true {
                    result.append(spacer(height: gap))
                } else if previous != nil {
                    addSpaceAfter(gap, in: result)
                }
                addTable(
                    table, leading: blockIndent(paragraph) + (paragraph.quoted ? codeInset : 0),
                    trailing: paragraph.quoted ? codeInset : 0,
                    isLast: index == paragraphs.count - 1, fileLinks: fileLinks, to: result)
            } else {
                addText(paragraph, spacingBefore: gap, fileLinks: fileLinks, to: result)
            }
            previous = paragraph
        }
        if let quote {
            closeQuote(from: quote.start, leading: quote.leading, in: result)
        }
        return result
    }

    private static func addText(
        _ paragraph: RichParagraph, spacingBefore gap: CGFloat, fileLinks: Bool,
        to result: NSMutableAttributedString
    ) {
        let start = result.length
        let base = baseFont(paragraph.role)
        if !paragraph.prefix.isEmpty {
            result.append(
                NSAttributedString(
                    string: paragraph.prefix,
                    attributes: [.font: base, .foregroundColor: secondary]))
        }
        var color = paragraph.quoted ? secondary : primary
        if case .rule = paragraph.role {
            color = .clear
        }
        let textStart = result.length
        for run in paragraph.runs {
            result.append(
                styled(
                    run, base: base, inCodeBlock: paragraph.role.isCode, color: color,
                    fileLinks: fileLinks))
        }
        if case .code(let language) = paragraph.role {
            addCodeColors(paragraph, language: language, from: textStart, in: result)
        }
        let range = NSRange(location: start, length: result.length - start)
        if paragraph.role.isCode, !paragraph.quoted {
            result.addAttribute(
                .blockDecoration,
                value: BlockDecoration(
                    fill: codeBackground, radius: Radius.card, outset: codePadding,
                    leading: blockIndent(paragraph)),
                range: range)
        }
        if case .rule = paragraph.role {
            result.addAttribute(
                .blockDecoration,
                value: BlockDecoration(
                    fill: NSColor(Mac.divider), leading: blockIndent(paragraph), isRule: true),
                range: range)
        }
        applyParagraphStyle(style(for: paragraph), spacingBefore: gap, to: range, in: result)
    }

    /// The block's colours, as attributes on the text, so drawing it costs nothing more.
    private static func addCodeColors(
        _ paragraph: RichParagraph, language: String?, from start: Int,
        in result: NSMutableAttributedString
    ) {
        let code = paragraph.runs.map(\.text).joined()
        for token in CodeColors.tokens(language: language, code: code) {
            result.addAttribute(
                .foregroundColor, value: codeColor(token.kind),
                range: NSRange(location: start + token.start, length: token.end - token.start))
        }
    }

    private static func codeColor(_ kind: CodeToken.Kind) -> NSColor {
        switch kind {
        case .comment: codeComment
        case .string: codeString
        case .keyword: codeKeyword
        case .number: codeNumber
        case .added: codeAdded
        case .removed: codeRemoved
        }
    }

    private static let codeComment = NSColor(Colors.Code.comment)
    private static let codeString = NSColor(Colors.Code.string)
    private static let codeKeyword = NSColor(Colors.Code.keyword)
    private static let codeNumber = NSColor(Colors.Code.number)
    private static let codeAdded = NSColor(Colors.Code.added)
    private static let codeRemoved = NSColor(Colors.Code.removed)

    /// Draws a box around a run of quoted paragraphs, gaps included.
    private static func closeQuote(
        from start: Int, leading: CGFloat, in result: NSMutableAttributedString
    ) {
        var end = result.length
        if (result.string as NSString).character(at: end - 1) == 10 {
            end -= 1
        }
        result.addAttribute(
            .blockDecoration,
            value: BlockDecoration(
                fill: codeBackground, radius: Radius.card, outset: codePadding, leading: leading),
            range: NSRange(location: start, length: end - start))
    }

    private static func isBox(_ paragraph: RichParagraph) -> Bool {
        paragraph.role.isCode || paragraph.quoted
    }

    private static func baseFont(_ role: RichParagraph.Role) -> NSFont {
        switch role {
        case .body, .listItem: ui(TypeSize.reading)
        case .heading(let level): ui(level <= 2 ? TypeSize.body : TypeSize.reading, .semibold)
        case .code: mono(TypeSize.meta)
        case .table: ui(TypeSize.ui)
        case .rule: ui(TypeSize.meta)
        }
    }

    /// How far a list marker's text hangs from the marker.
    private static func hang(_ marker: String) -> CGFloat {
        marker.count > 2 ? 26 : 18
    }

    /// Where a block under a list item starts: at the item's text.
    private static func blockIndent(_ paragraph: RichParagraph) -> CGFloat {
        paragraph.under.map { CGFloat($0.level) * listIndent + hang($0.marker) } ?? 0
    }

    private static func style(for paragraph: RichParagraph) -> NSMutableParagraphStyle {
        let role = paragraph.role
        let style = NSMutableParagraphStyle()
        style.lineSpacing = role.isCode ? 3 : lineSpacing
        let block = blockIndent(paragraph)
        let boxed = role.isCode || paragraph.quoted
        let inset = boxed ? codeInset : 0
        style.firstLineHeadIndent = block + inset
        style.headIndent = block + inset
        style.tailIndent = -inset
        if case .listItem(let marker, let level) = role {
            // Its level already counts the items it sits under.
            let indent = CGFloat(level) * listIndent
            let hanging = indent + hang(marker) + inset
            style.firstLineHeadIndent = indent + inset
            style.headIndent = hanging
            style.tabStops = [NSTextTab(textAlignment: .left, location: hanging)]
        }
        return style
    }

    /// Sets `style` on every line of `range` and the gap above its first line only, so
    /// soft line breaks and code lines stay together.
    private static func applyParagraphStyle(
        _ style: NSMutableParagraphStyle, spacingBefore gap: CGFloat, to range: NSRange,
        in text: NSMutableAttributedString
    ) {
        text.addAttribute(.paragraphStyle, value: style.copy(), range: range)
        let first = (text.string as NSString).paragraphRange(
            for: NSRange(location: range.location, length: 0))
        let leading = style.mutableCopy() as! NSMutableParagraphStyle
        leading.paragraphSpacingBefore = gap
        text.addAttribute(
            .paragraphStyle, value: leading, range: NSIntersectionRange(first, range))
    }

    // MARK: Tables

    private static let cellPadding = (x: CGFloat(12), y: CGFloat(7))
    private static let tableLineSpacing: CGFloat = 2

    /// The gap above a table: table cells take no space before, so the line before it gives
    /// it. The text ends with that line's break.
    private static func addSpaceAfter(_ gap: CGFloat, in text: NSMutableAttributedString) {
        let string = text.string as NSString
        let last = string.paragraphRange(for: NSRange(location: text.length - 1, length: 0))
        let style =
            (text.attribute(.paragraphStyle, at: last.location, effectiveRange: nil)
            as? NSParagraphStyle)?.mutableCopy() as? NSMutableParagraphStyle
            ?? NSMutableParagraphStyle()
        style.paragraphSpacing = gap
        text.addAttribute(.paragraphStyle, value: style, range: last)
    }

    /// An empty line between two tables, which would touch otherwise.
    private static func spacer(height: CGFloat) -> NSAttributedString {
        let style = NSMutableParagraphStyle()
        style.minimumLineHeight = height
        style.maximumLineHeight = height
        return NSAttributedString(
            string: "\n", attributes: [.paragraphStyle: style, .font: ui(TypeSize.meta)])
    }

    /// A table as an `NSTextTable`: each cell a paragraph, wrapping to its share of the width,
    /// with its line break copied as a tab or, at a row's end, a line break.
    private static func addTable(
        _ table: RichTable, leading: CGFloat, trailing: CGFloat, isLast: Bool, fileLinks: Bool,
        to result: NSMutableAttributedString
    ) {
        let frame = MessageTable(
            columns: columnWidths(table), leading: leading, trailing: trailing,
            padding: cellPadding.x)
        let rows = [table.header] + table.rows
        let start = result.length
        var cellStarts: [[Int]] = []
        for (rowIndex, row) in rows.enumerated() {
            var starts: [Int] = []
            for (column, cell) in row.enumerated() {
                let cellStart = result.length
                starts.append(cellStart - start)
                let align = column < table.aligns.count ? table.aligns[column] : .leading
                let isHeader = rowIndex == 0
                let font = cellFont(align: align, isHeader: isHeader)
                for run in cell {
                    result.append(
                        styled(
                            run, base: font, inCodeBlock: false, color: primary,
                            fileLinks: fileLinks))
                }
                let endsRow = column == row.count - 1
                var breakAttributes: [NSAttributedString.Key: Any] = [.font: font]
                if !endsRow {
                    breakAttributes[.copiedAs] = "\t"
                } else if isLast, rowIndex == rows.count - 1 {
                    breakAttributes[.copiedAs] = ""
                }
                result.append(NSAttributedString(string: "\n", attributes: breakAttributes))
                let block = NSTextTableBlock(
                    table: frame, startingRow: rowIndex, rowSpan: 1, startingColumn: column,
                    columnSpan: 1)
                block.setWidth(cellPadding.x, type: .absoluteValueType, for: .padding, edge: .minX)
                block.setWidth(cellPadding.x, type: .absoluteValueType, for: .padding, edge: .maxX)
                block.setWidth(cellPadding.y, type: .absoluteValueType, for: .padding, edge: .minY)
                block.setWidth(cellPadding.y, type: .absoluteValueType, for: .padding, edge: .maxY)
                let style = NSMutableParagraphStyle()
                style.textBlocks = [block]
                style.alignment = alignment(align)
                style.lineSpacing = tableLineSpacing
                result.addAttribute(
                    .paragraphStyle, value: style,
                    range: NSRange(location: cellStart, length: result.length - cellStart))
            }
            cellStarts.append(starts)
        }
        result.addAttribute(
            .tableDecoration,
            value: TableDecoration(
                fill: codeBackground, hairline: NSColor(Mac.divider), radius: Radius.card,
                rows: cellStarts),
            range: NSRange(location: start, length: result.length - start))
    }

    private static func alignment(_ align: MarkdownTable.Alignment) -> NSTextAlignment {
        switch align {
        case .leading: .left
        case .center: .center
        case .trailing: .right
        }
    }

    /// Right aligned columns hold numbers: tabular digits keep them in line.
    private static func cellFont(align: MarkdownTable.Alignment, isHeader: Bool) -> NSFont {
        let weight: NSFont.Weight = isHeader ? .semibold : .regular
        return align == .trailing
            ? .monospacedDigitSystemFont(ofSize: TypeSize.ui, weight: weight)
            : ui(TypeSize.ui, weight)
    }

    /// The width each column wants: its longest cell and its longest word, padding included.
    private static func columnWidths(_ table: RichTable) -> MessageTable.Columns {
        let padding = 2 * cellPadding.x
        var columns = MessageTable.Columns(
            longest: [Double](repeating: padding, count: table.header.count),
            longestWord: [Double](repeating: padding, count: table.header.count))
        for (rowIndex, row) in ([table.header] + table.rows).enumerated() {
            for (column, cell) in row.enumerated() {
                let align = column < table.aligns.count ? table.aligns[column] : .leading
                let font = cellFont(align: align, isHeader: rowIndex == 0)
                let width = cell.reduce(0.0) { width, run in
                    let runFont = run.style.contains(.code) ? mono(TypeSize.meta) : font
                    return width
                        + (run.text as NSString).size(withAttributes: [.font: runFont]).width
                }
                // Words measured by their share of the characters: a table may hold many.
                let characters = cell.reduce(0) { $0 + $1.text.count }
                let word =
                    cell.flatMap { $0.text.split(whereSeparator: \.isWhitespace) }.map(\.count)
                    .max()
                    ?? 0
                let wordWidth = width * Double(word) / Double(max(characters, 1))
                columns.longest[column] = max(columns.longest[column], ceil(width) + padding + 2)
                columns.longestWord[column] = max(
                    columns.longestWord[column], ceil(wordWidth) + padding + 2)
            }
        }
        return columns
    }

    // MARK: Runs

    private static func styled(
        _ run: TextRun, base: NSFont, inCodeBlock: Bool, color: NSColor, fileLinks: Bool
    ) -> NSAttributedString {
        var font = base
        var attributes: [NSAttributedString.Key: Any] = [.foregroundColor: color]
        if run.style.contains(.code), !inCodeBlock {
            font = mono(TypeSize.meta)
            attributes[.inlineChip] = codeBackground
        }
        var traits: NSFontDescriptor.SymbolicTraits = []
        if run.style.contains(.bold) { traits.insert(.bold) }
        if run.style.contains(.italic) { traits.insert(.italic) }
        if !traits.isEmpty {
            let descriptor = font.fontDescriptor.withSymbolicTraits(
                font.fontDescriptor.symbolicTraits.union(traits))
            font = NSFont(descriptor: descriptor, size: font.pointSize) ?? font
        }
        attributes[.font] = font
        if run.style.contains(.strikethrough) {
            attributes[.strikethroughStyle] = NSUnderlineStyle.single.rawValue
            attributes[.foregroundColor] = tertiary
        }
        if let link = run.link {
            attributes[.link] = link
        }
        if fileLinks, let file = run.file {
            // Not `.link`, which AppKit opens by itself: `MessageTextView` takes the click.
            attributes[.fileReference] = file
            attributes[.foregroundColor] = NSColor(Mac.link)
            attributes[.underlineStyle] = NSUnderlineStyle.single.rawValue
        }
        return NSAttributedString(string: run.text, attributes: attributes)
    }

    // MARK: Plain text

    /// Unstyled text such as a user message, a tool's output or thinking.
    static func plain(
        _ text: String, font: NSFont, color: NSColor, lineSpacing: CGFloat = 2
    ) -> NSAttributedString {
        let style = NSMutableParagraphStyle()
        style.lineSpacing = lineSpacing
        return NSAttributedString(
            string: text,
            attributes: [.font: font, .foregroundColor: color, .paragraphStyle: style])
    }
}

extension TextStyling {
    // MARK: Diffs

    static var diffFont: NSFont { mono(11.5) }

    /// A unified hunk as one text: line numbers (not copied), then the marked line on the
    /// change's color, wrapping under the code rather than under the numbers.
    static func unifiedHunk(_ hunk: Hunk) -> NSAttributedString {
        let result = NSMutableAttributedString()
        let decorations = DiffDecorations()
        for (index, line) in hunk.lines.enumerated() {
            let start = result.length
            result.append(gutter(number(line.oldLine, 5) + number(line.newLine, 5) + "  "))
            result.append(
                NSAttributedString(
                    string: marker(line.kind) + line.text,
                    attributes: [.font: diffFont, .foregroundColor: textColor(line.kind)]))
            if index < hunk.lines.count - 1 {
                result.append(NSAttributedString(string: "\n"))
            }
            if let decoration = decorations.decoration(for: line.kind) {
                result.addAttribute(
                    .blockDecoration, value: decoration,
                    range: NSRange(location: start, length: result.length - start))
            }
        }
        applyDiffStyle(to: result, hangingColumns: 14, truncates: false)
        return result
    }

    /// One side of a side-by-side hunk, one row per line so both sides stay level; long
    /// lines are cut short on screen but copy whole. Markers and numbers are not copied.
    static func splitSide(_ cells: [DiffCell?]) -> NSAttributedString {
        let result = NSMutableAttributedString()
        let decorations = DiffDecorations()
        for (index, cell) in cells.enumerated() {
            let start = result.length
            if let cell {
                result.append(gutter(number(cell.number, 5) + "  " + marker(cell.kind)))
                result.append(
                    NSAttributedString(
                        string: cell.text,
                        attributes: [.font: diffFont, .foregroundColor: textColor(cell.kind)]))
            } else {
                result.append(gutter(" "))
            }
            if index < cells.count - 1 {
                result.append(NSAttributedString(string: "\n"))
            }
            if let decoration = cell.map({ decorations.decoration(for: $0.kind) })
                ?? decorations.blank
            {
                result.addAttribute(
                    .blockDecoration, value: decoration,
                    range: NSRange(location: start, length: result.length - start))
            }
        }
        applyDiffStyle(to: result, hangingColumns: 9, truncates: true)
        return result
    }

    private static func gutter(_ text: String) -> NSAttributedString {
        NSAttributedString(
            string: text,
            attributes: [.font: diffFont, .foregroundColor: tertiary, .notCopied: true])
    }

    private static func number(_ value: Int?, _ width: Int) -> String {
        let text = value.map(String.init) ?? ""
        return String(repeating: " ", count: max(0, width - text.count)) + text
    }

    private static func marker(_ kind: DiffLineKind) -> String {
        switch kind {
        case .add: "+ "
        case .delete: "- "
        default: "  "
        }
    }

    private static func textColor(_ kind: DiffLineKind) -> NSColor {
        switch kind {
        case .add: NSColor(DesignTokens.Colors.Diff.addedText)
        case .delete: NSColor(DesignTokens.Colors.Diff.removedText)
        default: primary
        }
    }

    private static func applyDiffStyle(
        to text: NSMutableAttributedString, hangingColumns: Int, truncates: Bool
    ) {
        let advance = ("0" as NSString).size(withAttributes: [.font: diffFont]).width
        let style = NSMutableParagraphStyle()
        style.lineSpacing = 2
        style.headIndent = advance * CGFloat(hangingColumns)
        style.lineBreakMode = truncates ? .byTruncatingTail : .byWordWrapping
        text.addAttribute(
            .paragraphStyle, value: style, range: NSRange(location: 0, length: text.length))
    }
}

/// The line fills of one diff text; consecutive lines of a kind share one, so they join.
private struct DiffDecorations {
    let added = BlockDecoration(fill: NSColor(DesignTokens.Colors.Diff.addedFill))
    let removed = BlockDecoration(fill: NSColor(DesignTokens.Colors.Diff.removedFill))
    let blank = BlockDecoration(fill: NSColor(DesignTokens.Colors.Fill.subtle))

    func decoration(for kind: DiffLineKind) -> BlockDecoration? {
        switch kind {
        case .add: added
        case .delete: removed
        default: nil
        }
    }
}

extension RichParagraph.Role {
    var isCode: Bool {
        if case .code = self {
            return true
        }
        return false
    }

    var isTable: Bool {
        if case .table = self {
            return true
        }
        return false
    }
}
