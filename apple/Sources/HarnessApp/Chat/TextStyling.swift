import AppKit
import HarnessKit

/// The AppKit side of the transcript's selectable text: fonts, colors and paragraph
/// styles applied to `RichText` paragraphs and to plain output.
enum TextStyling {
    typealias Colors = DesignTokens.Colors

    static let primary = NSColor(Colors.Text.primary)
    static let secondary = NSColor(Colors.Text.secondary)
    static let tertiary = NSColor(Colors.Text.tertiary)
    static let codeBackground = NSColor(Colors.Surface.code)
    static let inlineCodeBackground = NSColor(Colors.Fill.strong)
    static let hairline = NSColor(Colors.Line.hairline)

    static func ui(_ size: Double, _ weight: NSFont.Weight = .regular) -> NSFont {
        .systemFont(ofSize: size, weight: weight)
    }

    static func mono(_ size: Double, _ weight: NSFont.Weight = .regular) -> NSFont {
        .monospacedSystemFont(ofSize: size, weight: weight)
    }

    // MARK: Messages

    private static let blockGap: CGFloat = 8
    private static let listGap: CGFloat = 3
    private static let codePadding: CGFloat = 8
    private static let codeInset: CGFloat = 10
    private static let listIndent: CGFloat = 16

    /// An assistant message: headings, paragraphs, lists and code blocks in one text.
    static func message(_ paragraphs: [RichParagraph]) -> NSAttributedString {
        let result = NSMutableAttributedString()
        var previousWasCode = false
        for (index, paragraph) in paragraphs.enumerated() {
            if index > 0 {
                result.append(NSAttributedString(string: "\n"))
            }
            let start = result.length
            let base = baseFont(paragraph.role)
            if !paragraph.prefix.isEmpty {
                result.append(
                    NSAttributedString(
                        string: paragraph.prefix,
                        attributes: [.font: base, .foregroundColor: secondary]))
            }
            for run in paragraph.runs {
                result.append(styled(run, base: base, inCodeBlock: paragraph.role.isCode))
            }
            let range = NSRange(location: start, length: result.length - start)
            var gap: CGFloat =
                switch paragraph.spacing {
                case .none: 0
                case .tight: listGap
                case .block: blockGap
                }
            if previousWasCode {
                gap += codePadding
            }
            if paragraph.role.isCode {
                gap += paragraph.spacing == .none ? 0 : codePadding
                result.addAttribute(
                    .blockDecoration,
                    value: BlockDecoration(
                        fill: codeBackground, stroke: hairline, radius: 9, outset: codePadding),
                    range: range)
            }
            applyParagraphStyle(
                style(for: paragraph.role), spacingBefore: gap, to: range, in: result)
            previousWasCode = paragraph.role.isCode
        }
        return result
    }

    private static func baseFont(_ role: RichParagraph.Role) -> NSFont {
        switch role {
        case .body, .listItem: ui(TypeSize.callout)
        case .heading(let level): ui(level <= 2 ? TypeSize.subhead : TypeSize.body, .bold)
        case .code: mono(11)
        }
    }

    private static func style(for role: RichParagraph.Role) -> NSMutableParagraphStyle {
        let style = NSMutableParagraphStyle()
        style.lineSpacing = 3
        switch role {
        case .body, .heading:
            break
        case .listItem(let marker, let level):
            let indent = CGFloat(level) * listIndent
            let hang = indent + (marker.count > 2 ? 26 : 18)
            style.firstLineHeadIndent = indent
            style.headIndent = hang
            style.tabStops = [NSTextTab(textAlignment: .left, location: hang)]
        case .code:
            style.firstLineHeadIndent = codeInset
            style.headIndent = codeInset
            style.tailIndent = -codeInset
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

    private static func styled(_ run: TextRun, base: NSFont, inCodeBlock: Bool)
        -> NSAttributedString
    {
        var font = base
        var attributes: [NSAttributedString.Key: Any] = [.foregroundColor: primary]
        if run.style.contains(.code), !inCodeBlock {
            font = mono(base.pointSize - 1)
            attributes[.backgroundColor] = inlineCodeBackground
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
        }
        if let link = run.link {
            attributes[.link] = link
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
}
