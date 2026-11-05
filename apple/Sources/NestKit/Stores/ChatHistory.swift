import Foundation

/// What the Mac reads from a chat's messages, the transcript itself being a web page
/// (D150): the last message for up arrow and Esc Esc, and the files it names for
/// dictation's vocabulary. Read from the daemon when asked, so a rewound message is gone.
public struct ChatHistory: Sendable, Equatable {
    /// The event of the user's latest message.
    public private(set) var lastMessage: Int?
    /// The text of the user's latest message that has any.
    public private(set) var lastText: String?
    /// File names the chat mentions, newest first.
    public private(set) var files: [String] = []

    public init(events: [Event] = []) {
        for event in events {
            read(event)
        }
    }

    public static func load(_ chat: String, api: any NestAPI) async throws -> ChatHistory {
        ChatHistory(events: try await api.sessionEvents(chat, after: 0))
    }

    private mutating func read(_ event: Event) {
        switch event.body {
        case .userMessage(let message):
            guard let text = Self.ownText(of: message) else { return }
            lastMessage = event.id
            if !text.isEmpty {
                lastText = text
            }
            mention(DictationVocabulary.fileNames(in: text))
        case .message(let message) where message.parentToolUseID == nil:
            for block in message.blocks {
                switch block {
                case .text(let text):
                    mention(DictationVocabulary.fileNames(in: text))
                case .toolUse(_, _, let input):
                    let paths = ["file_path", "path", "notebook_path"].compactMap {
                        input[$0]?.stringValue
                    }
                    mention(paths.map { ($0 as NSString).lastPathComponent })
                default:
                    break
                }
            }
        default:
            break
        }
    }

    private mutating func mention(_ names: [String]) {
        files.insert(contentsOf: names.reversed().filter { !$0.isEmpty }, at: 0)
    }

    /// What the user wrote; nil for a message Nest sent for someone else.
    private static func ownText(of message: UserMessage) -> String? {
        if let origin = message.origin,
            [.reportBack, .report, .limitResume, .autopilot, .pixieResult].contains(origin)
        {
            return nil
        }
        if let github = GitHubMessage.of(message) {
            return github.own
        }
        let split = BashBlocks.split(message.text)
        let onlyCommands = !split.blocks.isEmpty && split.rest.isEmpty
        return onlyCommands && message.attachments.isEmpty ? nil : split.rest
    }
}
