import Foundation

/// The Mac app's side of a transcript page (B124, D150): what the page may ask, what it is
/// told, where it may go and what it may load. The page shows agent output and holds
/// the device token, so its requests are checked here before anything runs, it answers only
/// to the daemon's own origin, and the only network it can reach is the daemon.
public enum WebPaneBridge {
    /// The web view's script message handler name.
    public static let handlerName = "nestPane"
    /// The event the page listens to for `Command`s.
    public static let eventName = "nest-pane"
    static let longestText = 1024 * 1024
    static let longestPath = 4096
    static let longestID = 128
    /// Bytes of a saved attachment, as base64: the 24 MiB an artifact's Save file allows.
    static let longestFile = 32 * 1024 * 1024

    public enum MessageAction: String, Sendable {
        case edit, rewind, fork
    }

    /// A checked request from the page.
    public enum Message: Equatable, Sendable {
        /// The daemon's address and the token, the only answer the page gets.
        case daemon
        case ready
        case openLink(URL)
        case openFile(String)
        case openChat(String)
        case openPixie(String)
        case copy(String)
        case toast(text: String, failed: Bool)
        case teamWork(String)
        case pixieWork(String)
        case message(MessageAction, event: Int)
        case artifact(id: String, version: Int?)
        case terminal(String)
        case image(String)
        case saveFile(name: String, data: Data)
    }

    /// Reads a message body from the page; anything else in any shape is nil.
    public static func parse(_ body: Any) -> Message? {
        guard let fields = body as? [String: Any], let kind = fields["kind"] as? String else {
            return nil
        }
        func text(_ key: String, _ longest: Int) -> String? {
            guard let value = fields[key] as? String, !value.isEmpty, value.utf8.count <= longest
            else { return nil }
            return value
        }
        func id(_ key: String) -> String? { text(key, longestID) }
        switch kind {
        case "daemon": return .daemon
        case "ready": return .ready
        case "openExternal":
            return text("url", longestPath).flatMap(SafeLink.url).map(Message.openLink)
        case "openFile": return text("path", longestPath).map(Message.openFile)
        case "open":
            let target = fields["target"] as? [String: Any]
            if let chat = target?["chat"] as? String, chat.utf8.count <= longestID {
                return .openChat(chat)
            }
            if let pixie = target?["pixie"] as? String, pixie.utf8.count <= longestID {
                return .openPixie(pixie)
            }
            return nil
        case "copy": return text("text", longestText).map(Message.copy)
        case "toast":
            return text("text", longestPath).map {
                .toast(text: $0, failed: fields["tone"] as? String == "error")
            }
        case "teamWork": return id("team").map(Message.teamWork)
        case "pixieWork": return id("pixie").map(Message.pixieWork)
        case "message":
            guard let action = (fields["action"] as? String).flatMap(MessageAction.init),
                let event = fields["event"] as? Int
            else { return nil }
            return .message(action, event: event)
        case "artifact":
            return id("id").map { .artifact(id: $0, version: fields["version"] as? Int) }
        case "terminal": return text("command", longestPath).map(Message.terminal)
        case "image": return id("id").map(Message.image)
        case "saveFile":
            guard let name = text("name", longestPath),
                let data = text("base64", longestFile).flatMap({ Data(base64Encoded: $0) })
            else { return nil }
            return .saveFile(name: (name as NSString).lastPathComponent, data: data)
        default: return nil
        }
    }

    /// What the app tells a page.
    public enum Command: Equatable, Sendable {
        case dimmed(Bool)
        case focus(event: Int)
        case appearance(dark: Bool, accent: String)
        case bash([BashStore.Row])

        /// Commands of a kind replace each other while the page is not ready.
        public var kind: String {
            switch self {
            case .dimmed: "dimmed"
            case .focus: "focus"
            case .appearance: "appearance"
            case .bash: "bash"
            }
        }

        var payload: [String: Any] {
            switch self {
            case .dimmed(let value): ["kind": kind, "value": value]
            case .focus(let event): ["kind": kind, "event": event]
            case .appearance(let dark, let accent):
                ["kind": kind, "theme": dark ? "dark" : "light", "accent": accent]
            case .bash(let rows):
                ["kind": kind, "runs": rows.enumerated().map(Self.run)]
            }
        }

        /// A row in the shape of the page's `BashRun`.
        private static func run(_ index: Int, _ row: BashStore.Row) -> [String: Any] {
            var fields: [String: Any] = [
                "id": index, "command": row.command, "error": row.failure ?? NSNull(),
                "result": NSNull(),
            ]
            if let run = row.run {
                fields["result"] = [
                    "command": row.command, "exit_code": run.exitCode ?? NSNull(),
                    "output": run.output, "truncated": run.truncated, "timed_out": run.timedOut,
                    "context": "",
                ]
            }
            return fields
        }
    }

    /// The script that delivers a command. Everything in it is JSON, so a command's text
    /// cannot become code.
    public static func script(_ command: Command) -> String? {
        guard JSONSerialization.isValidJSONObject(command.payload),
            let data = try? JSONSerialization.data(withJSONObject: command.payload),
            let json = String(data: data, encoding: .utf8)
        else { return nil }
        return "window.dispatchEvent(new CustomEvent('\(eventName)', { detail: \(json) }))"
    }

    /// What a page shows.
    public enum Target: Hashable, Sendable {
        /// A pane's chat: a Nest chat, or a Claude Code chat by its pane id.
        case pane(String)
        /// A subagent's, pixie's or team's work in a chat.
        case work(WorkTarget)
        /// A chat opened only to time it, apart from any pane showing it.
        case probe(String)

        /// The Nest chat it belongs to.
        public var chat: String {
            switch self {
            case .pane(let chat), .probe(let chat): chat
            case .work(let work): work.session
            }
        }

        var query: [URLQueryItem] {
            func items(_ pairs: (String, String)...) -> [URLQueryItem] {
                pairs.map { URLQueryItem(name: $0.0, value: $0.1) }
            }
            switch self {
            case .pane(let pane), .probe(let pane):
                if let claude = ClaudeChat.chatID(ofPane: pane) {
                    return items(("claude", claude))
                }
                return items(("chat", pane))
            case .work(.subagent(let session, let call)):
                return items(("session", session), ("call", call))
            case .work(.pixie(let session, let pixie)):
                return items(("session", session), ("pixie", pixie))
            case .work(.team(let session, let team, _)):
                return items(("session", session), ("team", team))
            }
        }
    }

    /// The page for a target.
    public static func address(base: URL, target: Target) -> URL? {
        var parts = URLComponents(
            url: base.appending(path: "desktop.html"), resolvingAgainstBaseURL: false)
        parts?.queryItems = [URLQueryItem(name: "view", value: "transcript")] + target.query
        return parts?.url
    }

    public enum Navigation: Equatable, Sendable {
        case stay
        case openOutside(URL)
        case cancel
    }

    /// Where a navigation in the page leads: the daemon's page stays, a click on a web or
    /// mail link leaves for the browser, and nothing else happens.
    public static func navigation(to url: URL?, base: URL, linkClick: Bool) -> Navigation {
        guard let url else { return .cancel }
        if !linkClick, isDaemon(url, base: base) {
            return .stay
        }
        return SafeLink.url(url.absoluteString).map(Navigation.openOutside) ?? .cancel
    }

    /// Whether `url` is on the daemon's origin.
    public static func isDaemon(_ url: URL, base: URL) -> Bool {
        isDaemon(scheme: url.scheme, host: url.host, port: url.port, base: base)
    }

    /// Whether an origin is the daemon's; a port of nil or 0 is the scheme's default.
    public static func isDaemon(scheme: String?, host: String?, port: Int?, base: URL) -> Bool {
        func standard(_ port: Int?, _ scheme: String?) -> Int {
            if let port, port != 0 { return port }
            return scheme?.lowercased() == "https" ? 443 : 80
        }
        return scheme?.lowercased() == base.scheme?.lowercased()
            && host?.lowercased() == base.host?.lowercased()
            && standard(port, scheme) == standard(base.port, base.scheme)
    }

    /// The stored rule list of a daemon, the same at every launch so that lists do not pile
    /// up in WebKit's store.
    public static func rulesIdentifier(base: URL) -> String {
        "nest-web-pane-" + base.absoluteString.replacing(/[^A-Za-z0-9]+/) { _ in "-" }
    }

    /// A content rule list that blocks every load but the daemon's own, sockets included.
    public static func contentRules(base: URL) -> String {
        let origin = String(base.absoluteString.trimmingPrefix(/https?:\/\//))
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let escaped = origin.replacing(/[.+*?^$()\[\]{}|\\]/) { "\\\($0.output)" }
        let secure = base.scheme?.lowercased() == "https"
        let allowed = [
            (secure ? "https" : "http") + "://" + escaped + "/",
            (secure ? "wss" : "ws") + "://" + escaped + "/", "blob:", "data:",
        ]
        let block: [String: Any] = [
            "trigger": ["url-filter": ".*"], "action": ["type": "block"],
        ]
        let rules =
            [block]
            + allowed.map {
                [
                    "trigger": ["url-filter": "^" + $0],
                    "action": ["type": "ignore-previous-rules"],
                ]
            }
        let data = (try? JSONSerialization.data(withJSONObject: rules)) ?? Data("[]".utf8)
        return String(data: data, encoding: .utf8) ?? "[]"
    }
}
