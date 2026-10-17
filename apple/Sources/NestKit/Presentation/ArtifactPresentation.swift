import Foundation

/// An HTML artifact made safe to render: the content security policy goes in before
/// anything else, so the page can load nothing and run only its own inline scripts.
public enum ArtifactHTML {
    public static let policy =
        "default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'"
    public static let meta = #"<meta http-equiv="Content-Security-Policy" content="\#(policy)">"#

    /// The document with the policy's meta tag after its leading doctype and comments,
    /// ahead of any element. The HTML parser then starts the head with it whatever
    /// follows: a later `<html>` only adds its attributes and a later `<head>` is
    /// ignored, so no comment or stray tag can keep it out of the head.
    public static func sandboxed(_ html: String) -> String {
        var index = html.startIndex
        while true {
            index =
                html[index...].firstIndex { !$0.isWhitespace && $0 != "\u{FEFF}" }
                ?? html.endIndex
            let rest = html[index...]
            if rest.hasPrefix("<!--"), let end = rest.range(of: "-->") {
                index = end.upperBound
            } else if rest.prefix(9).lowercased() == "<!doctype", let end = rest.firstIndex(of: ">")
            {
                index = html.index(after: end)
            } else {
                break
            }
        }
        return String(html[..<index]) + meta + String(html[index...])
    }
}

/// Save as file: the title as a file name, with the kind's extension.
public enum ArtifactFile {
    static let longest = 120

    public static func name(title: String, kind: ArtifactKind) -> String {
        let forbidden = CharacterSet(charactersIn: "/\\:*?\"<>|").union(.controlCharacters)
        let cleaned = String(
            title.unicodeScalars.map { forbidden.contains($0) ? " " : Character($0) }
        )
        .split(whereSeparator: \.isWhitespace).joined(separator: " ")
        .trimmingCharacters(in: CharacterSet(charactersIn: ". "))
        let base = cleaned.isEmpty ? "Artifact" : String(cleaned.prefix(longest))
        return "\(base).\(fileExtension(kind))"
    }

    public static func fileExtension(_ kind: ArtifactKind) -> String {
        switch kind {
        case .markdown: "md"
        case .html: "html"
        case .unknown: "txt"
        }
    }
}

/// The words the artifact views use.
public enum ArtifactText {
    /// Who made it: the pixie, the chat, or "Deleted chat".
    public static func origin(_ artifact: Artifact) -> String {
        if let pixie = artifact.pixieName {
            return pixie
        }
        guard !artifact.chatDeleted, let title = artifact.chatTitle else { return "Deleted chat" }
        return title
    }

    /// "now" or "9m ago".
    public static func when(_ date: Date, now: Date) -> String {
        let elapsed = Elapsed.short(from: date, to: now)
        return elapsed == "now" ? elapsed : "\(elapsed) ago"
    }

    public static func kind(_ kind: ArtifactKind) -> String {
        switch kind {
        case .markdown: "Markdown"
        case .html: "HTML"
        case .unknown: "Document"
        }
    }

    /// "Version 2 of 3".
    public static func version(_ version: Int, of count: Int) -> String {
        "Version \(version) of \(count)"
    }

    /// A transcript card's state: "Saved" for a new artifact, "Version 3" for an update.
    public static func cardState(_ card: ArtifactCard) -> String {
        card.action == .updated ? "Version \(card.version)" : "Saved"
    }

    public static let deleted = "Deleted"

    /// The Artifacts switch item's count; nil hides the badge.
    public static func badge(_ unseen: Int) -> String? {
        unseen <= 0 ? nil : unseen > 99 ? "99+" : "\(unseen)"
    }

    /// An artifact tool call's line while it runs or after it failed.
    public static func toolTitle(_ tool: String) -> String {
        tool == ArtifactTools.update ? "Update artifact" : "Save artifact"
    }

    /// What the list says when the scope holds none.
    public static func empty(_ query: ArtifactQuery) -> String {
        switch query {
        case .chat: "This chat has saved no artifacts yet."
        case .project: "No chat in this project has saved an artifact yet."
        case .pixie: "This pixie has saved no artifacts yet."
        case .pixies: "No pixie has saved an artifact yet."
        }
    }
}

/// The agent's tools that save artifacts, by their names in the transcript.
public enum ArtifactTools {
    public static let create = "mcp__nest__create_artifact"
    public static let update = "mcp__nest__update_artifact"

    public static func contains(_ tool: String) -> Bool {
        tool == create || tool == update
    }
}
