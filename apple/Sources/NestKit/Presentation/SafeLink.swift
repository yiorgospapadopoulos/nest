import Foundation

/// The links the app opens: web pages and mail. A `file:` link could run a program (a
/// `.command` file opens in Terminal) and other schemes launch apps, so those stay text
/// (audit SEC-03; the iPhone allows only web links).
public enum SafeLink {
    static let schemes: Set<String> = ["http", "https", "mailto"]

    public static func allows(_ url: URL) -> Bool {
        url.scheme.map { schemes.contains($0.lowercased()) } ?? false
    }

    /// The text as a link the app may open, else nil.
    public static func url(_ text: String) -> URL? {
        URL(string: text).flatMap { allows($0) ? $0 : nil }
    }
}
