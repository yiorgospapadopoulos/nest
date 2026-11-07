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

    /// A page the daemon sends for the user to open, such as a check's fix (B130): https only.
    public static func web(_ text: String) -> URL? {
        guard let url = URL(string: text), url.scheme?.lowercased() == "https", url.host != nil
        else { return nil }
        return url
    }

    /// The bug report's new issue opens on GitHub only, whatever address came back with it.
    public static func githubIssue(_ text: String) -> URL? {
        guard let url = web(text), url.host?.lowercased() == "github.com" else { return nil }
        return url
    }
}
