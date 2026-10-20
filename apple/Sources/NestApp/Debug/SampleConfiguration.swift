#if DEBUG
    import Foundation
    import NestKit

    /// Settings > Configuration's sample setup (B97), as the mockup shows it: Claude with
    /// instructions, skills and a server Shared lacks, and Codex on Nest's own copy.
    struct SampleConfiguration {
        static let home = NSHomeDirectory()
        static let shared = "\(home)/.codex/AGENTS.md"
        static let claudeMD = "\(home)/.claude/CLAUDE.md"

        private(set) var copied = false
        var files: [String: ConfigFile] = [
            shared: ConfigFile(
                path: shared,
                text: """
                    # How I like to work

                    - Run only the tests that cover what you changed while working; run the full gate once at the end.
                    - Never push unless I ask in my current message.
                    - Prefer small, readable changes that follow the code around them.

                    ## Writing
                    - Short sentences, no filler.
                    - Explain why in comments only when it is not obvious.
                    """, version: "s1"),
            claudeMD: ConfigFile(
                path: claudeMD,
                text: """
                    # Claude

                    - Never push unless I ask in my current message.
                    - Run the relevant tests only, then the full gate once.
                    - No em dashes anywhere.
                    """, version: "c1"),
        ]
        var codexEnabled: [String: Bool] = ["chrome-browser": false, "computer-use": false]

        func page(codexSignedIn: Bool) -> ConfigurationPage {
            ConfigurationPage(
                shared: SharedConfiguration(
                    instructions: ConfigFileRef(path: Self.shared, exists: true, version: "s1"),
                    skills: SharedSkills(folder: "\(Self.home)/.claude/skills", items: skills),
                    mcpServers: servers),
                engines: codexSignedIn ? [claude, codex] : [claude])
        }

        private var skills: [ConfigSkill] {
            let folder = "\(Self.home)/.claude/skills"
            let yours = { (name: String, description: String?) in
                ConfigSkill(
                    name: name, description: description, path: "\(folder)/\(name)/SKILL.md",
                    source: .yours, codexError: description == nil ? "missing description" : nil)
            }
            let synced = { (name: String, description: String) in
                ConfigSkill(
                    name: name, description: description,
                    path: "\(folder)/synced/\(name)/SKILL.md", source: .synced, readOnly: true,
                    codexEnabled: codexEnabled[name] ?? true)
            }
            var list = [
                yours("release-notes", "Writes release notes from merged pull requests"),
                yours("swift-format-fix", "Fixes swift format lint findings in changed files"),
                synced("chrome-browser", "Drives Chrome through the extension"),
            ]
            if !copied {
                list.append(
                    ConfigSkill(
                        name: "hatch-pet", path: "\(Self.home)/.codex/skills/hatch-pet/SKILL.md",
                        source: .engineOnly, engine: "codex"))
            } else {
                list.append(yours("hatch-pet", "Hatches a pet for the status line"))
            }
            list += [
                yours("pr-description", "Writes a pull request description from the diff"),
                yours("changelog", "Adds the change to CHANGELOG.md"),
                yours("db-migration", "Plans and checks a database migration"),
                synced("computer-use", "Controls native apps on the Mac"),
                synced("pdf", "Reads and fills PDF files"),
                yours("deploy-notes", nil),
                synced("schedule", "Creates scheduled tasks"),
            ]
            return list
        }

        private var servers: [MCPServerEntry] {
            [
                MCPServerEntry(
                    name: "context7", summary: "https://mcp.context7.com/mcp", transport: .http,
                    engines: ["claude", "codex"]),
                MCPServerEntry(
                    name: "serena", summary: "uvx serena start-mcp-server", transport: .stdio,
                    engines: ["claude", "codex"]),
                MCPServerEntry(
                    name: "playwright", summary: "npx @playwright/mcp", transport: .stdio,
                    engines: copied ? ["claude", "codex"] : ["claude"]),
                MCPServerEntry(
                    name: "linear", summary: "https://mcp.linear.app/sse", transport: .sse,
                    engines: ["claude"], convertible: false,
                    reason: "Codex cannot connect to SSE servers"),
            ]
        }

        private var claude: EngineConfiguration {
            let folder = "\(Self.home)/.claude"
            return EngineConfiguration(
                id: "claude", name: "Claude", account: "giorgos@example.com · Max plan",
                bundledVersion: "2.1.286",
                standalone: StandaloneEngine(path: "/opt/homebrew/bin/claude", version: "2.1.160"),
                configFolder: folder,
                usesShared: UsesShared(
                    instructions: SharedSwitch(on: copied),
                    skills: SharedSwitch(on: true, fixed: true), mcpServers: SharedSwitch(on: true)
                ),
                missingFromShared: copied
                    ? MissingFromShared()
                    : MissingFromShared(
                        instructions: true, skills: ["release-notes", "swift-format-fix"],
                        mcpServers: ["playwright"]),
                items: [
                    EngineItem(kind: .plugins, count: 8),
                    EngineItem(kind: .connectors, count: 6),
                    EngineItem(kind: .hooks, count: 2, path: "\(folder)/settings.json"),
                    EngineItem(kind: .subagents, count: 3, path: "\(folder)/agents", folder: true),
                    EngineItem(kind: .commands, count: 5, path: "\(folder)/commands", folder: true),
                    EngineItem(
                        kind: .permissions, count: 16, detail: "14 allow · 2 deny",
                        path: "\(folder)/settings.json"),
                    EngineItem(
                        kind: .settings, detail: "model, output style, status line",
                        path: "\(folder)/settings.json"),
                ])
        }

        private var codex: EngineConfiguration {
            let folder = "\(Self.home)/.codex"
            return EngineConfiguration(
                id: "codex", name: "Codex", account: "giorgos@example.com · ChatGPT Plus",
                bundledVersion: "0.163.0", configFolder: folder,
                usesShared: UsesShared(
                    instructions: SharedSwitch(on: true, fixed: true),
                    skills: SharedSwitch(on: true), mcpServers: SharedSwitch(on: true)),
                missingFromShared: copied
                    ? MissingFromShared() : MissingFromShared(skills: ["hatch-pet"]),
                items: [
                    EngineItem(kind: .plugins, count: 0),
                    EngineItem(kind: .hooks, count: 0, path: "\(folder)/config.toml"),
                    EngineItem(
                        kind: .rules, detail: "commands Codex may run", path: "\(folder)/rules",
                        folder: true),
                    EngineItem(
                        kind: .settings, detail: "model, profiles, sandbox",
                        path: "\(folder)/config.toml"),
                ])
        }

        var preview: CopyPreview {
            CopyPreview(
                instructions: CopyInstructions(
                    replace: true, enginePath: Self.claudeMD, sharedPath: Self.shared),
                skills: CopySkills(
                    add: ["release-notes", "swift-format-fix"],
                    already: (1...9).map { "skill-\($0)" },
                    sameName: [
                        SameNameSkill(
                            name: "changelog", reason: "Shared has a skill with this name")
                    ]),
                mcpServers: CopyServers(
                    add: ["playwright"], already: ["context7", "serena"],
                    notConvertible: [
                        NotConvertibleServer(
                            name: "linear", reason: "Codex cannot connect to SSE servers")
                    ]),
                stays: [
                    "plugins themselves (their skills and MCP servers are covered above)",
                    "claude.ai connectors", "hooks", "subagents", "slash commands",
                    "permission rules",
                ])
        }

        /// Codex's own skills Claude already has from superpowers are left out (B97).
        var codexPreview: CopyPreview {
            let superpowers = [
                "brainstorming", "systematic-debugging", "test-driven-development",
                "writing-plans", "executing-plans", "requesting-code-review",
                "receiving-code-review", "verification-before-completion", "using-git-worktrees",
                "dispatching-parallel-agents", "subagent-driven-development", "writing-skills",
                "finishing-a-development-branch", "using-superpowers", "diagnosing-superpowers",
            ]
            return CopyPreview(
                instructions: nil,
                skills: CopySkills(
                    add: ["hatch-pet"], already: (1...9).map { "skill-\($0)" },
                    sameName: superpowers.map {
                        SameNameSkill(name: $0, reason: "Claude has it from plugin superpowers")
                    }),
                mcpServers: CopyServers(already: ["context7", "serena"]),
                stays: ["plugins themselves", "hooks", "rules"])
        }

        mutating func copy() -> String {
            copied = true
            return
                "Copied to Shared: instructions replaced (backup kept), 2 skills and 1 MCP server added."
        }

        mutating func undo() {
            copied = false
        }

        var repo: RepoConfiguration {
            let root = "\(Self.home)/Personal projects/cv-page"
            return RepoConfiguration(
                instructions: [
                    ConfigFileRef(path: "\(root)/AGENTS.md", exists: false),
                    ConfigFileRef(path: "\(root)/CLAUDE.md", exists: true),
                ],
                skills: [
                    ConfigSkill(
                        name: "publish-cv", description: "Builds the PDF and uploads it",
                        path: "\(root)/.claude/skills/publish-cv/SKILL.md", source: .project)
                ],
                mcpServers: [
                    MCPServerEntry(
                        name: "lighthouse", summary: "npx lighthouse-mcp", transport: .stdio)
                ])
        }
    }
#endif
