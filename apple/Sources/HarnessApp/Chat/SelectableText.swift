import AppKit
import SwiftUI

extension NSAttributedString.Key {
    /// A `BlockDecoration` drawn behind the lines of the range: code blocks and diff lines.
    static let blockDecoration = NSAttributedString.Key("harness.blockDecoration")
    /// Text that is shown but left out when copying, such as diff line numbers.
    static let notCopied = NSAttributedString.Key("harness.notCopied")
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
/// when it changes, so redraws keep the selection.
struct SelectableText: NSViewRepresentable {
    let key: String
    /// Shrinks to the longest line instead of taking the offered width (chat bubbles).
    var hugsWidth = false
    var linkColor: NSColor = .linkColor
    let build: () -> NSAttributedString

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
        view.setContent(build())
    }

    func sizeThatFits(
        _ proposal: ProposedViewSize, nsView view: MessageTextView, context: Context
    ) -> CGSize? {
        let offered = proposal.width.flatMap { $0.isFinite ? $0 : nil }
        let size = view.fit(width: offered ?? 100_000)
        guard let offered, !hugsWidth else { return size }
        return CGSize(width: offered, height: size.height)
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

    func setContent(_ text: NSAttributedString) {
        textStorage?.setAttributedString(text)
        measured = [:]
        needsDisplay = true
    }

    /// The size the text needs at `width`, decorations included.
    func fit(width: CGFloat) -> CGSize {
        if let size = measured[width] {
            return size
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
