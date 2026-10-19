import Foundation

/// An artifact's page made safe to render: the content security policy goes in before
/// anything else, so the page runs its own inline scripts and pinned libraries from a few
/// public CDNs (B82), uses Google Fonts, and can reach nothing else.
public enum ArtifactHTML {
    /// The same string as the iPhone frame's policy.
    public static let policy =
        "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net/npm/ https://unpkg.com https://cdn.tailwindcss.com https://code.jquery.com; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com data:; img-src data: blob:; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-src 'none'; worker-src 'none'"
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

/// The Mac web view's content rule list, a second wall under the policy: every load is
/// blocked, then scripts from the policy's CDNs, Google Fonts stylesheets and their font
/// files are let through. Each url-filter anchors the scheme and the whole host, so a
/// look-alike host, plain http or a listed host in another URL's path does not match.
public enum ArtifactRules {
    /// WebKit caches a compiled list under its name; B79's list had another one.
    public static let identifier = "nest-artifact-cdn-v1"
    public static let json = #"""
        [
          {"trigger": {"url-filter": ".*"}, "action": {"type": "block"}},
          {"trigger": {"url-filter": "^https://cdnjs\\.cloudflare\\.com/", "resource-type": ["script"]}, "action": {"type": "ignore-previous-rules"}},
          {"trigger": {"url-filter": "^https://cdn\\.jsdelivr\\.net/npm/", "resource-type": ["script"]}, "action": {"type": "ignore-previous-rules"}},
          {"trigger": {"url-filter": "^https://unpkg\\.com/", "resource-type": ["script"]}, "action": {"type": "ignore-previous-rules"}},
          {"trigger": {"url-filter": "^https://cdn\\.tailwindcss\\.com/", "resource-type": ["script"]}, "action": {"type": "ignore-previous-rules"}},
          {"trigger": {"url-filter": "^https://code\\.jquery\\.com/", "resource-type": ["script"]}, "action": {"type": "ignore-previous-rules"}},
          {"trigger": {"url-filter": "^https://fonts\\.googleapis\\.com/", "resource-type": ["style-sheet"]}, "action": {"type": "ignore-previous-rules"}},
          {"trigger": {"url-filter": "^https://fonts\\.gstatic\\.com/", "resource-type": ["font"]}, "action": {"type": "ignore-previous-rules"}}
        ]
        """#
}

/// Save as file: the title as a file name, with the kind's extension.
public enum ArtifactFile {
    static let longest = 120

    public static func name(title: String, kind: ArtifactKind) -> String {
        name(title: title, fileExtension: fileExtension(kind))
    }

    /// Export PDF's file name.
    public static func pdfName(title: String) -> String {
        name(title: title, fileExtension: "pdf")
    }

    private static func name(title: String, fileExtension: String) -> String {
        let cleaned = clean(title)
        return "\(cleaned.isEmpty ? "Artifact" : cleaned).\(fileExtension)"
    }

    /// The text without characters a file name may not hold, its spaces folded, at most
    /// 120 characters; empty when nothing usable is left.
    static func clean(_ text: String) -> String {
        let forbidden = CharacterSet(charactersIn: "/\\:*?\"<>|").union(.controlCharacters)
        let cleaned = String(
            text.unicodeScalars.map { forbidden.contains($0) ? " " : Character($0) }
        )
        .split(whereSeparator: \.isWhitespace).joined(separator: " ")
        .trimmingCharacters(in: CharacterSet(charactersIn: ". "))
        return String(cleaned.prefix(longest))
    }

    /// What Save as file writes: the content as saved, or for a multi-file html page the
    /// built page, which holds its files.
    public static func savedText(_ content: ArtifactContent) -> String {
        content.kind == .html && !content.files.isEmpty ? content.page : content.content
    }

    public static func fileExtension(_ kind: ArtifactKind) -> String {
        switch kind {
        case .markdown, .slides, .document: "md"
        case .html: "html"
        case .design, .designSystem: "json"
        case .unknown: "txt"
        }
    }
}

/// Export PDF's paper (B88), in points: slides one 16:9 stage per landscape page with no
/// margin, as the template's print CSS lays them out; documents A4 portrait. Other kinds
/// have no export.
public struct ArtifactPrint: Equatable, Sendable {
    public let width: Double
    public let height: Double
    public let landscape: Bool
    public let margin: Double

    public static func layout(_ kind: ArtifactKind) -> ArtifactPrint? {
        switch kind {
        case .slides: ArtifactPrint(width: 960, height: 540, landscape: true, margin: 0)
        case .document: ArtifactPrint(width: 595, height: 842, landscape: false, margin: 36)
        case .markdown, .html, .design, .designSystem, .unknown: nil
        }
    }
}

extension ArtifactKind {
    /// The SF Symbol the views show for the kind.
    public var symbol: String {
        switch self {
        case .markdown, .unknown: "doc.richtext"
        case .html: "chevron.left.forwardslash.chevron.right"
        case .slides: "play.rectangle"
        case .document: "doc.text"
        case .design: "rectangle.3.group"
        case .designSystem: "swatchpalette"
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
        case .slides: "Slides"
        case .document, .unknown: "Document"
        case .design: "Design"
        case .designSystem: "Design system"
        }
    }

    /// The reader's line under the title: the kind, who made it, and when this version
    /// was saved, "Edited by you" when the user saved it.
    /// What the page stored follows, when it stored anything, then today's asks once it
    /// asked Claude.
    public static func line(
        _ artifact: Artifact, author: ArtifactAuthor, saved: Date, now: Date, stored: Int = 0,
        asks: ArtifactAskCount? = nil
    ) -> String {
        let made = author == .user ? "Edited by you" : "saved"
        var parts = [kind(artifact.kind), origin(artifact), "\(made) \(when(saved, now: now))"]
        if stored > 0 {
            parts.append("\(StorageText.bytes(stored)) stored")
        }
        if let asks {
            parts.append(asks.text)
        }
        return parts.joined(separator: " · ")
    }

    /// The reader's quiet indicator while a page's ask runs.
    public static let asking = "Asking Claude\u{2026}"

    /// "Version 2 of 3".
    public static func version(_ version: Int, of count: Int) -> String {
        "Version \(version) of \(count)"
    }

    /// A transcript card's state: "Saved" for a new artifact, "Version 3" for an update.
    public static func cardState(_ card: ArtifactCard) -> String {
        card.action == .updated || card.action == .edited ? "Version \(card.version)" : "Saved"
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
