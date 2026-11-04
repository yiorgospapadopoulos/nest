import Foundation

extension NSAttributedString.Key {
    /// Text that is shown but left out when copying, such as diff line numbers.
    public static let notCopied = NSAttributedString.Key("nest.notCopied")
    /// A `String` copied in place of the range: a table cell's line break copies as a tab, so
    /// a row pastes as one line.
    public static let copiedAs = NSAttributedString.Key("nest.copiedAs")
}

/// What a message's text puts on the pasteboard when it holds text that copies differently
/// from how it shows.
public enum MessageCopy {
    /// Whether copying `text` needs `text(of:in:)`.
    public static func applies(to text: NSAttributedString) -> Bool {
        let all = NSRange(location: 0, length: text.length)
        return [NSAttributedString.Key.notCopied, .copiedAs].contains { key in
            var found = false
            text.enumerateAttribute(key, in: all) { value, _, stop in
                if value != nil {
                    found = true
                    stop.pointee = true
                }
            }
            return found
        }
    }

    public static func text(of text: NSAttributedString, in ranges: [NSRange]) -> String {
        var copied = ""
        for range in ranges {
            text.enumerateAttributes(in: range) { attributes, part, _ in
                if attributes[.notCopied] != nil {
                    return
                }
                if let replacement = attributes[.copiedAs] as? String {
                    copied += replacement
                } else {
                    copied += text.attributedSubstring(from: part).string
                }
            }
        }
        return copied
    }
}
