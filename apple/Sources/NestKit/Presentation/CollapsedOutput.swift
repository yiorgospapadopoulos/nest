import Foundation

/// A tool's output as the transcript shows it, like Claude's apps: whole when short, else
/// its first lines with a control to show the rest. Nothing is ever cut for good (B59).
public struct CollapsedOutput: Sendable, Hashable {
    public static let maxLines = 10
    /// A few very long lines collapse too.
    public static let maxCharacters = 2000

    public let full: String
    /// What shows while collapsed: the whole output when it is short.
    public let preview: String
    /// The lines the preview leaves out.
    public let hiddenLines: Int

    public init(
        _ text: String, maxLines: Int = Self.maxLines, maxCharacters: Int = Self.maxCharacters
    ) {
        full = text
        // Scans bytes: outputs can be large, and this runs as the row draws.
        var lineBreaks = 0
        var cut: String.Index?
        for index in text.utf8.indices where text.utf8[index] == UInt8(ascii: "\n") {
            lineBreaks += 1
            if lineBreaks == maxLines {
                cut = index
            }
        }
        let head = cut.map { String(text[..<$0]) } ?? text
        hiddenLines = cut == nil ? 0 : lineBreaks + 1 - maxLines
        preview = head.count > maxCharacters ? String(head.prefix(maxCharacters)) : head
    }

    public var isCollapsible: Bool { preview.utf8.count < full.utf8.count }

    /// "Show 20 more lines", or "Show all" when only long lines are hidden; nil when there
    /// is nothing more.
    public var expandLabel: String? {
        guard isCollapsible else { return nil }
        guard hiddenLines > 0 else { return "Show all" }
        return "Show \(hiddenLines) more line\(hiddenLines == 1 ? "" : "s")"
    }
}
