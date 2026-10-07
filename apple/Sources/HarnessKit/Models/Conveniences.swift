import Foundation

/// How full a session's context window is, measured after each turn (D032).
public struct SessionContext: Codable, Sendable, Hashable {
    /// Percent of the limit used, 0 to 100.
    public var percent: Double
    public var used: Int
    public var limit: Int

    public init(percent: Double, used: Int, limit: Int) {
        self.percent = percent
        self.used = used
        self.limit = limit
    }

    /// Above this share the meter turns amber.
    public static let highPercent = 80.0

    /// The composer's quiet text, such as "context 41%".
    public var label: String { "context \(Int(percent.rounded()))%" }

    public var isHigh: Bool { percent > Self.highPercent }

    /// The numbers behind the meter, such as "82k of 200k tokens".
    public var detail: String {
        "\(UsageText.tokens(used)) of \(UsageText.tokens(limit)) tokens"
    }
}

/// A message sent while a turn ran, waiting to start the next one.
public struct QueuedMessage: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var text: String
    public var attachments: [Attachment]
    public var createdAt: Date

    public init(id: String, text: String, attachments: [Attachment] = [], createdAt: Date) {
        self.id = id
        self.text = text
        self.attachments = attachments
        self.createdAt = createdAt
    }

    enum CodingKeys: String, CodingKey {
        case id, text, attachments
        case createdAt = "created_at"
    }
}

/// The answer to `POST /api/sessions/{id}/messages`: the session, and the queued message
/// when the send waits for the running turn.
public struct SentMessage: Decodable, Sendable, Hashable {
    public var session: Session
    public var queuedMessage: QueuedMessage?

    public init(session: Session, queuedMessage: QueuedMessage? = nil) {
        self.session = session
        self.queuedMessage = queuedMessage
    }

    enum CodingKeys: String, CodingKey {
        case queuedMessage = "queued_message"
    }

    public init(from decoder: any Decoder) throws {
        session = try Session(from: decoder)
        queuedMessage = try decoder.container(keyedBy: CodingKeys.self)
            .decodeIfPresent(QueuedMessage.self, forKey: .queuedMessage)
    }
}

/// A command typed as "/name": built in, from the user's setup, or a skill.
public struct SlashCommand: Decodable, Sendable, Hashable, Identifiable {
    /// Without the leading slash.
    public var name: String
    public var description: String?
    public var argumentHint: String?

    public var id: String { name }

    public init(name: String, description: String? = nil, argumentHint: String? = nil) {
        self.name = name
        self.description = description
        self.argumentHint = argumentHint
    }

    enum CodingKeys: String, CodingKey {
        case name, description
        case argumentHint = "argument_hint"
    }
}

/// A subagent type the engine offers.
public struct AgentInfo: Decodable, Sendable, Hashable {
    public var name: String
    public var description: String?
}

public enum CommandSource: String, UnknownSafeEnum {
    /// The session's own runs.
    case session
    /// The repo's latest run, for chats that have not started.
    case repo
    /// No run reported commands yet.
    case none
    case unknown
}

/// A session's or repo's slash commands and agents, sorted by name.
public struct CommandList: Decodable, Sendable, Hashable {
    public var source: CommandSource
    public var commands: [SlashCommand]
    public var agents: [AgentInfo]
    public var updatedAt: Date?

    public init(
        source: CommandSource, commands: [SlashCommand], agents: [AgentInfo] = [],
        updatedAt: Date? = nil
    ) {
        self.source = source
        self.commands = commands
        self.agents = agents
        self.updatedAt = updatedAt
    }

    enum CodingKeys: String, CodingKey {
        case source, commands, agents
        case updatedAt = "updated_at"
    }
}

struct FileList: Decodable {
    var files: [String]
}

/// The plan Claude finished in plan mode, waiting for Approve plan or Keep planning.
public struct PlanRequest: Decodable, Sendable, Hashable {
    /// Markdown.
    public var plan: String
    public var toolUseID: String?

    enum CodingKeys: String, CodingKey {
        case plan
        case toolUseID = "tool_use_id"
    }
}
