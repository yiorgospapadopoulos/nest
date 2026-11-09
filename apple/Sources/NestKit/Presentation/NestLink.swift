import Foundation

/// A `nest://chat/<id>?project=<name>` link, which the `nest open` command opens (B151).
public struct NestLink: Sendable, Hashable {
    public let chat: String
    public let project: String

    /// Nil for any other link, or one whose id or project could not be Nest's.
    public init?(_ url: URL) {
        guard url.scheme == "nest", url.host() == "chat",
            let parts = URLComponents(url: url, resolvingAgainstBaseURL: false)
        else { return nil }
        let chat = String(parts.path.dropFirst())
        let project = parts.queryItems?.first { $0.name == "project" }?.value ?? ""
        guard Self.isID(chat), !project.isEmpty, project.count <= 200, !project.contains("/")
        else { return nil }
        self.chat = chat
        self.project = project
    }

    private static func isID(_ text: String) -> Bool {
        !text.isEmpty && text.count <= 64
            && text.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-") }
    }
}
