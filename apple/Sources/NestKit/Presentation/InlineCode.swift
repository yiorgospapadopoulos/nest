import Foundation

/// A run of a short hint, such as "Run `codex login` with a ChatGPT plan.": code between
/// backticks, or plain text (B91). Spaces inside code are plain, so a view drawing code in
/// mono keeps the text's own word gap.
public struct InlineCode: Sendable, Hashable {
    public var text: String
    public var isCode: Bool

    public init(text: String, isCode: Bool) {
        self.text = text
        self.isCode = isCode
    }

    /// The runs in order, without the backticks; a tick without its pair stays as text.
    public static func parts(_ text: String) -> [InlineCode] {
        var parts: [InlineCode] = []
        let pieces = text.components(separatedBy: "`")
        // An even count of pieces means an odd count of ticks: the last one is unpaired.
        let unpaired = pieces.count % 2 == 0
        let paired = unpaired ? Array(pieces.dropLast()) : pieces
        for (index, piece) in paired.enumerated() {
            if index % 2 == 0 {
                append(piece, isCode: false, to: &parts)
            } else {
                for (wordIndex, word) in piece.components(separatedBy: " ").enumerated() {
                    if wordIndex > 0 {
                        append(" ", isCode: false, to: &parts)
                    }
                    append(word, isCode: true, to: &parts)
                }
            }
        }
        if unpaired {
            append("`" + pieces[pieces.count - 1], isCode: false, to: &parts)
        }
        return parts
    }

    /// Joins plain runs that meet; drops empty ones.
    private static func append(_ text: String, isCode: Bool, to parts: inout [InlineCode]) {
        guard !text.isEmpty else { return }
        if let last = parts.last, !last.isCode, !isCode {
            parts[parts.count - 1].text += text
        } else {
            parts.append(InlineCode(text: text, isCode: isCode))
        }
    }
}
