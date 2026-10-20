import Foundation

/// `GET /api/configuration` (B97): what the agents read, shared across the engines and
/// each signed-in engine's own setup. The engines' files are the only source of truth.
public struct ConfigurationPage: Codable, Sendable, Hashable {
    public var shared: SharedConfiguration
    /// Only the engines the user is signed in to.
    public var engines: [EngineConfiguration]

    public init(shared: SharedConfiguration, engines: [EngineConfiguration]) {
        self.shared = shared
        self.engines = engines
    }

    public func engine(_ id: String) -> EngineConfiguration? {
        engines.first { $0.id == id }
    }
}

/// The instructions, skills and MCP servers every engine that uses them shares.
public struct SharedConfiguration: Codable, Sendable, Hashable {
    public var instructions: ConfigFileRef
    public var skills: SharedSkills
    public var mcpServers: [MCPServerEntry]

    public init(instructions: ConfigFileRef, skills: SharedSkills, mcpServers: [MCPServerEntry]) {
        self.instructions = instructions
        self.skills = skills
        self.mcpServers = mcpServers
    }

    enum CodingKeys: String, CodingKey {
        case instructions, skills
        case mcpServers = "mcp_servers"
    }
}

/// A file Nest can open in its editor; `version` is the sha256 of its bytes, nil when the
/// file does not exist (or, for a project's files, is not given).
public struct ConfigFileRef: Codable, Sendable, Hashable {
    public var path: String
    public var exists: Bool
    public var version: String?

    public init(path: String, exists: Bool, version: String? = nil) {
        self.path = path
        self.exists = exists
        self.version = version
    }
}

public struct SharedSkills: Codable, Sendable, Hashable {
    /// `~/.claude/skills` or wherever Claude's config folder is.
    public var folder: String
    public var items: [ConfigSkill]

    public init(folder: String, items: [ConfigSkill]) {
        self.folder = folder
        self.items = items
    }
}

/// Where a skill comes from, which decides whether Nest may edit it.
public enum SkillSource: String, UnknownSafeEnum {
    /// The user's own, in the shared folder.
    case yours
    /// A claude.ai account skill, read only.
    case synced
    /// A plugin's skill, read only.
    case plugin
    /// Found only in one engine's own folder; "Make shared" moves it.
    case engineOnly = "engine_only"
    /// A repo's `.claude/skills`.
    case project
    case unknown
}

/// A skill of the shared folder, a plugin, an engine's own folder or a project.
public struct ConfigSkill: Codable, Sendable, Hashable, Identifiable {
    public var name: String
    public var description: String?
    /// Its SKILL.md.
    public var path: String
    public var source: SkillSource
    /// The plugin it comes with.
    public var plugin: String?
    /// The engine whose own folder holds it, for `engineOnly`.
    public var engine: String?
    public var readOnly: Bool
    /// Whether Codex loads it; Nest switches a few Claude-only ones off. Nil while Codex
    /// does not use the shared skills, or cannot see this one.
    public var codexEnabled: Bool?
    /// Why Codex cannot load it, when it cannot.
    public var codexError: String?

    public var id: String { path }

    public init(
        name: String, description: String? = nil, path: String, source: SkillSource,
        plugin: String? = nil, engine: String? = nil, readOnly: Bool = false,
        codexEnabled: Bool? = true, codexError: String? = nil
    ) {
        self.name = name
        self.description = description
        self.path = path
        self.source = source
        self.plugin = plugin
        self.engine = engine
        self.readOnly = readOnly
        self.codexEnabled = codexEnabled
        self.codexError = codexError
    }

    enum CodingKeys: String, CodingKey {
        case name, description, path, source, plugin, engine
        case readOnly = "read_only"
        case codexEnabled = "codex_enabled"
        case codexError = "codex_error"
    }

    /// `read_only` defaults to false when a list leaves it out.
    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        name = try container.decode(String.self, forKey: .name)
        description = try container.decodeIfPresent(String.self, forKey: .description)
        path = try container.decode(String.self, forKey: .path)
        source = try container.decode(SkillSource.self, forKey: .source)
        plugin = try container.decodeIfPresent(String.self, forKey: .plugin)
        engine = try container.decodeIfPresent(String.self, forKey: .engine)
        readOnly = try container.decodeIfPresent(Bool.self, forKey: .readOnly) ?? false
        codexEnabled = try container.decodeIfPresent(Bool.self, forKey: .codexEnabled)
        codexError = try container.decodeIfPresent(String.self, forKey: .codexError)
    }
}

public enum MCPTransport: String, UnknownSafeEnum, CaseIterable {
    case stdio, http, sse, unknown

    /// The kinds the server form offers.
    public static let choices: [MCPTransport] = [.stdio, .http, .sse]
}

/// An MCP server in a list: the shared ones with the engines that have each, or a
/// project's `.mcp.json` ones.
public struct MCPServerEntry: Codable, Sendable, Hashable, Identifiable {
    public var name: String
    /// Its command line or URL.
    public var summary: String
    public var transport: MCPTransport
    /// `claude`, `codex`.
    public var engines: [String]
    /// False when Codex cannot take it, which `reason` explains.
    public var convertible: Bool
    public var reason: String?

    public var id: String { name }

    public init(
        name: String, summary: String, transport: MCPTransport, engines: [String] = [],
        convertible: Bool = true, reason: String? = nil
    ) {
        self.name = name
        self.summary = summary
        self.transport = transport
        self.engines = engines
        self.convertible = convertible
        self.reason = reason
    }

    enum CodingKeys: String, CodingKey {
        case name, summary, transport, engines, convertible, reason
    }

    /// A project's servers come with their name, summary and transport only.
    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        name = try container.decode(String.self, forKey: .name)
        summary = try container.decode(String.self, forKey: .summary)
        transport = try container.decode(MCPTransport.self, forKey: .transport)
        engines = try container.decodeIfPresent([String].self, forKey: .engines) ?? []
        convertible = try container.decodeIfPresent(Bool.self, forKey: .convertible) ?? true
        reason = try container.decodeIfPresent(String.self, forKey: .reason)
    }
}

/// A signed-in engine's section.
public struct EngineConfiguration: Codable, Sendable, Hashable, Identifiable {
    /// `claude` or `codex`.
    public var id: String
    public var name: String
    /// "giorgos@example.com · Max plan".
    public var account: String?
    /// The version Nest brings itself.
    public var bundledVersion: String?
    /// A CLI the user installed, when Nest found one.
    public var standalone: StandaloneEngine?
    public var configFolder: String
    public var usesShared: UsesShared
    public var missingFromShared: MissingFromShared
    public var items: [EngineItem]

    public init(
        id: String, name: String, account: String? = nil, bundledVersion: String? = nil,
        standalone: StandaloneEngine? = nil, configFolder: String, usesShared: UsesShared,
        missingFromShared: MissingFromShared = MissingFromShared(), items: [EngineItem] = []
    ) {
        self.id = id
        self.name = name
        self.account = account
        self.bundledVersion = bundledVersion
        self.standalone = standalone
        self.configFolder = configFolder
        self.usesShared = usesShared
        self.missingFromShared = missingFromShared
        self.items = items
    }

    enum CodingKeys: String, CodingKey {
        case id, name, account, standalone, items
        case bundledVersion = "bundled_version"
        case configFolder = "config_folder"
        case usesShared = "uses_shared"
        case missingFromShared = "missing_from_shared"
    }

    public func item(_ kind: EngineItemKind) -> EngineItem? {
        items.first { $0.kind == kind }
    }
}

/// The engine's own CLI on this Mac.
public struct StandaloneEngine: Codable, Sendable, Hashable {
    public var path: String
    public var version: String?

    public init(path: String, version: String? = nil) {
        self.path = path
        self.version = version
    }
}

/// The three things an engine can share.
public enum SharedItem: String, Codable, Sendable, CaseIterable {
    case instructions, skills
    case mcpServers = "mcp_servers"

    public var title: String {
        switch self {
        case .instructions: "Instructions"
        case .skills: "Skills"
        case .mcpServers: "MCP servers"
        }
    }
}

/// An engine's "Uses shared" switches.
public struct UsesShared: Codable, Sendable, Hashable {
    public var instructions: SharedSwitch
    public var skills: SharedSwitch
    public var mcpServers: SharedSwitch

    public init(instructions: SharedSwitch, skills: SharedSwitch, mcpServers: SharedSwitch) {
        self.instructions = instructions
        self.skills = skills
        self.mcpServers = mcpServers
    }

    enum CodingKeys: String, CodingKey {
        case instructions, skills
        case mcpServers = "mcp_servers"
    }

    public subscript(item: SharedItem) -> SharedSwitch {
        get {
            switch item {
            case .instructions: instructions
            case .skills: skills
            case .mcpServers: mcpServers
            }
        }
        set {
            switch item {
            case .instructions: instructions = newValue
            case .skills: skills = newValue
            case .mcpServers: mcpServers = newValue
            }
        }
    }
}

/// One switch: `fixed` ones are shown and cannot change, as Claude's skills folder is
/// itself the shared one.
public struct SharedSwitch: Codable, Sendable, Hashable {
    public var on: Bool
    public var fixed: Bool

    public init(on: Bool, fixed: Bool = false) {
        self.on = on
        self.fixed = fixed
    }
}

/// What the engine has that Shared lacks, for "Copy <engine>'s setup to Shared".
public struct MissingFromShared: Codable, Sendable, Hashable {
    public var instructions: Bool
    public var skills: [String]
    public var mcpServers: [String]

    public init(instructions: Bool = false, skills: [String] = [], mcpServers: [String] = []) {
        self.instructions = instructions
        self.skills = skills
        self.mcpServers = mcpServers
    }

    enum CodingKeys: String, CodingKey {
        case instructions, skills
        case mcpServers = "mcp_servers"
    }

    public var isEmpty: Bool { !instructions && skills.isEmpty && mcpServers.isEmpty }
}

public enum EngineItemKind: String, UnknownSafeEnum {
    case plugins, connectors, hooks, subagents, commands, permissions, settings, rules, unknown
}

/// One of the engine's own things, listed with a count and opened in place or in the
/// editor.
public struct EngineItem: Codable, Sendable, Hashable, Identifiable {
    public var kind: EngineItemKind
    public var count: Int?
    /// Such as "14 allow · 2 deny".
    public var detail: String?
    /// The file or folder that holds it.
    public var path: String?
    /// Whether `path` is a folder, opened in Finder rather than the editor.
    public var folder: Bool

    public var id: String { "\(kind.rawValue):\(path ?? "")" }

    public init(
        kind: EngineItemKind, count: Int? = nil, detail: String? = nil, path: String? = nil,
        folder: Bool = false
    ) {
        self.kind = kind
        self.count = count
        self.detail = detail
        self.path = path
        self.folder = folder
    }
}

/// `GET /api/configuration/file`: missing files read as empty with no version.
public struct ConfigFile: Codable, Sendable, Hashable {
    public var path: String
    public var text: String
    public var version: String?

    public init(path: String, text: String, version: String? = nil) {
        self.path = path
        self.text = text
        self.version = version
    }
}

/// How an MCP server is started, in the form Nest sends it and Claude stores it.
public struct MCPServerSpec: Codable, Sendable, Hashable {
    public var transport: MCPTransport
    public var command: String?
    public var args: [String]
    public var env: [String: String]
    public var url: String?
    public var headers: [String: String]

    public init(
        transport: MCPTransport, command: String? = nil, args: [String] = [],
        env: [String: String] = [:], url: String? = nil, headers: [String: String] = [:]
    ) {
        self.transport = transport
        self.command = command
        self.args = args
        self.env = env
        self.url = url
        self.headers = headers
    }

    enum CodingKeys: String, CodingKey {
        case transport, type, command, args, env, url, headers
    }

    /// Claude's own shape names the transport `type`, or leaves it out for a command.
    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        command = try container.decodeIfPresent(String.self, forKey: .command)
        args = try container.decodeIfPresent([String].self, forKey: .args) ?? []
        env = try container.decodeIfPresent([String: String].self, forKey: .env) ?? [:]
        url = try container.decodeIfPresent(String.self, forKey: .url)
        headers = try container.decodeIfPresent([String: String].self, forKey: .headers) ?? [:]
        transport =
            try container.decodeIfPresent(MCPTransport.self, forKey: .transport)
            ?? container.decodeIfPresent(MCPTransport.self, forKey: .type)
            ?? (command == nil ? .http : .stdio)
    }

    /// Every field, nulls included, as the daemon's form expects.
    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(transport, forKey: .transport)
        try container.encode(command, forKey: .command)
        try container.encode(args, forKey: .args)
        try container.encode(env, forKey: .env)
        try container.encode(url, forKey: .url)
        try container.encode(headers, forKey: .headers)
    }
}

/// `GET /api/configuration/copy/{engine}`: what copying the engine's setup to Shared
/// would do.
public struct CopyPreview: Codable, Sendable, Hashable {
    /// Nil when the engine has no instructions of its own to copy.
    public var instructions: CopyInstructions?
    public var skills: CopySkills
    public var mcpServers: CopyServers
    /// What stays with the engine, such as "claude.ai connectors".
    public var stays: [String]

    public init(
        instructions: CopyInstructions?, skills: CopySkills, mcpServers: CopyServers,
        stays: [String]
    ) {
        self.instructions = instructions
        self.skills = skills
        self.mcpServers = mcpServers
        self.stays = stays
    }

    enum CodingKeys: String, CodingKey {
        case instructions, skills, stays
        case mcpServers = "mcp_servers"
    }
}

public struct CopyInstructions: Codable, Sendable, Hashable {
    public var replace: Bool
    public var enginePath: String
    public var sharedPath: String

    public init(replace: Bool, enginePath: String, sharedPath: String) {
        self.replace = replace
        self.enginePath = enginePath
        self.sharedPath = sharedPath
    }

    enum CodingKeys: String, CodingKey {
        case replace
        case enginePath = "engine_path"
        case sharedPath = "shared_path"
    }
}

public struct CopySkills: Codable, Sendable, Hashable {
    public var add: [String]
    public var already: [String]
    /// Engine skills named like a shared one: Shared keeps its own.
    public var sameName: [SameNameSkill]

    public init(add: [String] = [], already: [String] = [], sameName: [SameNameSkill] = []) {
        self.add = add
        self.already = already
        self.sameName = sameName
    }

    enum CodingKeys: String, CodingKey {
        case add, already
        case sameName = "same_name"
    }
}

/// An engine skill the copy skips for its name, and why: Shared has one, or Claude has
/// it from a plugin.
public struct SameNameSkill: Codable, Sendable, Hashable {
    public var name: String
    public var reason: String

    public init(name: String, reason: String) {
        self.name = name
        self.reason = reason
    }
}

public struct CopyServers: Codable, Sendable, Hashable {
    public var add: [String]
    public var already: [String]
    public var notConvertible: [NotConvertibleServer]

    public init(
        add: [String] = [], already: [String] = [], notConvertible: [NotConvertibleServer] = []
    ) {
        self.add = add
        self.already = already
        self.notConvertible = notConvertible
    }

    enum CodingKeys: String, CodingKey {
        case add, already
        case notConvertible = "not_convertible"
    }
}

public struct NotConvertibleServer: Codable, Sendable, Hashable {
    public var name: String
    public var reason: String

    public init(name: String, reason: String) {
        self.name = name
        self.reason = reason
    }
}

/// What the copy did, the backup to undo it from, and the page after it.
public struct CopyResult: Codable, Sendable, Hashable {
    public var summary: String
    public var undoID: String
    public var page: ConfigurationPage

    public init(summary: String, undoID: String, page: ConfigurationPage) {
        self.summary = summary
        self.undoID = undoID
        self.page = page
    }

    enum CodingKeys: String, CodingKey {
        case summary, page
        case undoID = "undo_id"
    }
}

/// `GET /api/repos/{name}/configuration`: the project's own instructions files, skills
/// and `.mcp.json` servers, which only Claude reads.
public struct RepoConfiguration: Codable, Sendable, Hashable {
    /// AGENTS.md and CLAUDE.md.
    public var instructions: [ConfigFileRef]
    public var skills: [ConfigSkill]
    public var mcpServers: [MCPServerEntry]

    public init(
        instructions: [ConfigFileRef], skills: [ConfigSkill], mcpServers: [MCPServerEntry]
    ) {
        self.instructions = instructions
        self.skills = skills
        self.mcpServers = mcpServers
    }

    enum CodingKeys: String, CodingKey {
        case instructions, skills
        case mcpServers = "mcp_servers"
    }
}

/// A plugin of Codex's own, installed or offered by its marketplaces.
public struct CodexPlugin: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var name: String
    public var marketplace: String?
    public var description: String?
    public var installed: Bool

    public init(
        id: String, name: String, marketplace: String? = nil, description: String? = nil,
        installed: Bool = false
    ) {
        self.id = id
        self.name = name
        self.marketplace = marketplace
        self.description = description
        self.installed = installed
    }
}

public struct CodexMarketplace: Codable, Sendable, Hashable, Identifiable {
    public var name: String
    /// Where Codex keeps its checkout.
    public var path: String?

    public var id: String { name }

    public init(name: String, path: String? = nil) {
        self.name = name
        self.path = path
    }
}

/// `GET /api/configuration/codex/plugins`: the plugins, installed first, and the
/// marketplaces they come from.
struct CodexPluginList: Decodable {
    var plugins: [CodexPlugin]
}

// MARK: Requests

struct WriteConfigFileRequest: Encodable {
    var path: String
    var text: String
    var expectedVersion: String?

    enum CodingKeys: String, CodingKey {
        case path, text
        case expectedVersion = "expected_version"
    }

    /// A new file's null version is sent, not left out.
    func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(path, forKey: .path)
        try container.encode(text, forKey: .text)
        try container.encode(expectedVersion, forKey: .expectedVersion)
    }
}

struct FileVersion: Decodable {
    var version: String
}

struct UsesSharedRequest: Encodable {
    var engine: String
    var item: SharedItem
    var on: Bool
}

struct NewSkillRequest: Encodable {
    var name: String
    var description: String
}

struct EngineRequest: Encodable {
    var engine: String
}

struct CopyRequest: Encodable {
    var instructions: Bool
}
