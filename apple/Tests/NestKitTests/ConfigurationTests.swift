import Foundation
import Testing

@testable import NestKit

@Suite struct ConfigurationModelTests {
    @Test func decodesThePageAsTheContractShowsIt() {
        let page = Fixture.configurationPage
        let skills = [
            ConfigSkill(
                name: "release-notes", description: "Writes release notes",
                path: "/Users/x/.claude/skills/release-notes/SKILL.md", source: .yours),
            ConfigSkill(
                name: "brainstorming", description: "Explores intent",
                path: "/p/brainstorming/SKILL.md", source: .plugin, plugin: "superpowers",
                readOnly: true),
            ConfigSkill(
                name: "hatch-pet", path: "/Users/x/.codex/skills/hatch-pet/SKILL.md",
                source: .engineOnly, engine: "codex"),
            ConfigSkill(
                name: "chrome-browser", description: "Drives Chrome",
                path: "/Users/x/.claude/skills/synced/chrome-browser/SKILL.md", source: .synced,
                readOnly: true, codexEnabled: false),
            ConfigSkill(
                name: "no-description", path: "/Users/x/.claude/skills/no-description/SKILL.md",
                source: .yours, codexError: "missing field description"),
        ]
        let shared = SharedConfiguration(
            instructions: ConfigFileRef(
                path: "/Users/x/.codex/AGENTS.md", exists: true, version: "abc"),
            skills: SharedSkills(folder: "/Users/x/.claude/skills", items: skills),
            mcpServers: [
                MCPServerEntry(
                    name: "context7", summary: "https://mcp.context7.com/mcp", transport: .http,
                    engines: ["codex", "claude"]),
                MCPServerEntry(
                    name: "linear", summary: "https://mcp.linear.app/sse", transport: .sse,
                    engines: ["claude"], convertible: false, reason: "Codex cannot use SSE"),
            ])
        let claude = EngineConfiguration(
            id: "claude", name: "Claude", account: "giorgos@example.com · Max plan",
            bundledVersion: "2.1.286",
            standalone: StandaloneEngine(path: "/opt/homebrew/bin/claude", version: "2.1.160"),
            configFolder: "/Users/x/.claude",
            usesShared: UsesShared(
                instructions: SharedSwitch(on: true), skills: SharedSwitch(on: true, fixed: true),
                mcpServers: SharedSwitch(on: true)),
            missingFromShared: MissingFromShared(
                instructions: true, skills: ["a", "b"], mcpServers: ["playwright"]),
            items: [
                EngineItem(kind: .plugins, count: 8),
                EngineItem(kind: .hooks, count: 2, path: "/Users/x/.claude/settings.json"),
                EngineItem(
                    kind: .subagents, count: 3, path: "/Users/x/.claude/agents", folder: true),
                EngineItem(
                    kind: .permissions, count: 16, detail: "14 allow · 2 deny",
                    path: "/Users/x/.claude/settings.json"),
                EngineItem(kind: .unknown, count: 1),
            ])
        let codex = EngineConfiguration(
            id: "codex", name: "Codex", bundledVersion: "0.163.0", configFolder: "/Users/x/.codex",
            usesShared: UsesShared(
                instructions: SharedSwitch(on: true, fixed: true),
                skills: SharedSwitch(on: false), mcpServers: SharedSwitch(on: true)))
        #expect(page == ConfigurationPage(shared: shared, engines: [claude, codex]))
        #expect(page.engine("codex")?.missingFromShared.isEmpty == true)
        #expect(page.engine("gemini") == nil)
        #expect(claude.item(.hooks)?.id == "hooks:/Users/x/.claude/settings.json")
        #expect(claude.item(.rules) == nil)
        #expect(EngineItem(kind: .plugins).id == "plugins:")
        #expect(skills[0].id == skills[0].path)
        #expect(shared.mcpServers[0].id == "context7")
    }

    @Test func listsLeaveOutFlagsTheyDoNotNeed() {
        let project = Fixture.decode(
            RepoConfiguration.self,
            json: """
                {"instructions": [{"path": "/r/AGENTS.md", "exists": false},
                                  {"path": "/r/CLAUDE.md", "exists": true}],
                 "skills": [{"name": "deploy", "path": "/r/.claude/skills/deploy/SKILL.md",
                             "source": "project"}],
                 "mcp_servers": [{"name": "db", "summary": "npx db-mcp", "transport": "stdio"}]}
                """)
        #expect(
            project
                == RepoConfiguration(
                    instructions: [
                        ConfigFileRef(path: "/r/AGENTS.md", exists: false),
                        ConfigFileRef(path: "/r/CLAUDE.md", exists: true),
                    ],
                    skills: [
                        ConfigSkill(
                            name: "deploy", path: "/r/.claude/skills/deploy/SKILL.md",
                            source: .project, codexEnabled: nil)
                    ],
                    mcpServers: [
                        MCPServerEntry(name: "db", summary: "npx db-mcp", transport: .stdio)
                    ]))
        let odd = Fixture.decode(
            ConfigSkill.self, json: #"{"name": "x", "path": "/x", "source": "galaxy"}"#)
        #expect(odd.source == .unknown)
        #expect(odd.codexEnabled == nil)
        // Null while Codex does not use the shared skills.
        let unused = Fixture.decode(
            ConfigSkill.self,
            json: #"{"name": "x", "path": "/x", "source": "yours", "codex_enabled": null}"#)
        #expect(unused.codexEnabled == nil)
    }

    @Test func serverSpecReadsClaudesShapeAndSendsEveryField() throws {
        let stdio = Fixture.decode(
            MCPServerSpec.self,
            json: #"{"command": "npx", "args": ["@playwright/mcp"], "env": {"A": "1"}}"#)
        #expect(
            stdio
                == MCPServerSpec(
                    transport: .stdio, command: "npx", args: ["@playwright/mcp"], env: ["A": "1"]))
        let typed = Fixture.decode(
            MCPServerSpec.self,
            json: #"{"type": "http", "url": "https://x/mcp", "headers": {"H": "v"}}"#)
        #expect(typed == MCPServerSpec(transport: .http, url: "https://x/mcp", headers: ["H": "v"]))
        let bare = Fixture.decode(MCPServerSpec.self, json: #"{"url": "https://x/mcp"}"#)
        #expect(bare.transport == .http)
        let named = Fixture.decode(
            MCPServerSpec.self, json: #"{"transport": "sse", "url": "https://x/sse"}"#)
        #expect(named.transport == .sse)
        #expect(
            Fixture.json(MCPServerSpec(transport: .stdio, command: "uvx"))
                == #"{"args":[],"command":"uvx","env":{},"headers":{},"transport":"stdio","url":null}"#
        )
        #expect(MCPTransport.choices == [.stdio, .http, .sse])
    }

    @Test func decodesTheCopyPreviewAndResult() {
        #expect(
            Fixture.copyPreview
                == CopyPreview(
                    instructions: CopyInstructions(
                        replace: true, enginePath: "/Users/x/.claude/CLAUDE.md",
                        sharedPath: "/Users/x/.codex/AGENTS.md"),
                    skills: CopySkills(
                        add: ["release-notes", "swift-format-fix"], already: ["a", "b", "c"],
                        sameName: [
                            SameNameSkill(
                                name: "changelog", reason: "Shared has a skill with this name")
                        ]),
                    mcpServers: CopyServers(
                        add: ["playwright"], already: ["context7", "serena"],
                        notConvertible: [NotConvertibleServer(name: "linear", reason: "uses SSE")]),
                    stays: ["plugins themselves", "claude.ai connectors", "hooks"]))
        let result = Fixture.decode(
            CopyResult.self,
            json: """
                {"summary": "Copied to Shared: 1 skill added.", "undo_id": "20261020-copy",
                 "page": \(Fixture.configurationJSON)}
                """)
        #expect(
            result
                == CopyResult(
                    summary: "Copied to Shared: 1 skill added.", undoID: "20261020-copy",
                    page: Fixture.configurationPage))
        #expect(CopySkills() == CopySkills(add: [], already: [], sameName: []))
        #expect(CopyServers().add.isEmpty)
    }

    @Test func decodesCodexPluginsAndMarketplaces() {
        let plugins = Fixture.decode(
            [CodexPlugin].self,
            json:
                #"[{"id": "figma@openai", "name": "figma", "marketplace": "openai", "description": "Design files", "installed": true}]"#
        )
        #expect(
            plugins == [
                CodexPlugin(
                    id: "figma@openai", name: "figma", marketplace: "openai",
                    description: "Design files", installed: true)
            ])
        let markets = Fixture.decode(
            [CodexMarketplace].self, json: #"[{"name": "openai", "path": "/m/openai"}]"#)
        #expect(markets == [CodexMarketplace(name: "openai", path: "/m/openai")])
        #expect(markets[0].id == "openai")
    }

    @Test func switchesReadAndWriteByItem() {
        var uses = UsesShared(
            instructions: SharedSwitch(on: true), skills: SharedSwitch(on: false),
            mcpServers: SharedSwitch(on: true))
        for item in SharedItem.allCases {
            uses[item].on.toggle()
        }
        #expect(uses[.instructions].on == false)
        #expect(uses[.skills].on == true)
        #expect(uses[.mcpServers].on == false)
        #expect(SharedItem.allCases.map(\.title) == ["Instructions", "Skills", "MCP servers"])
    }

    @Test func fileRequestSendsANullVersion() {
        #expect(
            Fixture.json(WriteConfigFileRequest(path: "/a", text: "x", expectedVersion: nil))
                == #"{"expected_version":null,"path":"/a","text":"x"}"#)
    }

    @Test func eventSaysWhatChanged() {
        let user = Fixture.event(
            EventType.configurationChanged, #"{"scope": "user", "repo": null}"#, session: nil)
        #expect(user.body == .configurationChanged(repo: nil))
        let repo = Fixture.event(
            EventType.configurationChanged, #"{"scope": "repo", "repo": "nest"}"#, session: nil)
        #expect(repo.body == .configurationChanged(repo: "nest"))
    }
}

@Suite struct ConfigurationTextTests {
    let page = Fixture.configurationPage

    @Test func shortensHomePaths() {
        #expect(
            ConfigurationText.shortPath("/Users/x/.codex/AGENTS.md", home: "/Users/x")
                == "~/.codex/AGENTS.md")
        #expect(ConfigurationText.shortPath("/Users/x", home: "/Users/x") == "~")
        #expect(ConfigurationText.shortPath("/Users/xy/a", home: "/Users/x") == "/Users/xy/a")
        #expect(ConfigurationText.shortPath("/a", home: "") == "/a")
        #expect(ConfigurationText.shortPath(NSHomeDirectory() + "/a") == "~/a")
    }

    @Test func namesEngines() {
        #expect(ConfigurationText.engineName("claude") == "Claude")
        #expect(ConfigurationText.engineName("codex") == "Codex")
        #expect(ConfigurationText.engineName("gemini") == "Gemini")
    }

    @Test func showsFourSkillsThenShowAll() {
        let skills = page.shared.skills.items
        #expect(ConfigurationText.shownSkills(skills, showAll: false).count == 4)
        #expect(ConfigurationText.shownSkills(skills, showAll: true).count == 5)
        #expect(ConfigurationText.skillsToggle(count: 5, showAll: false) == "Show all 5")
        #expect(ConfigurationText.skillsToggle(count: 5, showAll: true) == "Show fewer")
        #expect(ConfigurationText.skillsToggle(count: 4, showAll: false) == nil)
    }

    @Test func labelsWhereEachSkillComesFrom() {
        let skills = page.shared.skills.items
        #expect(
            skills.map(ConfigurationText.skillChip) == [
                "yours", "plugin superpowers", "Codex only", "claude.ai account", "yours",
            ])
        #expect(ConfigurationText.skillDetail(skills[0]) == "Writes release notes")
        #expect(ConfigurationText.skillDetail(skills[2]) == "Found in Codex's own skills folder")
        #expect(ConfigurationText.skillDetail(skills[4]) == "")
        var odd = skills[1]
        odd.plugin = nil
        #expect(ConfigurationText.skillChip(odd) == "plugin")
        odd.source = .project
        #expect(ConfigurationText.skillChip(odd) == "project")
        odd.source = .unknown
        #expect(ConfigurationText.skillChip(odd) == "other")
        odd.source = .engineOnly
        #expect(ConfigurationText.skillChip(odd) == "Codex only")
        #expect(ConfigurationText.skillDetail(odd) == "Found in Codex's own skills folder")
    }

    @Test func offersTheCodexSwitchWhereItMatters() {
        let skills = page.shared.skills.items
        // A claude.ai skill, and one Nest switched off for Codex.
        #expect(ConfigurationText.showsCodexSwitch(skills[3]))
        var off = skills[0]
        off.codexEnabled = false
        #expect(ConfigurationText.showsCodexSwitch(off))
        #expect(!ConfigurationText.showsCodexSwitch(skills[0]))
        // Codex does not use the shared skills.
        var unused = skills[3]
        unused.codexEnabled = nil
        #expect(!ConfigurationText.showsCodexSwitch(unused))
    }

    @Test func saysWhatSharedLacks() {
        #expect(
            ConfigurationText.missingNote(page.engines[0].missingFromShared)
                == "Not in Shared yet: instructions, 2 skills, 1 MCP server")
        #expect(
            ConfigurationText.missingNote(MissingFromShared(skills: ["a"], mcpServers: ["b", "c"]))
                == "Not in Shared yet: 1 skill, 2 MCP servers")
        #expect(ConfigurationText.missingNote(MissingFromShared()) == nil)
        #expect(ConfigurationText.copyTitle("claude") == "Copy Claude's setup to Shared")
        #expect(
            ConfigurationText.replaceWarning("claude")
                == "Your shared instructions will be replaced with Claude's. A copy of the current ones is saved first, so you can undo this."
        )
    }

    @Test func describesTheEngine() {
        let claude = page.engines[0]
        #expect(ConfigurationText.engineLine(claude) == "Claude Code 2.1.286, bundled with Nest")
        #expect(
            ConfigurationText.standaloneLine(claude)
                == "Also on this Mac: /opt/homebrew/bin/claude 2.1.160")
        var codex = page.engines[1]
        #expect(ConfigurationText.engineLine(codex) == "Codex 0.163.0, bundled with Nest")
        #expect(ConfigurationText.standaloneLine(codex) == nil)
        codex.bundledVersion = nil
        codex.standalone = StandaloneEngine(path: "/usr/local/bin/codex")
        #expect(ConfigurationText.engineLine(codex) == "Codex, bundled with Nest")
        #expect(ConfigurationText.standaloneLine(codex) == "Also on this Mac: /usr/local/bin/codex")
        #expect(
            ConfigurationText.fixedCaption("claude", .skills)
                == "Claude's own folder is the shared one")
        #expect(
            ConfigurationText.fixedCaption("codex", .instructions)
                == "Codex's own AGENTS.md is the shared one")
        #expect(ConfigurationText.fixedCaption("claude", .instructions) == nil)
    }

    @Test func titlesAndDetailsEngineItems() {
        let kinds: [EngineItemKind] = [
            .plugins, .connectors, .hooks, .subagents, .commands, .permissions, .settings, .rules,
            .unknown,
        ]
        #expect(
            kinds.map(ConfigurationText.itemTitle) == [
                "Plugins", "Connectors", "Hooks", "Subagents", "Slash commands", "Permission rules",
                "Settings file", "Rules", "Other",
            ])
        let items = page.engines[0].items
        #expect(ConfigurationText.itemDetail(items[1]) == "2")
        #expect(ConfigurationText.itemDetail(items[3]) == "14 allow · 2 deny")
        #expect(ConfigurationText.itemDetail(EngineItem(kind: .hooks, count: 0)) == "none")
        #expect(ConfigurationText.itemDetail(EngineItem(kind: .settings, detail: "")) == nil)
        #expect(ConfigurationText.itemDetail(items[0], engine: "claude") == "8 installed")
        #expect(
            ConfigurationText.itemDetail(EngineItem(kind: .plugins, count: 0), engine: "codex")
                == "Codex's own · none")
        #expect(
            ConfigurationText.itemDetail(EngineItem(kind: .plugins), engine: "claude") == "none")
        #expect(
            ConfigurationText.itemDetail(EngineItem(kind: .connectors, count: 6), engine: "claude")
                == "claude.ai · 6")
        #expect(ConfigurationText.itemDetail(items[1], engine: "claude") == "2")
        #expect(ConfigurationText.openTitle(items[2]) == "Open folder")
        #expect(ConfigurationText.openTitle(items[1]) == "Open")
    }

    @Test func ordersServerEngines() {
        #expect(
            ConfigurationText.serverEngines(page.shared.mcpServers[0]) == ["Claude", "Codex"])
        let odd = MCPServerEntry(
            name: "x", summary: "", transport: .stdio, engines: ["gemini", "codex"])
        #expect(ConfigurationText.serverEngines(odd) == ["Codex", "Gemini"])
    }

    @Test func copySectionsSayWhatIsAddedAndKept() {
        let sections = ConfigurationText.copySections(Fixture.copyPreview, engine: "claude")
        #expect(sections.map(\.title) == ["Skills", "MCP servers", "Stays Claude only"])
        #expect(sections[0].lead == "Add 2")
        #expect(sections[0].names == "release-notes, swift-format-fix")
        #expect(
            sections[0].notes == [
                "3 already in Shared, left as they are",
                "1 with the same name as a shared one (changelog): Shared keeps its own",
            ])
        #expect(sections[1].lead == "Add 1")
        #expect(
            sections[1].notes == [
                "context7 and serena already in Shared", "linear stays with Claude: uses SSE",
            ])
        #expect(sections[2].notes == ["Plugins themselves, claude.ai connectors, hooks"])
        #expect(sections[2].id == "Stays Claude only")

        let shared = "Shared has a skill with this name"
        let plugin = "Claude has it from plugin superpowers"
        let names = ["brainstorming", "debugging", "tdd", "plans", "review"]
        let empty = ConfigurationText.copySections(
            CopyPreview(
                instructions: nil,
                skills: CopySkills(
                    sameName: [SameNameSkill(name: "a", reason: shared)]
                        + names.map { SameNameSkill(name: $0, reason: plugin) }
                        + [
                            SameNameSkill(name: "b", reason: shared),
                            SameNameSkill(name: "c", reason: "Something else"),
                        ]),
                mcpServers: CopyServers(already: ["x", "y", "z"]), stays: []),
            engine: "codex")
        #expect(empty[0].lead == "Nothing to add")
        #expect(empty[0].names == nil)
        // Grouped by reason, in the order the reasons first come, long lists cut to three.
        #expect(
            empty[0].notes == [
                "2 with the same name as shared ones (a, b): Shared keeps its own",
                "5 Claude already has from plugin superpowers (brainstorming, debugging, tdd and 2 more): left as they are",
                "1 skipped (c): Something else",
            ])
        #expect(ConfigurationText.shortList(["a", "b", "c", "d"]) == "a, b, c and 1 more")
        #expect(ConfigurationText.shortList(["a", "b", "c"]) == "a, b, c")
        #expect(
            ConfigurationText.copyIntro(Fixture.copyPreview)
                == "Skills and MCP servers are added to what Shared already has. Only the instructions file is replaced."
        )
        var keep = Fixture.copyPreview
        keep.instructions = nil
        #expect(
            ConfigurationText.copyIntro(keep)
                == "Skills and MCP servers are added to what Shared already has.")
        #expect(empty[1].notes == ["x, y and z already in Shared"])
        #expect(empty[2].notes.isEmpty)
        #expect(ConfigurationText.list([]) == "")
    }

    @Test func checksSkillNames() {
        #expect(ConfigurationText.isValidSkillName("release-notes"))
        #expect(ConfigurationText.isValidSkillName("2fa"))
        #expect(!ConfigurationText.isValidSkillName(""))
        #expect(!ConfigurationText.isValidSkillName("-x"))
        #expect(!ConfigurationText.isValidSkillName("Release"))
        #expect(!ConfigurationText.isValidSkillName("a b"))
        #expect(!ConfigurationText.isValidSkillName("é"))
        #expect(!ConfigurationText.isValidSkillName(String(repeating: "a", count: 65)))
        #expect(ConfigurationText.isValidSkillName(String(repeating: "a", count: 64)))
    }
}

@Suite struct MCPServerFormTests {
    @Test func aNewServerNeedsANameAndACommand() {
        var form = MCPServerForm()
        #expect(form.isNew)
        #expect(form.spec == nil)
        form.name = " playwright "
        #expect(form.spec == nil)
        form.command = "npx"
        form.args = "@playwright/mcp\n\n --headless "
        form.env = "DEBUG=1\nnot a pair\n=x\nTOKEN = a=b"
        #expect(form.trimmedName == "playwright")
        #expect(
            form.spec
                == MCPServerSpec(
                    transport: .stdio, command: "npx", args: ["@playwright/mcp", "--headless"],
                    env: ["DEBUG": "1", "TOKEN": "a=b"]))
    }

    @Test func aRemoteServerNeedsAURL() {
        var form = MCPServerForm()
        form.name = "context7"
        form.transport = .http
        #expect(form.spec == nil)
        form.url = "https://mcp.context7.com/mcp"
        form.headers = "Authorization: Bearer ${KEY}"
        #expect(
            form.spec
                == MCPServerSpec(
                    transport: .http, url: "https://mcp.context7.com/mcp",
                    headers: ["Authorization": "Bearer ${KEY}"]))
    }

    @Test func editingFillsTheFormFromTheServer() {
        let form = MCPServerForm(
            name: "serena",
            spec: MCPServerSpec(
                transport: .stdio, command: "uvx", args: ["serena", "start"],
                env: ["B": "2", "A": "1"], headers: ["Y": "2", "X": "1"]))
        #expect(!form.isNew)
        #expect(form.command == "uvx")
        #expect(form.args == "serena\nstart")
        #expect(form.env == "A=1\nB=2")
        #expect(form.headers == "X: 1\nY: 2")
        #expect(form.url == "")
        let odd = MCPServerForm(name: "x", spec: MCPServerSpec(transport: .unknown))
        #expect(odd.transport == .stdio)
    }
}

@MainActor
@Suite struct ConfigFileEditorTests {
    let api = FakeAPI()
    let path = "/Users/x/.codex/AGENTS.md"

    func editor(_ text: String = "# Rules", version: String? = "v1") async throws
        -> ConfigFileEditor
    {
        api.set { $0.configFiles[path] = ConfigFile(path: path, text: text, version: version) }
        let editor = ConfigFileEditor(
            api: api, path: path, title: "Instructions", note: "used by Claude and Codex")
        try await editor.load()
        return editor
    }

    func changeOnDisk(_ text: String, version: String) {
        api.set { $0.configFiles[path] = ConfigFile(path: path, text: text, version: version) }
    }

    @Test func readsAndSavesTheFile() async throws {
        let editor = try await editor()
        #expect(editor.loaded)
        #expect(editor.id == path)
        #expect(editor.note == "used by Claude and Codex")
        #expect(editor.text == "# Rules")
        #expect(!editor.isDirty)
        editor.text = "# Rules\n- one"
        #expect(editor.isDirty)
        #expect(try await editor.save())
        #expect(!editor.isDirty)
        #expect(!editor.saving)
        #expect(api.calls.contains("saveConfigurationFile \(path) v1"))
        // A second save names the version the first one made.
        editor.text += "\n- two"
        #expect(try await editor.save())
        #expect(api.state.withLock { $0.configFiles[path]?.text } == "# Rules\n- one\n- two")
    }

    @Test func aMissingFileStartsEmptyAndIsCreated() async throws {
        let editor = ConfigFileEditor(api: api, path: "/new/AGENTS.md", title: "Instructions")
        try await editor.load()
        #expect(editor.text == "")
        #expect(editor.version == nil)
        editor.text = "hello"
        #expect(try await editor.save())
        #expect(api.calls.contains("saveConfigurationFile /new/AGENTS.md nil"))
    }

    @Test func anUntouchedDraftFollowsTheDisk() async throws {
        let editor = try await editor()
        changeOnDisk("# Theirs", version: "v2")
        try await editor.checkDisk()
        #expect(editor.text == "# Theirs")
        #expect(editor.version == "v2")
        #expect(editor.onDisk == nil)
    }

    @Test func editsShowTheChangedOnDiskBarThenReload() async throws {
        let editor = try await editor()
        editor.text = "# Mine"
        changeOnDisk("# Theirs", version: "v2")
        try await editor.checkDisk()
        #expect(editor.onDisk == ConfigFile(path: path, text: "# Theirs", version: "v2"))
        #expect(editor.text == "# Mine")
        editor.reload()
        #expect(editor.text == "# Theirs")
        #expect(editor.onDisk == nil)
        #expect(!editor.isDirty)
        editor.reload()
        #expect(editor.text == "# Theirs")
    }

    @Test func keepMineSavesOverTheDisk() async throws {
        let editor = try await editor()
        editor.text = "# Mine"
        changeOnDisk("# Theirs", version: "v2")
        try await editor.checkDisk()
        editor.keepMine()
        #expect(editor.onDisk == nil)
        #expect(editor.version == "v2")
        #expect(try await editor.save())
        #expect(api.state.withLock { $0.configFiles[path]?.text } == "# Mine")
        editor.keepMine()
        #expect(editor.version != nil)
    }

    @Test func aSaveRefusedForAChangeShowsTheBar() async throws {
        let editor = try await editor()
        editor.text = "# Mine"
        changeOnDisk("# Theirs", version: "v2")
        #expect(try await editor.save() == false)
        #expect(editor.onDisk?.text == "# Theirs")
        #expect(editor.text == "# Mine")
    }

    @Test func invalidTextShowsTheDaemonsWordsAndStaysOpen() async throws {
        let editor = try await editor()
        editor.text = "[model\n"
        api.set {
            $0.failNext["saveConfigurationFile"] = APIError.invalidInput("Invalid TOML at line 1")
        }
        #expect(try await editor.save() == false)
        #expect(editor.error == "Invalid TOML at line 1")
        #expect(editor.text == "[model\n")
        #expect(editor.onDisk == nil)
        editor.text = "model = \"o3\"\n"
        #expect(try await editor.save())
        #expect(editor.error == nil)
    }

    @Test func aConflictWithoutAVersionIsChangedOnDisk() async throws {
        let editor = try await editor()
        editor.text = "# Mine"
        changeOnDisk("# Theirs", version: "v2")
        api.set {
            $0.failNext["saveConfigurationFile"] = APIError.from(
                HTTPResponse(
                    status: 409, headers: [:],
                    body: Data(#"{"detail": "changed", "current_version": null}"#.utf8)))
        }
        #expect(try await editor.save() == false)
        #expect(editor.onDisk?.text == "# Theirs")
        editor.reload()
        #expect(editor.text == "# Theirs")
        #expect(editor.error == nil)
    }

    @Test func otherFailuresAreThrown() async throws {
        let editor = try await editor()
        api.fail("saveConfigurationFile")
        await #expect(throws: APIError.self) { try await editor.save() }
        #expect(!editor.saving)
    }

    @Test func theSameTextOrAnUnchangedVersionIsNoChange() async throws {
        let editor = try await editor()
        try await editor.checkDisk()
        #expect(editor.onDisk == nil)
        editor.text = "# Same"
        changeOnDisk("# Same", version: "v3")
        try await editor.checkDisk()
        #expect(editor.onDisk == nil)
        #expect(editor.version == "v3")
        let unloaded = ConfigFileEditor(api: api, path: path, title: "x")
        try await unloaded.checkDisk()
        #expect(!api.calls.contains("configurationFile x"))
    }

    @Test func noCheckWhileSaving() async throws {
        let editor = try await editor()
        let (gate, open) = AsyncStream<Void>.makeStream()
        api.set { $0.gates["saveConfigurationFile"] = gate }
        editor.text = "# Mine"
        let saving = Task { try await editor.save() }
        while !editor.saving { await Task.yield() }
        let reads = api.calls.count
        try await editor.checkDisk()
        #expect(api.calls.count == reads)
        open.finish()
        #expect(try await saving.value)
    }
}

@MainActor
@Suite struct ConfigurationStoreTests {
    let api = FakeAPI()

    func loaded() async throws -> ConfigurationStore {
        let store = ConfigurationStore(api: api)
        try await store.load()
        return store
    }

    @Test func opensTheFirstEngineAndOneAtATime() async throws {
        let store = try await loaded()
        #expect(store.openEngine == "claude")
        store.toggleEngine("codex")
        #expect(store.openEngine == "codex")
        store.toggleEngine("codex")
        #expect(store.openEngine == nil)
        // Folding them all is kept across reloads.
        try await store.load()
        #expect(store.openEngine == nil)
        store.openEngine("claude")
        #expect(store.openEngine == "claude")
    }

    @Test func anEngineSignedOutClosesItsSection() async throws {
        let store = try await loaded()
        store.toggleEngine("codex")
        api.set { $0.configuration.engines.removeLast() }
        try await store.load()
        #expect(store.openEngine == nil)
        let empty = ConfigurationStore(api: api)
        api.set { $0.configuration.engines = [] }
        try await empty.load()
        #expect(empty.openEngine == nil)
    }

    @Test func changesTheSharedSwitches() async throws {
        let store = try await loaded()
        try await store.setUsesShared(engine: "codex", .skills, on: true)
        #expect(store.page?.engine("codex")?.usesShared.skills.on == true)
        #expect(api.calls.contains("setUsesShared codex skills true"))
        #expect(store.busy.isEmpty)
    }

    @Test func managesSkills() async throws {
        let store = try await loaded()
        #expect(try await store.createSkill(name: "Bad Name", description: "") == false)
        #expect(try await store.createSkill(name: "deploy", description: " Ships it "))
        #expect(api.calls.contains("createSkill deploy Ships it"))
        #expect(store.page?.shared.skills.items.last?.name == "deploy")
        try await store.deleteSkill("deploy")
        #expect(store.page?.shared.skills.items.contains { $0.name == "deploy" } == false)
        let codexOnly = store.page!.shared.skills.items[2]
        try await store.makeShared(codexOnly)
        #expect(api.calls.contains("makeSkillShared hatch-pet codex"))
        #expect(store.page?.shared.skills.items[2].source == .yours)
        var plain = codexOnly
        plain.engine = nil
        try await store.makeShared(plain)
        #expect(api.calls.last == "makeSkillShared hatch-pet codex")
    }

    @Test func codexSwitchShowsAtOnceAndComesBackOnFailure() async throws {
        let store = try await loaded()
        let skill = store.page!.shared.skills.items[3]
        let (gate, open) = AsyncStream<Void>.makeStream()
        api.set { $0.gates["setSkillEnabled"] = gate }
        let change = Task { try await store.setCodexEnabled(skill, true) }
        while store.busy.isEmpty { await Task.yield() }
        #expect(store.page?.shared.skills.items[3].codexEnabled == true)
        open.finish()
        try await change.value
        #expect(store.page?.shared.skills.items[3].codexEnabled == true)

        api.set { $0.gates = [:] }
        api.fail("setSkillEnabled")
        let now = store.page!.shared.skills.items[3]
        await #expect(throws: APIError.self) { try await store.setCodexEnabled(now, false) }
        #expect(store.page?.shared.skills.items[3].codexEnabled == true)
        // A skill no longer listed changes nothing shown.
        var gone = now
        gone.path = "/gone"
        await #expect(throws: APIError.self) { try await store.setCodexEnabled(gone, false) }
    }

    @Test func managesServers() async throws {
        let store = try await loaded()
        let spec = MCPServerSpec(transport: .stdio, command: "npx", args: ["@playwright/mcp"])
        try await store.saveServer("playwright", spec)
        #expect(store.page?.shared.mcpServers.last?.name == "playwright")
        #expect(try await store.server("playwright") == spec)
        try await store.deleteServer("playwright")
        #expect(store.page?.shared.mcpServers.contains { $0.name == "playwright" } == false)
    }

    @Test func copiesTheEnginesSetupWithUndo() async throws {
        let store = try await loaded()
        let claude = store.page!.engine("claude")!
        #expect(store.offersCopy(claude))
        #expect(
            store.headerNote(claude) == "Not in Shared yet: instructions, 2 skills, 1 MCP server")
        #expect(!store.offersCopy(store.page!.engine("codex")!))
        try await store.startCopy("claude")
        #expect(store.copy?.engine == "claude")
        #expect(store.copy?.keepInstructions == false)
        try await store.applyCopy()
        #expect(api.calls.contains("copyToShared claude instructions=true"))
        #expect(store.copy == nil)
        #expect(
            store.done
                == CopyDone(
                    engine: "claude", summary: "Copied to Shared: 2 skills added.",
                    undoID: "backup-1"))
        let after = store.page!.engine("claude")!
        #expect(!store.offersCopy(after))
        #expect(store.headerNote(after) == "Shared matches Claude")
        #expect(store.headerNote(store.page!.engine("codex")!) == nil)
        try await store.undoCopy()
        #expect(api.calls.contains("undoCopy backup-1"))
        #expect(store.done == nil)
        try await store.undoCopy()
        try await store.applyCopy()
        #expect(api.calls.filter { $0.hasPrefix("copyToShared") }.count == 1)
    }

    @Test func keepingInstructionsCopiesTheRest() async throws {
        let store = try await loaded()
        try await store.startCopy("claude")
        store.setKeepInstructions(true)
        try await store.applyCopy()
        #expect(api.calls.contains("copyToShared claude instructions=false"))
        // Nothing to replace sends false too.
        api.set { $0.copyPreview.instructions = nil }
        try await store.startCopy("claude")
        #expect(store.done == nil)
        try await store.applyCopy()
        #expect(api.calls.last == "copyToShared claude instructions=false")
    }

    @Test func comparesTheTwoInstructionsFiles() async throws {
        let store = try await loaded()
        try await store.toggleCompare()
        api.set {
            $0.configFiles["/Users/x/.claude/CLAUDE.md"] = ConfigFile(
                path: "/Users/x/.claude/CLAUDE.md", text: "claude's", version: "c")
            $0.configFiles["/Users/x/.codex/AGENTS.md"] = ConfigFile(
                path: "/Users/x/.codex/AGENTS.md", text: "shared", version: "s")
        }
        try await store.startCopy("claude")
        try await store.toggleCompare()
        #expect(store.copy?.compare == CopyCompare(engine: "claude's", shared: "shared"))
        try await store.toggleCompare()
        #expect(store.copy?.compare == nil)
        store.cancelCopy()
        #expect(store.copy == nil)
    }

    @Test func foldingTheEngineClosesItsPopup() async throws {
        let store = try await loaded()
        try await store.startCopy("claude")
        store.toggleEngine("claude")
        #expect(store.copy == nil)
        store.toggleEngine("claude")
        try await store.startCopy("claude")
        store.openEngine("claude")
        #expect(store.copy != nil)
    }

    @Test func opensFilesInTheEditor() async throws {
        let store = try await loaded()
        api.set {
            $0.configFiles["/a"] = ConfigFile(path: "/a", text: "x", version: "1")
        }
        try await store.edit(path: "/a", title: "Instructions", note: "used by Claude")
        #expect(store.editor?.text == "x")
        #expect(store.editor?.title == "Instructions")
        store.closeEditor()
        #expect(store.editor == nil)
    }

    @Test func managesAProjectsItems() async throws {
        let store = ConfigurationStore(api: api)
        api.set {
            $0.repoConfigurations["nest"] = RepoConfiguration(
                instructions: [ConfigFileRef(path: "/r/CLAUDE.md", exists: true)], skills: [],
                mcpServers: [])
        }
        try await store.loadRepo("nest")
        #expect(store.repos["nest"]?.instructions.count == 1)
        try await store.saveRepoServer(
            "nest", "db", MCPServerSpec(transport: .stdio, command: "npx db"))
        #expect(store.repos["nest"]?.mcpServers.map(\.name) == ["db"])
        try await store.deleteRepoServer("nest", "db")
        #expect(store.repos["nest"]?.mcpServers.isEmpty == true)
        #expect(try await store.createRepoSkill("nest", name: "No", description: "") == false)
        #expect(try await store.createRepoSkill("nest", name: "deploy", description: " x "))
        #expect(api.calls.contains("createRepoSkill nest deploy x"))
        #expect(store.repos["nest"]?.skills.map(\.name) == ["deploy"])
    }

    @Test func managesCodexPluginsAndMarketplaces() async throws {
        let store = ConfigurationStore(api: api)
        api.set {
            $0.codexPlugins = [
                CodexPlugin(id: "figma@openai", name: "figma", marketplace: "openai"),
                CodexPlugin(id: "linear@openai", name: "linear", installed: true),
            ]
        }
        try await store.installCodexPlugin("figma@openai")
        #expect(store.codexPlugins == nil)
        try await store.loadCodexPlugins()
        #expect(store.codexPlugins?.count == 2)
        try await store.loadCodexPlugins(query: "fig")
        #expect(store.codexQuery == "fig")
        #expect(store.codexPlugins?.map(\.name) == ["figma"])
        try await store.uninstallCodexPlugin("figma@openai")
        #expect(store.codexPlugins?.first?.installed == false)
        #expect(api.calls.last == "codexPlugins fig")

        #expect(try await store.addCodexMarketplace("  ") == false)
        #expect(try await store.addCodexMarketplace(" openai/plugins "))
        #expect(store.codexMarketplaces.map(\.name) == ["openai/plugins"])
        try await store.removeCodexMarketplace("openai/plugins")
        #expect(store.codexMarketplaces.isEmpty)
        #expect(store.busy.isEmpty)
    }

    @Test func aLaterSearchWins() async throws {
        let store = ConfigurationStore(api: api)
        api.set { $0.codexPlugins = [CodexPlugin(id: "a", name: "alpha")] }
        let (gate, open) = AsyncStream<Void>.makeStream()
        api.set { $0.gates["codexPlugins al"] = gate }
        let slow = Task { try await store.loadCodexPlugins(query: "al") }
        while store.codexQuery != "al" { await Task.yield() }
        try await store.loadCodexPlugins(query: "")
        open.finish()
        try await slow.value
        #expect(store.codexQuery == "")
        #expect(store.codexPlugins?.count == 1)
    }

    @Test func refreshesWhatChangedOnDisk() async throws {
        let store = ConfigurationStore(api: api)
        // Nothing is read for a page or project not shown.
        try await store.refresh(repo: nil)
        try await store.refresh(repo: "nest")
        #expect(api.calls.isEmpty)
        try await store.load()
        try await store.loadRepo("nest")
        api.set { $0.configuration.engines.removeLast() }
        try await store.refresh(repo: nil)
        #expect(store.page?.engines.count == 1)
        api.set {
            $0.repoConfigurations["nest"] = RepoConfiguration(
                instructions: [], skills: [],
                mcpServers: [MCPServerEntry(name: "db", summary: "x", transport: .stdio)])
        }
        try await store.refresh(repo: "nest")
        #expect(store.repos["nest"]?.mcpServers.count == 1)
        api.set { $0.configFiles["/a"] = ConfigFile(path: "/a", text: "x", version: "1") }
        try await store.edit(path: "/a", title: "A")
        api.set { $0.configFiles["/a"] = ConfigFile(path: "/a", text: "y", version: "2") }
        try await store.refresh(repo: nil)
        #expect(store.editor?.text == "y")
    }

    @Test func liveEventsReadTheChangeAgain() async throws {
        let store = try await loaded()
        api.set { $0.configuration.engines.removeLast() }
        store.apply(
            Fixture.event(EventType.configurationChanged, #"{"scope": "user", "repo": null}"#))
        while store.page?.engines.count != 1 { await Task.yield() }
        api.set { $0.configuration = Fixture.configurationPage }
        store.apply(
            Fixture.event(
                EventType.accountCodex,
                #"{"signed_in": true, "checked_at": "2026-10-20T10:00:00Z"}"#))
        while store.page?.engines.count != 2 { await Task.yield() }
        let before = api.calls.count
        store.apply(Fixture.event("daemon.started", "{}"))
        #expect(api.calls.count == before)
    }
}
