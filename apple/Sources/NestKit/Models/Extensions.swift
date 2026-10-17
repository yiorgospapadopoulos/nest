import Foundation

/// An installed Claude Code plugin, as `GET /api/extensions/plugins` lists it (B81).
public struct InstalledPlugin: Codable, Sendable, Hashable, Identifiable {
    /// `name@marketplace`.
    public var id: String
    public var name: String
    public var marketplace: String
    public var version: String?
    public var enabled: Bool
    /// user, project or local.
    public var scope: String
    public var description: String?

    public init(
        id: String, name: String, marketplace: String, version: String? = nil,
        enabled: Bool = true, scope: String = "user", description: String? = nil
    ) {
        self.id = id
        self.name = name
        self.marketplace = marketplace
        self.version = version
        self.enabled = enabled
        self.scope = scope
        self.description = description
    }
}

/// A standalone skill in `~/.claude/skills`, shown read-only.
public struct StandaloneSkill: Codable, Sendable, Hashable, Identifiable {
    public var name: String
    public var description: String?
    public var path: String

    public var id: String { path }

    public init(name: String, description: String? = nil, path: String) {
        self.name = name
        self.description = description
        self.path = path
    }
}

/// A plugin marketplace Claude Code reads.
public struct PluginMarketplace: Codable, Sendable, Hashable, Identifiable {
    public var name: String
    /// The CLI's source kind: github, git, url, directory and so on.
    public var kind: String
    /// Its repo, URL or path.
    public var source: String?

    public var id: String { name }

    public init(name: String, kind: String, source: String? = nil) {
        self.name = name
        self.kind = kind
        self.source = source
    }
}

/// A plugin offered by the configured marketplaces, installed or not.
public struct AvailablePlugin: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var name: String
    public var marketplace: String
    public var description: String?
    public var version: String?
    public var source: String
    public var installCount: Int?
    public var installed: Bool

    public init(
        id: String, name: String, marketplace: String, description: String? = nil,
        version: String? = nil, source: String, installCount: Int? = nil, installed: Bool = false
    ) {
        self.id = id
        self.name = name
        self.marketplace = marketplace
        self.description = description
        self.version = version
        self.source = source
        self.installCount = installCount
        self.installed = installed
    }

    enum CodingKeys: String, CodingKey {
        case id, name, marketplace, description, version, source, installed
        case installCount = "install_count"
    }
}

/// One kind of thing a plugin brings, such as its skills.
public struct PluginComponent: Codable, Sendable, Hashable {
    public var count: Int
    public var names: [String]

    public init(count: Int, names: [String]) {
        self.count = count
        self.names = names
    }
}

/// What a plugin brings; commands count as skills, as Claude Code counts them.
public struct PluginComponents: Codable, Sendable, Hashable {
    public var skills: PluginComponent
    public var agents: PluginComponent
    public var hooks: PluginComponent
    public var mcpServers: PluginComponent
    public var lspServers: PluginComponent

    public init(
        skills: PluginComponent, agents: PluginComponent, hooks: PluginComponent,
        mcpServers: PluginComponent, lspServers: PluginComponent
    ) {
        self.skills = skills
        self.agents = agents
        self.hooks = hooks
        self.mcpServers = mcpServers
        self.lspServers = lspServers
    }

    enum CodingKeys: String, CodingKey {
        case skills, agents, hooks
        case mcpServers = "mcp_servers"
        case lspServers = "lsp_servers"
    }

    /// "3 skills", "1 MCP server" and so on, leaving out what it has none of.
    public var summary: [String] {
        [
            (skills, "skill", "skills"), (agents, "agent", "agents"), (hooks, "hook", "hooks"),
            (mcpServers, "MCP server", "MCP servers"), (lspServers, "LSP server", "LSP servers"),
        ].compactMap { component, one, many in
            switch component.count {
            case 0: nil
            case 1: "1 \(one)"
            default: "\(component.count) \(many)"
            }
        }
    }
}

/// `GET /api/extensions/plugins/{id}/details`: what Browse shows before Install.
public struct PluginDetails: Codable, Sendable, Hashable {
    public var id: String
    public var name: String
    public var marketplace: String
    public var description: String?
    public var source: String
    public var installed: Bool
    /// Nil when its files are not in the marketplace's checkout.
    public var components: PluginComponents?

    public init(
        id: String, name: String, marketplace: String, description: String? = nil,
        source: String, installed: Bool = false, components: PluginComponents? = nil
    ) {
        self.id = id
        self.name = name
        self.marketplace = marketplace
        self.description = description
        self.source = source
        self.installed = installed
        self.components = components
    }
}

struct MarketplaceRequest: Encodable {
    var source: String
}

struct PluginEnabledRequest: Encodable {
    var enabled: Bool
}
