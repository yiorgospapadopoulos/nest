import Foundation
import Observation

/// Settings > Configuration (B97): the shared instructions, skills and MCP servers, each
/// signed-in engine's own setup, copying an engine's setup to Shared, and each project's
/// own items. The daemon reads and writes the engines' files; this keeps the latest page.
@MainActor @Observable
public final class ConfigurationStore {
    /// Nil until loaded.
    public private(set) var page: ConfigurationPage?
    /// The one engine section that is open; nil when all are folded.
    public private(set) var openEngine: String?
    /// Whether the skills list shows every skill.
    public var showsAllSkills = false
    /// The copy popup while it is open.
    public private(set) var copy: CopyFlow?
    /// The done line after a copy, with its Undo.
    public private(set) var done: CopyDone?
    /// The file in the editor sheet.
    public private(set) var editor: ConfigFileEditor?
    /// Each project's own items, by repo name, once read.
    public private(set) var repos: [String: RepoConfiguration] = [:]
    /// Codex's own plugins as last listed, and the search they match.
    public private(set) var codexPlugins: [CodexPlugin]?
    public private(set) var codexQuery = ""
    public private(set) var codexMarketplaces: [CodexMarketplace] = []
    /// Items with a change under way, by a key such as "skill:release-notes".
    public private(set) var busy: Set<String> = []
    /// Whether an engine was opened or closed by the user; until then the first opens.
    private var engineChosen = false

    let api: any NestAPI

    public init(api: any NestAPI) {
        self.api = api
    }

    public func load() async throws {
        show(try await api.configuration())
    }

    /// Opens the engine's section and closes the others, or folds it when it is open.
    public func toggleEngine(_ id: String) {
        engineChosen = true
        openEngine = openEngine == id ? nil : id
        if copy?.engine != openEngine {
            copy = nil
        }
    }

    /// Opens the engine's section, as the Connectors menu item does for Claude.
    public func openEngine(_ id: String) {
        engineChosen = true
        openEngine = id
    }

    // MARK: Shared items

    public func setUsesShared(engine: String, _ item: SharedItem, on: Bool) async throws {
        try await change("uses:\(engine):\(item.rawValue)") {
            try await self.api.setUsesShared(engine: engine, item: item, on: on)
        }
    }

    /// False for a name the daemon would refuse.
    @discardableResult
    public func createSkill(name: String, description: String) async throws -> Bool {
        guard ConfigurationText.isValidSkillName(name) else { return false }
        try await change("skill:\(name)") {
            try await self.api.createSkill(
                name: name, description: description.trimmingCharacters(in: .whitespaces))
        }
        return true
    }

    public func deleteSkill(_ name: String) async throws {
        try await change("skill:\(name)") { try await self.api.deleteSkill(name) }
    }

    public func makeShared(_ skill: ConfigSkill) async throws {
        try await change("skill:\(skill.name)") {
            try await self.api.makeSkillShared(skill.name, engine: skill.engine ?? "codex")
        }
    }

    /// Shows the switch at once and puts it back when the daemon refuses.
    public func setCodexEnabled(_ skill: ConfigSkill, _ enabled: Bool) async throws {
        setShownCodex(skill.path, enabled)
        do {
            try await change("skill:\(skill.name)") {
                try await self.api.setSkillEnabled(skill.name, codex: enabled)
            }
        } catch {
            setShownCodex(skill.path, skill.codexEnabled)
            throw error
        }
    }

    public func server(_ name: String) async throws -> MCPServerSpec {
        try await api.mcpServer(name)
    }

    public func saveServer(_ name: String, _ spec: MCPServerSpec) async throws {
        try await change("server:\(name)") { try await self.api.saveMCPServer(name, spec) }
    }

    public func deleteServer(_ name: String) async throws {
        try await change("server:\(name)") { try await self.api.deleteMCPServer(name) }
    }

    // MARK: Copy to Shared

    /// Opens the popup with what the copy would do.
    public func startCopy(_ engine: String) async throws {
        let preview = try await api.copyPreview(engine: engine)
        copy = CopyFlow(engine: engine, preview: preview)
        done = nil
    }

    public func cancelCopy() {
        copy = nil
    }

    public func setKeepInstructions(_ keep: Bool) {
        copy?.keepInstructions = keep
    }

    /// Reads both instructions files for Compare, or folds it again.
    public func toggleCompare() async throws {
        guard let flow = copy, let instructions = flow.preview.instructions else { return }
        if flow.compare != nil {
            copy?.compare = nil
            return
        }
        let engine = try await api.configurationFile(path: instructions.enginePath)
        let shared = try await api.configurationFile(path: instructions.sharedPath)
        copy?.compare = CopyCompare(engine: engine.text, shared: shared.text)
    }

    public func applyCopy() async throws {
        guard let flow = copy else { return }
        let replace = flow.preview.instructions != nil && !flow.keepInstructions
        let result = try await change("copy:\(flow.engine)") {
            try await self.api.copyToShared(engine: flow.engine, instructions: replace)
        } page: {
            $0.page
        }
        copy = nil
        done = CopyDone(engine: flow.engine, summary: result.summary, undoID: result.undoID)
    }

    public func undoCopy() async throws {
        guard let done else { return }
        try await change("copy:\(done.engine)") { try await self.api.undoCopy(done.undoID) }
        self.done = nil
    }

    /// The quiet note on an engine's header: what Shared lacks, or that it matches after a
    /// copy.
    public func headerNote(_ engine: EngineConfiguration) -> String? {
        if let note = ConfigurationText.missingNote(engine.missingFromShared) {
            return note
        }
        return done?.engine == engine.id ? "Shared matches \(engine.name)" : nil
    }

    /// Whether the engine's header offers the copy: it is open and has what Shared lacks.
    public func offersCopy(_ engine: EngineConfiguration) -> Bool {
        openEngine == engine.id && !engine.missingFromShared.isEmpty
    }

    // MARK: Editor

    /// Opens the file in the editor sheet and reads it.
    public func edit(path: String, title: String, note: String? = nil) async throws {
        let editor = ConfigFileEditor(api: api, path: path, title: title, note: note)
        self.editor = editor
        try await editor.load()
    }

    public func closeEditor() {
        editor = nil
    }

    // MARK: Projects

    public func loadRepo(_ name: String) async throws {
        repos[name] = try await api.repoConfiguration(name)
    }

    public func saveRepoServer(_ repo: String, _ name: String, _ spec: MCPServerSpec)
        async throws
    {
        try await api.saveRepoMCPServer(repo, name, spec)
        try await loadRepo(repo)
    }

    public func deleteRepoServer(_ repo: String, _ name: String) async throws {
        try await api.deleteRepoMCPServer(repo, name)
        try await loadRepo(repo)
    }

    @discardableResult
    public func createRepoSkill(_ repo: String, name: String, description: String) async throws
        -> Bool
    {
        guard ConfigurationText.isValidSkillName(name) else { return false }
        try await api.createRepoSkill(
            repo, name: name, description: description.trimmingCharacters(in: .whitespaces))
        try await loadRepo(repo)
        return true
    }

    // MARK: Codex plugins

    public func loadCodexPlugins(query: String = "") async throws {
        codexQuery = query
        let found = try await api.codexPlugins(query: query)
        // A later search may have answered first.
        if codexQuery == query {
            codexPlugins = found
        }
    }

    public func loadCodexMarketplaces() async throws {
        codexMarketplaces = try await api.codexMarketplaces()
    }

    public func installCodexPlugin(_ id: String) async throws {
        try await codexChange(id) { try await self.api.installCodexPlugin(id) }
    }

    public func uninstallCodexPlugin(_ id: String) async throws {
        try await codexChange(id) { try await self.api.uninstallCodexPlugin(id) }
    }

    /// False for a blank source.
    @discardableResult
    public func addCodexMarketplace(_ text: String) async throws -> Bool {
        let source = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !source.isEmpty else { return false }
        try await codexChange(source) {
            try await self.api.addCodexMarketplace(source: source)
            try await self.loadCodexMarketplaces()
        }
        return true
    }

    public func removeCodexMarketplace(_ name: String) async throws {
        try await codexChange(name) {
            try await self.api.removeCodexMarketplace(name)
            try await self.loadCodexMarketplaces()
        }
    }

    // MARK: Live

    /// `configuration.changed`: read again what changed, and check the open file.
    /// A sign-in or sign-out adds or removes an engine's section.
    public func apply(_ event: Event) {
        switch event.body {
        case .configurationChanged(let repo):
            Task { try? await refresh(repo: repo) }
        case .claudeAccount, .codexAccount:
            Task { try? await refresh(repo: nil) }
        default:
            break
        }
    }

    /// What `apply` runs: the page or the project, then the editor's file.
    public func refresh(repo: String?) async throws {
        if let repo {
            if repos[repo] != nil {
                try await loadRepo(repo)
            }
        } else if page != nil {
            try await load()
        }
        try await editor?.checkDisk()
    }

    // MARK: Plumbing

    private func show(_ page: ConfigurationPage) {
        self.page = page
        if !engineChosen, openEngine == nil {
            openEngine = page.engines.first?.id
        }
        if let open = openEngine, page.engine(open) == nil {
            openEngine = nil
        }
    }

    private func setShownCodex(_ path: String, _ enabled: Bool?) {
        guard let index = page?.shared.skills.items.firstIndex(where: { $0.path == path })
        else { return }
        page?.shared.skills.items[index].codexEnabled = enabled
    }

    private func change(_ key: String, _ work: () async throws -> ConfigurationPage)
        async throws
    {
        _ = try await change(key, work) { $0 }
    }

    private func change<T>(
        _ key: String, _ work: () async throws -> T, page: (T) -> ConfigurationPage
    ) async throws -> T {
        busy.insert(key)
        defer { busy.remove(key) }
        let result = try await work()
        show(page(result))
        return result
    }

    private func codexChange(_ key: String, _ work: () async throws -> Void) async throws {
        busy.insert(key)
        defer { busy.remove(key) }
        try await work()
        if codexPlugins != nil {
            try await loadCodexPlugins(query: codexQuery)
        }
    }
}

/// The copy popup's state.
public struct CopyFlow: Sendable, Hashable {
    public var engine: String
    public var preview: CopyPreview
    /// "Keep instructions as they are".
    public var keepInstructions = false
    /// Both instructions files side by side, once Compare read them.
    public var compare: CopyCompare?

    public init(engine: String, preview: CopyPreview) {
        self.engine = engine
        self.preview = preview
    }
}

public struct CopyCompare: Sendable, Hashable {
    public var engine: String
    public var shared: String
}

/// The done line: "Copied to Shared: ..." with Undo.
public struct CopyDone: Sendable, Hashable {
    public var engine: String
    public var summary: String
    public var undoID: String
}
