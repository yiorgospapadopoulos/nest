import Foundation
import Observation

/// Settings > Extensions: the Claude Code on this Mac and installing it, and its plugins,
/// skills and marketplaces, all through Claude Code's own commands on the daemon (B81).
@MainActor @Observable
public final class ExtensionsStore {
    public private(set) var claudeCode: ClaudeCodeStatus?
    /// The latest word from the installer, while or after it runs.
    public private(set) var install: ClaudeCodeInstallProgress?
    /// Nil until loaded.
    public private(set) var plugins: [InstalledPlugin]?
    public private(set) var skills: [StandaloneSkill] = []
    public private(set) var marketplaces: [PluginMarketplace] = []
    /// What the marketplaces offer, once Browse read it.
    public private(set) var available: [AvailablePlugin]?
    /// Each plugin's contents, once read.
    public private(set) var details: [String: PluginDetails] = [:]
    /// Plugins and marketplaces with a change under way, by id or name.
    public private(set) var busy: Set<String> = []

    let api: any NestAPI

    public init(api: any NestAPI) {
        self.api = api
    }

    public func loadClaudeCode() async throws {
        claudeCode = try await api.claudeCode()
    }

    /// Starts the official installer; its events tell how it goes.
    public func installClaudeCode() async throws {
        install = ClaudeCodeInstallProgress(state: .running, message: nil)
        do {
            try await api.installClaudeCode()
        } catch {
            install = nil
            throw error
        }
    }

    public var isInstalling: Bool { install?.state == .running }

    /// The installed plugins, standalone skills and marketplaces.
    public func loadInstalled() async throws {
        plugins = try await api.plugins()
        skills = try await api.standaloneSkills()
        marketplaces = try await api.marketplaces()
    }

    public func loadAvailable() async throws {
        available = try await api.availablePlugins()
    }

    public func loadDetails(_ id: String) async throws {
        details[id] = try await api.pluginDetails(id)
    }

    /// Shows the switch at once and puts it back if Claude Code refuses.
    public func setEnabled(_ plugin: InstalledPlugin, _ enabled: Bool) async throws {
        try await change(plugin.id) {
            self.setShown(plugin.id, enabled: enabled)
            do {
                try await self.api.setPluginEnabled(plugin.id, enabled: enabled)
            } catch {
                self.setShown(plugin.id, enabled: plugin.enabled)
                throw error
            }
        }
    }

    public func installPlugin(_ id: String) async throws {
        try await change(id) {
            try await self.api.installPlugin(id)
            try await self.reloadAll()
        }
    }

    public func uninstallPlugin(_ id: String) async throws {
        try await change(id) {
            try await self.api.uninstallPlugin(id)
            try await self.reloadAll()
        }
    }

    /// Adds a marketplace from a URL, a path or a GitHub repo, as typed but trimmed; false
    /// for an empty one.
    @discardableResult
    public func addMarketplace(_ text: String) async throws -> Bool {
        let source = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !source.isEmpty else { return false }
        try await change(source) {
            try await self.api.addMarketplace(source: source)
            try await self.reloadAll()
        }
        return true
    }

    public func removeMarketplace(_ name: String) async throws {
        try await change(name) {
            try await self.api.removeMarketplace(name)
            try await self.reloadAll()
        }
    }

    /// Reads again what is loaded: after a change here, or `extensions.updated`.
    public func reloadAll() async throws {
        if plugins != nil {
            try await loadInstalled()
        }
        if available != nil {
            try await loadAvailable()
        }
    }

    private func setShown(_ id: String, enabled: Bool) {
        if let index = plugins?.firstIndex(where: { $0.id == id }) {
            plugins?[index].enabled = enabled
        }
    }

    private func change(_ key: String, _ work: () async throws -> Void) async throws {
        busy.insert(key)
        defer { busy.remove(key) }
        try await work()
    }

    public func apply(_ event: Event) {
        switch event.body {
        case .extensionsChanged:
            Task { try? await reloadAll() }
        case .claudeCodeInstall(let progress):
            install = progress
        case .claudeCodeUpdated(let status):
            claudeCode = status
        default:
            break
        }
    }
}
