import Foundation

/// The words of Settings > Configuration (B97).
public enum ConfigurationText {
    /// How many skills show before "Show all N".
    public static let skillsShown = 4

    public static let intro =
        "What your agents read: instructions, skills, MCP servers and each engine's own settings. These are the same files Claude Code and Codex use in a terminal, so changes here apply there too."
    public static let footer = "Other engines appear here once you sign in to them under Accounts."
    public static let editorFooter = "Saved files apply from each chat's next message."
    /// What the copy popup does; the instructions part only when it replaces them.
    public static func copyIntro(_ preview: CopyPreview) -> String {
        let intro = "Skills and MCP servers are added to what Shared already has."
        return preview.instructions == nil
            ? intro : intro + " Only the instructions file is replaced."
    }

    /// A path under the home folder with `~` for it.
    public static func shortPath(_ path: String, home: String = NSHomeDirectory()) -> String {
        guard !home.isEmpty, path == home || path.hasPrefix(home + "/") else { return path }
        return "~" + path.dropFirst(home.count)
    }

    /// The engine's display name for an id such as `codex`.
    public static func engineName(_ id: String) -> String {
        switch id {
        case "claude": "Claude"
        case "codex": "Codex"
        default: id.prefix(1).uppercased() + id.dropFirst()
        }
    }

    /// The skills the list shows: the first few, or all of them once asked.
    public static func shownSkills(_ skills: [ConfigSkill], showAll: Bool) -> [ConfigSkill] {
        showAll ? skills : Array(skills.prefix(skillsShown))
    }

    /// "Show all 12" while some are hidden, "Show fewer" while all show, nil when they fit.
    public static func skillsToggle(count: Int, showAll: Bool) -> String? {
        guard count > skillsShown else { return nil }
        return showAll ? "Show fewer" : "Show all \(count)"
    }

    /// The small chip beside a skill.
    public static func skillChip(_ skill: ConfigSkill) -> String {
        switch skill.source {
        case .yours: "yours"
        case .synced: "claude.ai account"
        case .plugin: skill.plugin.map { "plugin \($0)" } ?? "plugin"
        case .engineOnly: "\(engineName(skill.engine ?? "codex")) only"
        case .project: "project"
        case .unknown: "other"
        }
    }

    /// Whether a skill row has its Codex switch: claude.ai account skills, and any Codex
    /// does not load, while Codex uses the shared skills.
    public static func showsCodexSwitch(_ skill: ConfigSkill) -> Bool {
        guard let enabled = skill.codexEnabled else { return false }
        return skill.source == .synced || !enabled
    }

    /// The line beside a skill's name: its description, or where an engine-only one was
    /// found.
    public static func skillDetail(_ skill: ConfigSkill) -> String {
        if skill.source == .engineOnly {
            return "Found in \(engineName(skill.engine ?? "codex"))'s own skills folder"
        }
        return skill.description ?? ""
    }

    /// "Not in Shared yet: instructions, 2 skills, 1 MCP server"; nil when Shared has it
    /// all.
    public static func missingNote(_ missing: MissingFromShared) -> String? {
        var parts: [String] = []
        if missing.instructions {
            parts.append("instructions")
        }
        if !missing.skills.isEmpty {
            parts.append(count(missing.skills.count, "skill", "skills"))
        }
        if !missing.mcpServers.isEmpty {
            parts.append(count(missing.mcpServers.count, "MCP server", "MCP servers"))
        }
        return parts.isEmpty ? nil : "Not in Shared yet: " + parts.joined(separator: ", ")
    }

    /// The copy popup's plain warning about the one thing it replaces.
    public static func replaceWarning(_ engine: String) -> String {
        "Your shared instructions will be replaced with \(engineName(engine))'s. A copy of the current ones is saved first, so you can undo this."
    }

    public static func copyTitle(_ engine: String) -> String {
        "Copy \(engineName(engine))'s setup to Shared"
    }

    /// "Claude Code 2.1.163, bundled with Nest".
    public static func engineLine(_ engine: EngineConfiguration) -> String {
        let product = engine.id == "claude" ? "Claude Code" : engine.name
        guard let version = engine.bundledVersion else { return "\(product), bundled with Nest" }
        return "\(product) \(version), bundled with Nest"
    }

    /// "Also on this Mac: /opt/homebrew/bin/claude 2.1.160", nil when none was found.
    public static func standaloneLine(_ engine: EngineConfiguration) -> String? {
        guard let standalone = engine.standalone else { return nil }
        let version = standalone.version.map { " \($0)" } ?? ""
        return "Also on this Mac: \(shortPath(standalone.path))\(version)"
    }

    /// The caption under a switch that cannot change.
    public static func fixedCaption(_ engine: String, _ item: SharedItem) -> String? {
        switch (engine, item) {
        case ("claude", .skills): "Claude's own folder is the shared one"
        case ("codex", .instructions): "Codex's own AGENTS.md is the shared one"
        default: nil
        }
    }

    /// An engine item's title.
    public static func itemTitle(_ kind: EngineItemKind) -> String {
        switch kind {
        case .plugins: "Plugins"
        case .connectors: "Connectors"
        case .hooks: "Hooks"
        case .subagents: "Subagents"
        case .commands: "Slash commands"
        case .permissions: "Permission rules"
        case .settings: "Settings file"
        case .rules: "Rules"
        case .unknown: "Other"
        }
    }

    /// The grey words after an item's title: its detail, else its count, "none" for zero.
    public static func itemDetail(_ item: EngineItem) -> String? {
        if let detail = item.detail, !detail.isEmpty {
            return detail
        }
        guard let count = item.count else { return nil }
        return count == 0 ? "none" : "\(count)"
    }

    /// An item's grey words in an engine's section: plugins say how many are installed
    /// (Codex's are its own), connectors where they come from.
    public static func itemDetail(_ item: EngineItem, engine: String) -> String? {
        let count = item.count ?? 0
        switch item.kind {
        case .plugins:
            let installed = count == 0 ? "none" : "\(count) installed"
            return engine == "claude" ? installed : "\(engineName(engine))'s own · \(installed)"
        case .connectors:
            return "claude.ai · \(count)"
        default:
            return itemDetail(item)
        }
    }

    /// The button that opens an item's file or folder.
    public static func openTitle(_ item: EngineItem) -> String {
        item.folder ? "Open folder" : "Open"
    }

    /// "Claude", "Codex" chips for a shared server, in a fixed order.
    public static func serverEngines(_ server: MCPServerEntry) -> [String] {
        server.engines.sorted { rank($0) < rank($1) }.map(engineName)
    }

    private static func rank(_ engine: String) -> Int {
        switch engine {
        case "claude": 0
        case "codex": 1
        default: 2
        }
    }

    // MARK: Copy popup

    /// The copy popup's sections, in order.
    public struct CopySection: Sendable, Hashable, Identifiable {
        public var title: String
        /// The bold first words, such as "Add 2", and the names after them.
        public var lead: String?
        public var names: String?
        /// Grey lines under it.
        public var notes: [String]

        public var id: String { title }
    }

    public static func copySections(_ preview: CopyPreview, engine: String) -> [CopySection] {
        let skills = preview.skills
        var skillNotes: [String] = []
        if !skills.already.isEmpty {
            skillNotes.append("\(skills.already.count) already in Shared, left as they are")
        }
        skillNotes += sameNameNotes(skills.sameName)
        let servers = preview.mcpServers
        var serverNotes: [String] = []
        if !servers.already.isEmpty {
            serverNotes.append("\(list(servers.already)) already in Shared")
        }
        for server in servers.notConvertible {
            serverNotes.append("\(server.name) stays with \(engineName(engine)): \(server.reason)")
        }
        return [
            section("Skills", skills.add, notes: skillNotes),
            section("MCP servers", servers.add, notes: serverNotes),
            CopySection(
                title: "Stays \(engineName(engine)) only", lead: nil, names: nil,
                notes: preview.stays.isEmpty ? [] : [sentence(preview.stays)]),
        ]
    }

    private static func section(_ title: String, _ add: [String], notes: [String])
        -> CopySection
    {
        CopySection(
            title: title, lead: add.isEmpty ? "Nothing to add" : "Add \(add.count)",
            names: add.isEmpty ? nil : add.joined(separator: ", "), notes: notes)
    }

    static let sharedHasIt = "Shared has a skill with this name"

    /// One line per reason, in the order the reasons first come.
    static func sameNameNotes(_ skills: [SameNameSkill]) -> [String] {
        var groups: [(reason: String, names: [String])] = []
        for skill in skills {
            if let index = groups.firstIndex(where: { $0.reason == skill.reason }) {
                groups[index].names.append(skill.name)
            } else {
                groups.append((skill.reason, [skill.name]))
            }
        }
        return groups.map { reason, group in
            let list = "(\(shortList(group)))"
            if reason == sharedHasIt {
                let one = group.count == 1
                return
                    "\(group.count) with the same name as \(one ? "a shared one" : "shared ones") \(list): Shared keeps its own"
            }
            // "Claude has it from plugin superpowers".
            if let range = reason.range(of: " has it from plugin ") {
                let engine = reason[..<range.lowerBound]
                let plugin = reason[range.upperBound...]
                return
                    "\(group.count) \(engine) already has from plugin \(plugin) \(list): left as they are"
            }
            return "\(group.count) skipped \(list): \(reason)"
        }
    }

    /// The first three names, then "and N more".
    public static func shortList(_ names: [String]) -> String {
        let shown = names.prefix(3).joined(separator: ", ")
        return names.count > 3 ? "\(shown) and \(names.count - 3) more" : shown
    }

    /// "context7", "context7 and serena", "a, b and c".
    static func list(_ names: [String]) -> String {
        guard names.count > 1 else { return names.first ?? "" }
        return names.dropLast().joined(separator: ", ") + " and " + names[names.count - 1]
    }

    /// The daemon's list joined, starting with a capital.
    static func sentence(_ items: [String]) -> String {
        let text = items.joined(separator: ", ")
        return text.prefix(1).uppercased() + text.dropFirst()
    }

    static func count(_ number: Int, _ one: String, _ many: String) -> String {
        "\(number) \(number == 1 ? one : many)"
    }

    /// A new skill's name as the daemon accepts it: lower case letters, digits and dashes,
    /// starting with a letter or digit, at most 64 characters.
    public static func isValidSkillName(_ name: String) -> Bool {
        guard let first = name.first, name.count <= 64,
            first.isASCII && (first.isLowercase || first.isNumber)
        else { return false }
        return name.allSatisfy { $0.isASCII && ($0.isLowercase || $0.isNumber || $0 == "-") }
    }
}
