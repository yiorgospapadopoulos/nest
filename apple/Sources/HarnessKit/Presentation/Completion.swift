import Foundation

/// The "/command" or "@path" token being typed at the caret, as Claude Code completes
/// them. Offsets count characters.
public struct CompletionTrigger: Sendable, Hashable {
    public enum Kind: String, Sendable, Hashable {
        case command, file
    }

    public let kind: Kind
    /// The token's span, from its "/" or "@" to the next whitespace.
    public let start: Int
    public let end: Int
    /// What was typed after the "/" or "@", up to the caret.
    public let query: String

    /// A slash command counts only as the first thing in the message; a mention starts a
    /// word anywhere.
    public static func at(_ text: String, caret: Int) -> CompletionTrigger? {
        let characters = Array(text)
        let caret = min(max(caret, 0), characters.count)
        let before = characters[..<caret]
        let wordStart = before.lastIndex(where: \.isWhitespace).map { $0 + 1 } ?? 0
        guard wordStart < caret else { return nil }
        let word = before[wordStart...]
        let end = characters[caret...].firstIndex(where: \.isWhitespace) ?? characters.count
        let query = String(word.dropFirst())
        if word.first == "/", wordStart == 0 {
            return CompletionTrigger(kind: .command, start: 0, end: end, query: query)
        }
        if word.first == "@" {
            return CompletionTrigger(kind: .file, start: wordStart, end: end, query: query)
        }
        return nil
    }

    /// The text with `choice` and one space in place of the token, and the caret after
    /// them; a space already after the token is reused rather than doubled.
    public func replacing(in text: String, with choice: String) -> (text: String, caret: Int) {
        let characters = Array(text)
        let head = String(characters[..<min(start, characters.count)]) + choice + " "
        var tail = characters[min(end, characters.count)...]
        if tail.first?.isWhitespace == true {
            tail = tail.dropFirst()
        }
        return (head + String(tail), head.count)
    }

    /// Identifies the token while it is typed, so Esc keeps its list closed.
    var anchor: String { "\(kind.rawValue):\(start)" }
}

/// One entry of the suggestion list above the composer.
public struct Completion: Sendable, Hashable, Identifiable {
    public let id: String
    /// "/review" or "src/app.ts".
    public let label: String
    /// The command's argument hint, such as "[file]".
    public let hint: String?
    public let detail: String?
    /// The composer's text and caret once this entry is picked.
    public let text: String
    public let caret: Int
}

/// The suggestions for the token at the caret.
public struct CompletionList: Sendable, Hashable {
    public let trigger: CompletionTrigger
    public let items: [Completion]

    public var title: String { trigger.kind == .command ? "Commands" : "Files" }

    /// Commands whose name starts with the query first, then those containing it.
    public static func commands(
        _ commands: [SlashCommand], for trigger: CompletionTrigger, in text: String
    ) -> CompletionList {
        let query = trigger.query.lowercased()
        let starts = commands.filter { $0.name.lowercased().hasPrefix(query) }
        let inside = commands.filter {
            !$0.name.lowercased().hasPrefix(query) && $0.name.lowercased().contains(query)
        }
        let items = (starts + inside).map { command in
            let result = trigger.replacing(in: text, with: "/\(command.name)")
            return Completion(
                id: command.name, label: "/\(command.name)", hint: command.argumentHint,
                detail: command.description, text: result.text, caret: result.caret)
        }
        return CompletionList(trigger: trigger, items: items)
    }

    /// The daemon's ranked paths, each inserted as "@path".
    public static func files(_ paths: [String], for trigger: CompletionTrigger, in text: String)
        -> CompletionList
    {
        let items = paths.map { path in
            let result = trigger.replacing(in: text, with: "@\(path)")
            return Completion(
                id: path, label: path, hint: nil, detail: nil, text: result.text,
                caret: result.caret)
        }
        return CompletionList(trigger: trigger, items: items)
    }
}

/// Which suggestion is highlighted, and whether Esc closed the list for the token being
/// typed. The highlight starts over whenever the query changes.
public struct CompletionSelection: Sendable, Hashable {
    private var key = ""
    private var index = 0
    private var dismissed: String?

    public init() {}

    /// The list shows: it has entries and Esc did not close it for this token.
    public func isOpen(_ list: CompletionList?) -> Bool {
        guard let list, !list.items.isEmpty else { return false }
        return dismissed != list.trigger.anchor
    }

    public func active(in list: CompletionList) -> Int {
        guard key == Self.key(list), !list.items.isEmpty else { return 0 }
        return index % list.items.count
    }

    /// Moves the highlight, wrapping around the ends.
    public mutating func move(_ delta: Int, in list: CompletionList) {
        guard !list.items.isEmpty else { return }
        let count = list.items.count
        index = ((active(in: list) + delta) % count + count) % count
        key = Self.key(list)
    }

    /// The highlighted entry.
    public func chosen(in list: CompletionList) -> Completion? {
        list.items.isEmpty ? nil : list.items[active(in: list)]
    }

    /// Esc: closed until the token is gone.
    public mutating func dismiss(_ list: CompletionList) {
        dismissed = list.trigger.anchor
    }

    /// Called as the text changes: a closed list opens again once its token is gone.
    public mutating func update(for trigger: CompletionTrigger?) {
        if dismissed != nil, dismissed != trigger?.anchor {
            dismissed = nil
        }
    }

    private static func key(_ list: CompletionList) -> String {
        "\(list.trigger.anchor):\(list.trigger.query)"
    }
}
