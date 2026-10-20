import AppKit
import SwiftUI

extension NSAttributedString.Key {
    /// A `BlockDecoration` drawn behind the lines of the range: code blocks and diff lines.
    static let blockDecoration = NSAttributedString.Key("nest.blockDecoration")
    /// Text that is shown but left out when copying, such as diff line numbers.
    static let notCopied = NSAttributedString.Key("nest.notCopied")
    /// An `NSColor` drawn as a small rounded chip behind the range: inline code.
    static let inlineChip = NSAttributedString.Key("nest.inlineChip")
}

/// A fill behind whole lines of text, the full width of the view.
final class BlockDecoration: NSObject {
    let fill: NSColor
    let stroke: NSColor?
    let radius: CGFloat
    /// Room around the glyphs; with none, whole line fragments are filled edge to edge so
    /// neighbouring lines join up.
    let outset: CGFloat

    init(fill: NSColor, stroke: NSColor? = nil, radius: CGFloat = 0, outset: CGFloat = 0) {
        self.fill = fill
        self.stroke = stroke
        self.radius = radius
        self.outset = outset
    }
}

/// Read-only text that selects across paragraphs and copies with Cmd+C, sized to its
/// content for a SwiftUI stack. `key` identifies the content: the text is rebuilt only
/// when it changes, so redraws keep the selection. The built text and its measured sizes
/// are shared through `SelectableTextCache`, by the call site and `key`.
struct SelectableText: NSViewRepresentable {
    let key: String
    /// Shrinks to the longest line instead of taking the offered width (chat bubbles).
    var hugsWidth = false
    var linkColor: NSColor = .linkColor
    /// The call site and key, as two sites may style the same text differently; or, for
    /// text that `SelectableTextCache.warm` prepares ahead, its kind and key.
    let cacheID: String
    /// The kind whose offered width is noted, for preparing that kind ahead.
    let kind: String?
    let build: () -> NSAttributedString

    init(
        key: String, hugsWidth: Bool = false, linkColor: NSColor = .linkColor,
        kind: String? = nil, file: String = #fileID, line: Int = #line,
        build: @escaping () -> NSAttributedString
    ) {
        self.key = key
        self.hugsWidth = hugsWidth
        self.linkColor = linkColor
        self.kind = kind
        cacheID = SelectableTextCache.id(kind: kind ?? "\(file):\(line)", key: key)
        self.build = build
    }

    final class Coordinator {
        var key: String?
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> MessageTextView {
        MessageTextView.make()
    }

    func updateNSView(_ view: MessageTextView, context: Context) {
        view.linkTextAttributes = [
            .foregroundColor: linkColor, .underlineStyle: NSUnderlineStyle.single.rawValue,
            .cursor: NSCursor.pointingHand,
        ]
        guard context.coordinator.key != key else { return }
        context.coordinator.key = key
        view.setContent(SelectableTextCache.text(cacheID, build: build), cacheID: cacheID)
    }

    func sizeThatFits(
        _ proposal: ProposedViewSize, nsView view: MessageTextView, context: Context
    ) -> CGSize? {
        let offered = proposal.width.flatMap { $0.isFinite ? $0 : nil }
        if let kind, let offered {
            SelectableTextCache.noteWidth(offered, of: kind)
        }
        let size = view.fit(width: offered ?? 100_000)
        guard let offered, !hugsWidth else { return size }
        return CGSize(width: offered, height: size.height)
    }
}

/// Built text and measured sizes shared by every `SelectableText`. The lazy transcript
/// makes a new text view each time a message scrolls back into view; parsing and laying
/// out its text again on that frame made scrolling stutter.
@MainActor enum SelectableTextCache {
    final class Measured: NSObject {
        let size: CGSize
        let topOverflow: CGFloat

        init(size: CGSize, topOverflow: CGFloat) {
            self.size = size
            self.topOverflow = topOverflow
        }
    }

    private static let texts: NSCache<NSString, NSAttributedString> = {
        let cache = NSCache<NSString, NSAttributedString>()
        cache.countLimit = 2_000
        return cache
    }()
    private static let sizes: NSCache<NSString, Measured> = {
        let cache = NSCache<NSString, Measured>()
        cache.countLimit = 4_000
        return cache
    }()

    /// The width each kind was last offered, to measure its texts at ahead of time.
    private static var widths: [String: CGFloat] = [:]
    /// Lays out the texts that `warm` prepares, never shown.
    private static let scratch = MessageTextView.make()

    static func id(kind: String, key: String) -> String { "\(kind)\n\(key)" }

    static func noteWidth(_ width: CGFloat, of kind: String) {
        widths[kind] = width
    }

    /// Builds and measures texts of `kind` before they scroll into view, a few at a time
    /// between frames, so that a fast scroll through a chat just opened finds them ready.
    /// Waits for a text of the kind to lay out first, to learn its width.
    static func warm(_ keys: [String], kind: String, build: (String) -> NSAttributedString)
        async
    {
        for _ in 0..<40 where widths[kind] == nil {
            try? await Task.sleep(for: .milliseconds(50))
        }
        for (index, key) in keys.enumerated() {
            guard !Task.isCancelled else { return }
            let id = id(kind: kind, key: key)
            let text = text(id) { build(key) }
            if let width = widths[kind], size(id, width: width) == nil {
                scratch.setContent(text, cacheID: id)
                _ = scratch.fit(width: width)
            }
            if index % 4 == 3 {
                // Leaves the main thread free for the frames in between.
                try? await Task.sleep(for: .milliseconds(4))
            }
        }
    }

    static func text(_ id: String, build: () -> NSAttributedString) -> NSAttributedString {
        if let text = texts.object(forKey: id as NSString) {
            return text
        }
        let text = build()
        texts.setObject(text, forKey: id as NSString)
        return text
    }

    static func size(_ id: String, width: CGFloat) -> Measured? {
        sizes.object(forKey: "\(width)\n\(id)" as NSString)
    }

    static func store(_ measured: Measured, _ id: String, width: CGFloat) {
        sizes.setObject(measured, forKey: "\(width)\n\(id)" as NSString)
    }
}

/// How far an inline code chip reaches past its glyphs on one side.
enum InlineChip {
    /// Into a space or past a line's end: the chip's full padding.
    static let room: CGFloat = 2.5
    /// Against punctuation or a letter: barely past the glyph, so the neighbour sits as
    /// close as after a plain word.
    static let tight: CGFloat = 1

    /// The padding next to the character at `index` of `text`: full room when it is a
    /// space or a line break, or outside the text; tight otherwise.
    static func pad(nextTo index: Int, in text: NSString) -> CGFloat {
        guard index >= 0, index < text.length else { return room }
        let character = text.character(at: index)
        guard let scalar = Unicode.Scalar(character) else { return tight }
        return CharacterSet.whitespacesAndNewlines.contains(scalar) ? room : tight
    }
}

/// A TextKit 1 text view (for its line fragment geometry) that draws block decorations,
/// copies without `notCopied` text and drops its selection when another view takes focus.
final class MessageTextView: NSTextView {
    /// Measures on its own layout manager, so probing sizes never disturbs the laid out text.
    private let measuring = NSLayoutManager()
    private let measuringContainer = NSTextContainer()
    private var measured: [CGFloat: CGSize] = [:]
    private var topOverflow: CGFloat = 0
    /// The content's id in `SelectableTextCache`, for its shared sizes.
    private var cacheID: String?

    static func make() -> MessageTextView {
        let storage = NSTextStorage()
        let manager = NSLayoutManager()
        storage.addLayoutManager(manager)
        let container = NSTextContainer(
            size: NSSize(width: 100, height: CGFloat.greatestFiniteMagnitude))
        container.widthTracksTextView = true
        container.lineFragmentPadding = 0
        manager.addTextContainer(container)
        let view = MessageTextView(frame: .zero, textContainer: container)
        storage.addLayoutManager(view.measuring)
        view.measuringContainer.lineFragmentPadding = 0
        view.measuring.addTextContainer(view.measuringContainer)
        view.isEditable = false
        view.isSelectable = true
        view.isRichText = true
        view.drawsBackground = false
        view.textContainerInset = .zero
        view.isVerticallyResizable = false
        view.isHorizontallyResizable = false
        view.usesFindBar = false
        return view
    }

    func setContent(_ text: NSAttributedString, cacheID: String? = nil) {
        textStorage?.setAttributedString(text)
        self.cacheID = cacheID
        measured = [:]
        needsDisplay = true
    }

    /// The size the text needs at `width`, decorations included.
    func fit(width: CGFloat) -> CGSize {
        if let size = measured[width] {
            return size
        }
        if let cacheID, let shared = SelectableTextCache.size(cacheID, width: width) {
            topOverflow = shared.topOverflow
            measured[width] = shared.size
            return shared.size
        }
        measuringContainer.size = NSSize(
            width: max(width, 1), height: CGFloat.greatestFiniteMagnitude)
        measuring.ensureLayout(for: measuringContainer)
        let used = measuring.usedRect(for: measuringContainer)
        let blocks = decorationRects(in: measuring)
        // Only a code block at the very top reaches above the text; that does not depend on
        // the width, so any measurement sets it.
        topOverflow = blocks.map(\.rect.minY).min().map { max(0, -$0) } ?? 0
        let bottom = max(used.maxY, blocks.map(\.rect.maxY).max() ?? 0)
        let size = CGSize(width: ceil(used.width) + 1, height: ceil(topOverflow + bottom))
        measured[width] = size
        if let cacheID {
            SelectableTextCache.store(
                .init(size: size, topOverflow: topOverflow), cacheID, width: width)
        }
        return size
    }

    override var textContainerOrigin: NSPoint {
        NSPoint(x: 0, y: topOverflow)
    }

    override func drawBackground(in rect: NSRect) {
        super.drawBackground(in: rect)
        guard let manager = layoutManager else { return }
        let origin = textContainerOrigin
        for (decoration, area) in decorationRects(in: manager) {
            var area = area.offsetBy(dx: origin.x, dy: origin.y)
            area.origin.x = bounds.minX
            area.size.width = bounds.width
            guard area.intersects(rect) else { continue }
            let path =
                decoration.radius > 0
                ? NSBezierPath(
                    roundedRect: area.insetBy(dx: 0.5, dy: 0.5), xRadius: decoration.radius,
                    yRadius: decoration.radius)
                : NSBezierPath(rect: area)
            decoration.fill.setFill()
            path.fill()
            if let stroke = decoration.stroke {
                stroke.setStroke()
                path.lineWidth = 1
                path.stroke()
            }
        }
        drawInlineChips(in: rect, manager: manager, origin: origin)
    }

    /// Inline code chips: a rounded fill around the glyphs of each line the range covers,
    /// as tall as the font rather than the line, so the line spacing stays clear. The chip
    /// adds no width to the text: it reaches into a neighbouring space (or a line's end)
    /// and stays tight against neighbouring punctuation, which hugs it as after a word.
    private func drawInlineChips(in rect: NSRect, manager: NSLayoutManager, origin: NSPoint) {
        guard let storage = textStorage, let container = textContainer else { return }
        let text = storage.string as NSString
        storage.enumerateAttribute(
            .inlineChip, in: NSRange(location: 0, length: storage.length)
        ) { value, range, _ in
            guard let color = value as? NSColor else { return }
            let font = storage.attribute(.font, at: range.location, effectiveRange: nil) as? NSFont
            let ascender = font?.ascender ?? 10
            let descender = font?.descender ?? -3
            let glyphs = manager.glyphRange(forCharacterRange: range, actualCharacterRange: nil)
            let before = InlineChip.pad(nextTo: range.location - 1, in: text)
            let after = InlineChip.pad(nextTo: NSMaxRange(range), in: text)
            manager.enumerateLineFragments(forGlyphRange: glyphs) { fragment, _, _, lineGlyphs, _ in
                let part = NSIntersectionRange(lineGlyphs, glyphs)
                guard part.length > 0 else { return }
                let bounds = manager.boundingRect(forGlyphRange: part, in: container)
                let baseline = fragment.minY + manager.location(forGlyphAt: part.location).y
                // A chip that wraps keeps the full room at the line breaks.
                let leading = part.location == glyphs.location ? before : InlineChip.room
                let trailing = NSMaxRange(part) == NSMaxRange(glyphs) ? after : InlineChip.room
                let chip = CGRect(
                    x: bounds.minX - leading, y: baseline - ascender - 1.5,
                    width: bounds.width + leading + trailing, height: ascender - descender + 3
                ).offsetBy(dx: origin.x, dy: origin.y)
                guard chip.intersects(rect) else { return }
                color.setFill()
                NSBezierPath(roundedRect: chip, xRadius: Radius.chip, yRadius: Radius.chip).fill()
            }
        }
    }

    /// Each decorated range's lines, in text container coordinates.
    private func decorationRects(in manager: NSLayoutManager) -> [(
        decoration: BlockDecoration, rect: CGRect
    )] {
        guard let storage = textStorage else { return [] }
        var rects: [(BlockDecoration, CGRect)] = []
        storage.enumerateAttribute(
            .blockDecoration, in: NSRange(location: 0, length: storage.length)
        ) { value, range, _ in
            guard let decoration = value as? BlockDecoration else { return }
            let glyphs = manager.glyphRange(forCharacterRange: range, actualCharacterRange: nil)
            var area = CGRect.null
            manager.enumerateLineFragments(forGlyphRange: glyphs) { fragment, used, _, _, _ in
                area = area.union(decoration.outset > 0 ? used : fragment)
            }
            if !area.isNull {
                rects.append((decoration, area.insetBy(dx: 0, dy: -decoration.outset)))
            }
        }
        return rects
    }

    override func copy(_ sender: Any?) {
        guard let storage = textStorage, Self.containsNotCopied(storage) else {
            super.copy(sender)
            return
        }
        var text = ""
        for value in selectedRanges {
            storage.enumerateAttribute(.notCopied, in: value.rangeValue) { skip, part, _ in
                if skip == nil {
                    text += storage.attributedSubstring(from: part).string
                }
            }
        }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }

    private static func containsNotCopied(_ storage: NSTextStorage) -> Bool {
        var found = false
        storage.enumerateAttribute(.notCopied, in: NSRange(location: 0, length: storage.length)) {
            value, _, stop in
            if value != nil {
                found = true
                stop.pointee = true
            }
        }
        return found
    }

    override func resignFirstResponder() -> Bool {
        setSelectedRange(NSRange(location: selectedRange().location, length: 0))
        return super.resignFirstResponder()
    }
}
