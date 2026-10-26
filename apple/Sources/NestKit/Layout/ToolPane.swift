import Foundation

/// What a workspace pane shows.
public enum PaneKind: String, Codable, Sendable, Hashable {
    /// A Nest chat, a new chat's draft or a Claude Code chat.
    case chat
    case terminal
    case browser
    /// A folder's run output (B108).
    case run

    /// The kind of an open pane, from its id: tool panes carry their kind as a prefix.
    public init(paneID: String) {
        if paneID.hasPrefix(Self.terminal.idPrefix) {
            self = .terminal
        } else if paneID.hasPrefix(Self.browser.idPrefix) {
            self = .browser
        } else if paneID.hasPrefix(Self.run.idPrefix) {
            self = .run
        } else {
            self = .chat
        }
    }

    var idPrefix: String { "\(rawValue):" }
}

/// A terminal, browser or run output pane of a project's workspace. It takes a workspace
/// slot like a chat and is remembered per project: a terminal reopens a fresh shell in its
/// folder, a browser its page, a run output pane its folder's current output.
public struct ToolPane: Codable, Sendable, Hashable, Identifiable {
    public let id: String
    public let kind: PaneKind
    /// The folder a terminal's shell starts in, or whose run an output pane shows.
    public var folder: String?
    /// The address a browser shows; nil before the first page.
    public var url: String?
    /// The chat a run output pane opened from, which the run's routes go through.
    public var session: String?

    public init(
        id: String, kind: PaneKind, folder: String? = nil, url: String? = nil,
        session: String? = nil
    ) {
        self.id = id
        self.kind = kind
        self.folder = folder
        self.url = url
        self.session = session
    }

    /// A new terminal pane whose shell starts in `folder`.
    public static func terminal(in folder: String) -> ToolPane {
        ToolPane(id: newID(.terminal), kind: .terminal, folder: normalized(folder))
    }

    /// A new browser pane, empty or showing `url`.
    public static func browser(url: String? = nil) -> ToolPane {
        ToolPane(id: newID(.browser), kind: .browser, url: url)
    }

    /// A new pane showing the run of `folder`, as the daemon names it, through `session`.
    public static func run(folder: String, session: String) -> ToolPane {
        ToolPane(id: newID(.run), kind: .run, folder: folder, session: session)
    }

    /// A unique pane id that tells the pane's kind.
    static func newID(_ kind: PaneKind) -> String {
        kind.idPrefix + UUID().uuidString.lowercased()
    }

    /// Folders compare without a trailing slash, `.` or `..` parts.
    static func normalized(_ folder: String) -> String {
        (folder as NSString).standardizingPath
    }

    /// The header's name: a terminal's or run's folder name, a browser's host.
    public var title: String {
        switch kind {
        case .terminal, .run:
            let name = folder.map { ($0 as NSString).lastPathComponent } ?? ""
            return name.isEmpty ? "Terminal" : name
        case .browser, .chat:
            return url.flatMap { URL(string: $0)?.host() } ?? "Browser"
        }
    }
}

/// The text typed into a shell to run a command from a chat.
public enum TerminalInput {
    /// Marks that reorder text on screen, so it would read differently from what runs.
    static let directionMarks: Set<Unicode.Scalar> = [
        "\u{061C}", "\u{200E}", "\u{200F}", "\u{202A}", "\u{202B}", "\u{202C}", "\u{202D}",
        "\u{202E}", "\u{2066}", "\u{2067}", "\u{2068}", "\u{2069}",
    ]

    /// The command followed by the newline that runs it, without control characters
    /// (tabs aside) or direction marks. Nil when nothing is left, or when it spans lines:
    /// each line would run as a command of its own.
    public static func line(for command: String) -> String? {
        let kept = command.unicodeScalars.filter { scalar in
            scalar == "\t" || Character(scalar).isNewline
                || scalar.properties.generalCategory != .control
                    && !directionMarks.contains(scalar)
        }
        let text = String(String.UnicodeScalarView(kept))
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !text.contains(where: \.isNewline) else { return nil }
        return text + "\n"
    }
}
