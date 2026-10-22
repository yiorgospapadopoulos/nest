import Foundation

/// How well a local model uses tools, as the daemon judges it from the server's word, its
/// size and its context (B106).
public enum LocalToolUse: String, UnknownSafeEnum {
    case good
    case weak
    /// The server says the model has no tool use.
    case noTools = "none"
    case unknown
}

/// An app that serves local models and that Nest can start (B106).
public enum LocalApp: String, Codable, Sendable, Hashable, CaseIterable {
    case lmstudio
    case ollama

    /// The app named by a server's label, such as "LM Studio".
    public init?(label: String?) {
        guard let app = Self.allCases.first(where: { $0.title == label }) else { return nil }
        self = app
    }

    /// The app's own name.
    public var title: String {
        switch self {
        case .lmstudio: "LM Studio"
        case .ollama: "Ollama"
        }
    }
}

/// A local model added like an account (B106): a model of a server on this Mac or the
/// network. Chats name it as `local:<id>`.
public struct LocalModel: Codable, Sendable, Hashable, Identifiable {
    public static let prefix = "local:"

    public var id: String
    public var serverID: String
    /// The server's own id for the model.
    public var model: String
    public var name: String
    /// As typed, such as "localhost:1234".
    public var address: String
    /// The serving app's label, such as "LM Studio"; nil when unknown.
    public var app: String?
    /// In tokens; nil when the server does not say.
    public var context: Int?
    public var tools: LocalToolUse
    /// One plain sentence on why it is weak at tools.
    public var weakReason: String?
    public var vision: Bool
    public var thinking: Bool
    /// The server answers now.
    public var running: Bool
    public var hasKey: Bool
    /// One sentence when the model needs more of this Mac's memory than is safe; nil when
    /// fine, and from daemons before it.
    public var memoryWarning: String?

    public init(
        id: String, serverID: String, model: String, name: String, address: String,
        app: String? = nil, context: Int? = nil, tools: LocalToolUse = .good,
        weakReason: String? = nil, vision: Bool = false, thinking: Bool = false,
        running: Bool = true, hasKey: Bool = false, memoryWarning: String? = nil
    ) {
        self.id = id
        self.serverID = serverID
        self.model = model
        self.name = name
        self.address = address
        self.app = app
        self.context = context
        self.tools = tools
        self.weakReason = weakReason
        self.vision = vision
        self.thinking = thinking
        self.running = running
        self.hasKey = hasKey
        self.memoryWarning = memoryWarning
    }

    enum CodingKeys: String, CodingKey {
        case id, model, name, address, app, context, tools, vision, thinking, running
        case serverID = "server_id"
        case weakReason = "weak_reason"
        case hasKey = "has_key"
        case memoryWarning = "memory_warning"
    }

    /// What a chat's `model` holds for it.
    public var value: String { Self.prefix + id }

    /// The app Nest can start for its server, when it knows it.
    public var startApp: LocalApp? { LocalApp(label: app) }

    /// Weak at tools or without them: the chat warns until dismissed.
    public var isWeak: Bool { tools == .weak || tools == .noTools }

    /// Whether a chat's model value names a local model.
    public static func isLocal(_ value: String?) -> Bool {
        value?.hasPrefix(prefix) == true
    }
}

/// `GET /api/local/models`: the added models, the engine new local chats run on and
/// whether the user chose local models only.
public struct LocalModelList: Codable, Sendable, Hashable {
    public var models: [LocalModel]
    /// "claude" or "codex".
    public var engine: String
    public var localOnly: Bool

    public init(models: [LocalModel], engine: String = ProviderInfo.claude, localOnly: Bool = false)
    {
        self.models = models
        self.engine = engine
        self.localOnly = localOnly
    }

    enum CodingKeys: String, CodingKey {
        case models, engine
        case localOnly = "local_only"
    }
}

/// A model a server offers, found on this Mac or at an address.
public struct FoundModel: Codable, Sendable, Hashable, Identifiable {
    public var address: String
    public var app: String?
    public var model: String
    public var name: String
    public var context: Int?
    public var tools: LocalToolUse
    public var weakReason: String?
    public var vision: Bool
    public var thinking: Bool
    /// Already added.
    public var added: Bool
    /// One sentence when the model needs more of this Mac's memory than is safe.
    public var memoryWarning: String?

    public init(
        address: String, app: String? = nil, model: String, name: String, context: Int? = nil,
        tools: LocalToolUse = .good, weakReason: String? = nil, vision: Bool = false,
        thinking: Bool = false, added: Bool = false, memoryWarning: String? = nil
    ) {
        self.address = address
        self.app = app
        self.model = model
        self.name = name
        self.context = context
        self.tools = tools
        self.weakReason = weakReason
        self.vision = vision
        self.thinking = thinking
        self.added = added
        self.memoryWarning = memoryWarning
    }

    enum CodingKeys: String, CodingKey {
        case address, app, model, name, context, tools, vision, thinking, added
        case weakReason = "weak_reason"
        case memoryWarning = "memory_warning"
    }

    public var id: String { "\(address)/\(model)" }
}

/// A model in a model folder whose server is not running.
public struct DownloadedModel: Codable, Sendable, Hashable, Identifiable {
    public var name: String
    /// Where it was found, such as "Ollama models folder".
    public var source: String
    public var path: String
    /// What to do to use it, such as "start Ollama to use it".
    public var hint: String
    /// The app Nest can start for it.
    public var start: LocalApp?

    public init(name: String, source: String, path: String, hint: String, start: LocalApp?) {
        self.name = name
        self.source = source
        self.path = path
        self.hint = hint
        self.start = start
    }

    public var id: String { path }
}

/// `GET /api/local/find`: what runs now and what waits in model folders.
public struct LocalFind: Codable, Sendable, Hashable {
    public var running: [FoundModel]
    public var downloaded: [DownloadedModel]

    public init(running: [FoundModel], downloaded: [DownloadedModel]) {
        self.running = running
        self.downloaded = downloaded
    }
}

/// The APIs a server answers.
public struct LocalServerInfo: Codable, Sendable, Hashable {
    public var address: String
    public var app: String?
    /// Anthropic Messages.
    public var messages: Bool
    /// OpenAI Responses.
    public var responses: Bool
    /// OpenAI Chat Completions, which Nest's translator turns into either.
    public var chat: Bool

    public init(address: String, app: String?, messages: Bool, responses: Bool, chat: Bool) {
        self.address = address
        self.app = app
        self.messages = messages
        self.responses = responses
        self.chat = chat
    }

    /// Claude Code needs Messages, or Chat Completions through the translator.
    public var worksWithClaude: Bool { messages || chat }
    /// Codex needs Responses, or Chat Completions through the translator.
    public var worksWithCodex: Bool { responses || chat }
}

/// Why checking an address failed.
public enum LocalCheckError: String, UnknownSafeEnum {
    case unreachable
    case noTools = "no_tools"
    case noModels = "no_models"
    case unknown
}

/// `POST /api/local/check`: whether the server at an address can run agents, and its models.
public struct LocalCheck: Codable, Sendable, Hashable {
    public var ok: Bool
    public var error: LocalCheckError?
    public var server: LocalServerInfo?
    public var models: [FoundModel]

    public init(
        ok: Bool, error: LocalCheckError? = nil, server: LocalServerInfo? = nil,
        models: [FoundModel] = []
    ) {
        self.ok = ok
        self.error = error
        self.server = server
        self.models = models
    }
}

/// `POST /api/local/models`: the models added.
struct AddedLocalModels: Codable, Sendable, Hashable {
    var models: [LocalModel]
}

/// One model's tokens today.
public struct LocalModelUsage: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var inputTokens: Int
    public var outputTokens: Int

    public init(id: String, inputTokens: Int, outputTokens: Int) {
        self.id = id
        self.inputTokens = inputTokens
        self.outputTokens = outputTokens
    }

    enum CodingKeys: String, CodingKey {
        case id
        case inputTokens = "input_tokens"
        case outputTokens = "output_tokens"
    }
}

/// `GET /api/local/usage`: today's tokens on local models; never a cost.
public struct LocalUsage: Codable, Sendable, Hashable {
    public var todayTokens: Int
    public var models: [LocalModelUsage]

    public init(todayTokens: Int, models: [LocalModelUsage] = []) {
        self.todayTokens = todayTokens
        self.models = models
    }

    enum CodingKeys: String, CodingKey {
        case models
        case todayTokens = "today_tokens"
    }
}

/// `GET /api/setup`: whether the app shows the first-run welcome.
public struct SetupState: Codable, Sendable, Hashable {
    /// No engine signed in, no local model and the welcome never answered.
    public var firstRun: Bool
    public var localOnly: Bool

    public init(firstRun: Bool, localOnly: Bool) {
        self.firstRun = firstRun
        self.localOnly = localOnly
    }

    enum CodingKeys: String, CodingKey {
        case firstRun = "first_run"
        case localOnly = "local_only"
    }
}

/// A local chat's server does not answer: from a refused send (409 `local_server_down`) or
/// a turn that ended with that code.
public struct LocalServerDown: Sendable, Hashable {
    /// The serving app's label, such as "LM Studio".
    public var app: String?
    public var address: String?
    public var start: LocalApp?

    public init(app: String?, address: String?, start: LocalApp?) {
        self.app = app
        self.address = address
        self.start = start
    }

    /// The code's fields in an error body or event payload.
    init(_ body: JSONValue) {
        app = body["app"]?.stringValue
        address = body["address"]?.stringValue
        start = body["start"]?.stringValue.flatMap(LocalApp.init(rawValue:))
    }

    public static let code = "local_server_down"
}

/// `POST /api/local/check` and `POST /api/local/models`: the key is sent as null when none.
struct LocalServerRequest: Encodable {
    var address: String
    var key: String?
    var models: [String]?

    func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(address, forKey: .address)
        try container.encode(key, forKey: .key)
        try container.encodeIfPresent(models, forKey: .models)
    }

    enum CodingKeys: String, CodingKey {
        case address, key, models
    }
}

struct LocalEngineRequest: Encodable {
    var engine: String
}

struct LocalStartRequest: Encodable {
    var app: LocalApp
}
