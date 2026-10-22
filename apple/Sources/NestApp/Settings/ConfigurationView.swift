import AppKit
import NestKit
import SwiftUI

/// Settings > Configuration (B97): what the agents read. Shared instructions, skills and
/// MCP servers on top, then a fold-open section per signed-in engine. The engines' own
/// files are the only source of truth; the page follows them live.
struct ConfigurationView: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.configuration
        VStack(alignment: .leading, spacing: 0) {
            Text(ConfigurationText.intro)
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t2)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 14)
            if let page = store.page {
                SharedSection(page: page)
                ConfigLabel(text: "Engines")
                ForEach(page.engines) { engine in
                    EngineSection(engine: engine)
                }
            } else {
                Fireflies().padding(.vertical, 24)
            }
            if let footer = ConfigurationText.footer(
                signInOptional: shell.model.local.signInOptional)
            {
                Text(footer)
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                    .padding(.top, 8)
            }
        }
        .task { try? await store.load() }
    }
}

// MARK: Shared

private struct SharedSection: View {
    let page: ConfigurationPage
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.configuration
        let shared = page.shared
        let skills = shared.skills.items
        let codexIn = page.engine("codex") != nil
        ConfigLabel(text: "Shared")
        ConfigRow {
            ConfigIcon(symbol: "doc.text")
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text("Instructions").font(.ui(TypeSize.ui, .medium))
                    Text(fileName(shared.instructions.path)).font(.mono(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                }
                let path = Text(ConfigurationText.shortPath(shared.instructions.path))
                    .font(.mono(TypeSize.meta))
                if let holder = rulesElsewhere {
                    Text(
                        "Empty. Your rules are in \(holder.name)'s CLAUDE.md; copy them here to share them with every engine. \(path)"
                    )
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                } else {
                    Text("Read by Codex as it is; Claude's CLAUDE.md imports it. \(path)")
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                }
            }
            Spacer(minLength: 8)
            Button("Edit") {
                shell.editConfiguration(
                    shared.instructions.path, title: "Instructions",
                    note: "used by Claude and Codex")
            }
            .buttonStyle(.nest())
            OpenMenu(path: shared.instructions.path)
        }
        ConfigRow {
            ConfigIcon(symbol: "star")
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text("Skills").font(.ui(TypeSize.ui, .medium))
                    Text("\(skills.count)").foregroundStyle(Palette.t3).monospacedDigit()
                }
                let folder = Text(ConfigurationText.shortPath(shared.skills.folder))
                    .font(.mono(TypeSize.meta))
                Text("One folder for every engine. \(folder)")
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
            }
            Spacer(minLength: 8)
            Button("New skill") { shell.configurationForm = .skill(repo: nil) }
                .buttonStyle(.nest())
            Button("Open folder") { LocalOpen.folder(shared.skills.folder) }
                .buttonStyle(.nest())
        }
        ForEach(ConfigurationText.shownSkills(skills, showAll: store.showsAllSkills)) { skill in
            SkillRow(skill: skill, codexIn: codexIn)
        }
        if let toggle = ConfigurationText.skillsToggle(
            count: skills.count, showAll: store.showsAllSkills)
        {
            ConfigSubRow {
                Button(toggle) {
                    withAnimation(.smooth(duration: 0.2)) { store.showsAllSkills.toggle() }
                }
                .buttonStyle(.plain)
                .foregroundStyle(Palette.t2)
                .pointerStyle(.link)
            }
        }
        ConfigRow {
            ConfigIcon(symbol: "server.rack")
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text("MCP servers").font(.ui(TypeSize.ui, .medium))
                    Text("\(shared.mcpServers.count)").foregroundStyle(Palette.t3)
                        .monospacedDigit()
                }
                Text("Set up once; Nest writes each into every engine's own config.")
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
            }
            Spacer(minLength: 8)
            Button("Add server") {
                shell.configurationForm = .server(MCPServerForm(), repo: nil)
            }
            .buttonStyle(.nest())
        }
        ForEach(shared.mcpServers) { server in
            ServerRow(server: server)
        }
    }

    private func fileName(_ path: String) -> String {
        URL(fileURLWithPath: path).lastPathComponent
    }

    /// The engine still holding its own rules while the shared file is empty, if any.
    private var rulesElsewhere: EngineConfiguration? {
        let instructions = page.shared.instructions
        let empty = !instructions.exists || instructions.version == Self.emptyFileHash
        guard empty else { return nil }
        return page.engines.first { $0.id == "claude" && $0.missingFromShared.instructions }
    }

    /// sha256 of zero bytes, the version the daemon gives an empty file.
    private static let emptyFileHash =
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
}

private struct SkillRow: View {
    let skill: ConfigSkill
    let codexIn: Bool
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.configuration
        ConfigSubRow {
            Text(skill.name).font(.ui(TypeSize.ui, .medium)).lineLimit(1).layoutPriority(1)
            Text(ConfigurationText.skillDetail(skill))
                .foregroundStyle(Palette.t3)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
            if codexIn, let error = skill.codexError {
                ConfigChip(text: "not loaded by Codex")
                    .help(error)
            }
            ConfigChip(text: ConfigurationText.skillChip(skill))
            if codexIn, ConfigurationText.showsCodexSwitch(skill) {
                let enabled = skill.codexEnabled == true
                HStack(spacing: 5) {
                    Text("Codex").foregroundStyle(Palette.t3)
                    Switch(isOn: enabled, accent: true) {
                        shell.settingsChange("Could not change \(skill.name) for Codex") {
                            try await store.setCodexEnabled(skill, !enabled)
                        }
                    }
                    .accessibilityLabel("Load \(skill.name) in Codex")
                }
            }
            if skill.source == .engineOnly {
                Button("Make shared") {
                    shell.settingsChange("Could not share \(skill.name)") {
                        try await store.makeShared(skill)
                    }
                }
                .buttonStyle(.nest())
                .disabled(store.busy.contains("skill:\(skill.name)"))
            } else if skill.readOnly {
                Text("read only").foregroundStyle(Palette.t3)
                Button("Open") { LocalOpen.defaultApp(skill.path) }
                    .buttonStyle(.nest(.plain))
            } else {
                Button("Edit") {
                    shell.editConfiguration(skill.path, title: skill.name, note: "skill")
                }
                .buttonStyle(.nest())
            }
        }
        .contextMenu {
            Button("Reveal in Finder") { LocalOpen.reveal(skill.path) }
            if skill.source == .yours {
                Button("Remove \(skill.name)") {
                    shell.settingsChange("Could not remove \(skill.name)") {
                        try await store.deleteSkill(skill.name)
                    }
                }
            }
        }
    }
}

private struct ServerRow: View {
    let server: MCPServerEntry
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.configuration
        ConfigSubRow {
            Text(server.name).font(.ui(TypeSize.ui, .medium)).lineLimit(1).layoutPriority(1)
            Text(server.summary)
                .font(.mono(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .lineLimit(1)
                .truncationMode(.middle)
                .frame(maxWidth: .infinity, alignment: .leading)
            if server.convertible {
                ForEach(ConfigurationText.serverEngines(server), id: \.self) { engine in
                    ConfigChip(text: engine)
                }
            } else {
                ConfigChip(text: "Claude only")
                    .help(server.reason ?? "Codex cannot use this server")
                if let reason = server.reason {
                    Text(reason).foregroundStyle(Palette.t3).lineLimit(1)
                }
            }
            Button("Edit") {
                let name = server.name
                shell.settingsChange("Could not read \(name)") {
                    let spec = try await store.server(name)
                    shell.configurationForm = .server(
                        MCPServerForm(name: name, spec: spec), repo: nil)
                }
            }
            .buttonStyle(.nest())
        }
    }
}

// MARK: Engines

private struct EngineSection: View {
    let engine: EngineConfiguration
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent

    var body: some View {
        let store = shell.model.configuration
        let open = store.openEngine == engine.id
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 9) {
                Button {
                    withAnimation(.smooth(duration: 0.2)) { store.toggleEngine(engine.id) }
                } label: {
                    HStack(spacing: 9) {
                        Image(systemName: Icon.chevron)
                            .font(.system(size: 8, weight: .semibold))
                            .foregroundStyle(Palette.t3)
                            .rotationEffect(.degrees(open ? 0 : -90))
                        EngineMark(provider: engine.id, size: 15)
                        Text(engine.name).font(.ui(TypeSize.ui, .medium))
                        if let account = engine.account {
                            Text(account).font(.ui(TypeSize.meta)).foregroundStyle(Palette.t3)
                                .lineLimit(1)
                                .fixedSize()
                        }
                        Spacer(minLength: 8)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .pointerStyle(.link)
                .accessibilityLabel("\(engine.name), \(engine.account ?? "")")
                .accessibilityValue(open ? "Expanded" : "Collapsed")
                if store.offersCopy(engine) {
                    Button(ConfigurationText.copyTitle(engine.id)) {
                        shell.settingsChange("Could not read what the copy would do") {
                            try await store.startCopy(engine.id)
                        }
                    }
                    .buttonStyle(.nest(.primary))
                }
            }
            .padding(.horizontal, 14)
            .frame(height: 44)
            // What Shared lacks goes under the header, so the account is never cut short.
            if open, let note = store.headerNote(engine) {
                Text(note)
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t2)
                    .lineLimit(1)
                    .truncationMode(.tail)
                    .padding(.leading, 55)
                    .padding(.trailing, 14)
                    .padding(.top, -8)
                    .padding(.bottom, 8)
            }
            if open {
                VStack(alignment: .leading, spacing: 0) {
                    if let done = store.done, done.engine == engine.id {
                        HStack(spacing: 10) {
                            Image(systemName: "checkmark.circle.fill")
                                .foregroundStyle(accent.fill)
                            Text(done.summary)
                                .fixedSize(horizontal: false, vertical: true)
                            Spacer(minLength: 8)
                            Button("Undo") {
                                shell.settingsChange("Could not undo the copy") {
                                    try await store.undoCopy()
                                }
                            }
                            .buttonStyle(.nest())
                        }
                        .font(.ui(TypeSize.ui))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 8)
                        .background(Palette.soft, in: .rounded(8))
                        .padding(.bottom, 8)
                    }
                    EngineLine(engine: engine)
                    UsesSharedRow(engine: engine)
                    ForEach(engine.items) { item in
                        EngineItemRow(engine: engine, item: item)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 10)
            }
        }
        .background(Palette.soft.opacity(0.35), in: .rounded(10))
        .overlay(RoundedRectangle.rounded(10).strokeBorder(Palette.divider, lineWidth: 1))
        .padding(.bottom, 10)
    }
}

/// The version Nest brings, a CLI found on the Mac, and the config folder in use.
private struct EngineLine: View {
    let engine: EngineConfiguration
    @Environment(Shell.self) private var shell
    @State private var confirming = false

    var body: some View {
        let extensions = shell.model.extensions
        ConfigRow {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text("Engine").font(.ui(TypeSize.ui, .medium))
                    Text(ConfigurationText.engineLine(engine)).foregroundStyle(Palette.t3)
                }
                Text(ConfigurationText.shortPath(engine.configFolder))
                    .font(.mono(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
            }
            Spacer(minLength: 8)
            if let line = ConfigurationText.standaloneLine(engine) {
                Text(line)
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t2)
                    .lineLimit(1)
                    .truncationMode(.middle)
            } else if engine.id == "claude" {
                if extensions.isInstalling {
                    Fireflies()
                    Text(extensions.install?.message ?? "Installing")
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                } else {
                    Button("Install Claude Code") { confirming = true }
                        .buttonStyle(.nest(.plain))
                }
            }
        }
        .confirmationDialog(
            "Install Claude Code?", isPresented: $confirming, titleVisibility: .visible
        ) {
            Button("Install") {
                shell.settingsChange("Could not install Claude Code") {
                    try await extensions.installClaudeCode()
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(
                "Nest runs Anthropic's installer from claude.ai/install.sh, so claude also works in a terminal."
            )
        }
        if let install = extensions.install, install.state == .failed, engine.id == "claude" {
            SettingsFailure(text: "Installing failed: \(install.message ?? "no reason given")")
        }
    }
}

private struct UsesSharedRow: View {
    let engine: EngineConfiguration
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.configuration
        let captions = SharedItem.allCases.compactMap {
            engine.usesShared[$0].fixed ? ConfigurationText.fixedCaption(engine.id, $0) : nil
        }
        ConfigRow {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 18) {
                    Text("Uses shared").font(.ui(TypeSize.ui, .medium))
                    ForEach(SharedItem.allCases, id: \.self) { item in
                        let value = engine.usesShared[item]
                        HStack(spacing: 6) {
                            Switch(isOn: value.on, accent: true) {
                                shell.settingsChange("Could not change \(item.title)") {
                                    try await store.setUsesShared(
                                        engine: engine.id, item, on: !value.on)
                                }
                            }
                            .disabled(
                                value.fixed
                                    || store.busy.contains(
                                        "uses:\(engine.id):\(item.rawValue)")
                            )
                            .accessibilityLabel("\(engine.name) uses shared \(item.title)")
                            Text(item.title).foregroundStyle(Palette.t2)
                        }
                        .help(ConfigurationText.fixedCaption(engine.id, item) ?? "")
                    }
                }
                if !captions.isEmpty {
                    Text(captions.joined(separator: ". ") + ".")
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                }
            }
            Spacer(minLength: 0)
        }
    }
}

/// One of the engine's own items: plugins and connectors fold open in place, the rest
/// open their file in the editor or their folder in Finder.
private struct EngineItemRow: View {
    let engine: EngineConfiguration
    let item: EngineItem
    @Environment(Shell.self) private var shell

    var body: some View {
        let key = "\(engine.id):\(item.kind.rawValue)"
        let foldable = item.kind == .plugins || item.kind == .connectors
        let open = foldable && shell.configurationFolds.contains(key)
        HStack(spacing: 10) {
            if foldable {
                Button {
                    withAnimation(.smooth(duration: 0.2)) {
                        if open {
                            shell.configurationFolds.remove(key)
                        } else {
                            shell.configurationFolds.insert(key)
                        }
                    }
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: Icon.chevron)
                            .font(.system(size: 8, weight: .semibold))
                            .foregroundStyle(Palette.t3)
                            .rotationEffect(.degrees(open ? 0 : -90))
                            .frame(width: 10)
                        title
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .pointerStyle(.link)
                .accessibilityValue(open ? "Expanded" : "Collapsed")
            } else {
                Color.clear.frame(width: 10, height: 1)
                title
            }
            Spacer(minLength: 8)
            if item.kind == .connectors {
                Text("Claude only").font(.ui(TypeSize.meta)).foregroundStyle(Palette.t3)
            }
            if let path = item.path {
                Text(ConfigurationText.shortPath(path))
                    .font(.mono(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Button(ConfigurationText.openTitle(item)) {
                    if item.folder {
                        LocalOpen.folder(path)
                    } else {
                        shell.editConfiguration(
                            path, title: ConfigurationText.itemTitle(item.kind),
                            note: "\(engine.name) only")
                    }
                }
                .buttonStyle(.nest())
            }
            if item.kind == .plugins {
                pluginButtons(key: key)
            }
        }
        .font(.ui(TypeSize.ui))
        .frame(minHeight: 38)
        .overlay(alignment: .top) { Separator() }
        if open {
            if item.kind == .connectors {
                ConnectorsList()
                    .padding(.leading, 30)
                    .padding(.bottom, 8)
            } else if engine.id == "claude" {
                ClaudePluginRows()
            } else {
                CodexPluginRows()
            }
        }
        if item.kind == .plugins {
            if shell.configurationFolds.contains("\(key):browse") {
                Group {
                    if engine.id == "claude" {
                        BrowseSection()
                    } else {
                        CodexBrowse()
                    }
                }
                .padding(.leading, 30)
                .padding(.bottom, 8)
            }
            if shell.configurationFolds.contains("\(key):marketplaces") {
                Group {
                    if engine.id == "claude" {
                        MarketplacesSection()
                    } else {
                        CodexMarketplaces()
                    }
                }
                .padding(.leading, 30)
                .padding(.bottom, 8)
            }
        }
    }

    private var title: some View {
        HStack(spacing: 6) {
            Text(ConfigurationText.itemTitle(item.kind)).font(.ui(TypeSize.ui, .medium))
            if let detail = ConfigurationText.itemDetail(item, engine: engine.id) {
                Text(detail).foregroundStyle(Palette.t3)
            }
        }
    }

    @ViewBuilder private func pluginButtons(key: String) -> some View {
        let markets =
            engine.id == "claude"
            ? shell.model.extensions.marketplaces.count
            : shell.model.configuration.codexMarketplaces.count
        foldButton("Browse", key: "\(key):browse")
        foldButton(
            markets > 0 ? "Marketplaces \(markets)" : "Marketplaces", key: "\(key):marketplaces")
    }

    private func foldButton(_ title: String, key: String) -> some View {
        let on = shell.configurationFolds.contains(key)
        return Button(title) {
            withAnimation(.smooth(duration: 0.2)) {
                if on {
                    shell.configurationFolds.remove(key)
                } else {
                    shell.configurationFolds.insert(key)
                }
            }
        }
        .buttonStyle(.nest(on ? .primary : .soft))
    }
}

// MARK: Codex plugins

private struct CodexPluginRows: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.configuration
        let installed = (store.codexPlugins ?? []).filter(\.installed)
        VStack(alignment: .leading, spacing: 0) {
            if store.codexPlugins != nil, installed.isEmpty {
                ConfigSubRow {
                    Text("No plugins of Codex's own").foregroundStyle(Palette.t3)
                }
            }
            ForEach(installed) { plugin in
                CodexPluginRow(plugin: plugin)
            }
        }
        .task {
            if store.codexPlugins == nil {
                try? await store.loadCodexPlugins()
            }
        }
    }
}

private struct CodexPluginRow: View {
    let plugin: CodexPlugin
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.configuration
        ConfigSubRow {
            HStack(spacing: 0) {
                Text(plugin.name).font(.ui(TypeSize.ui, .medium))
                if let marketplace = plugin.marketplace {
                    Text(" · \(marketplace)").foregroundStyle(Palette.t3)
                }
            }
            .lineLimit(1)
            .layoutPriority(1)
            Text(plugin.description ?? "")
                .foregroundStyle(Palette.t3)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
            if plugin.installed {
                Button("Remove") {
                    shell.settingsChange("Could not remove \(plugin.name)") {
                        try await store.uninstallCodexPlugin(plugin.id)
                    }
                }
                .buttonStyle(.nest(.danger))
                .disabled(store.busy.contains(plugin.id))
            } else {
                Button("Install") {
                    shell.settingsChange("Could not install \(plugin.name)") {
                        try await store.installCodexPlugin(plugin.id)
                    }
                }
                .buttonStyle(.nest())
                .disabled(store.busy.contains(plugin.id))
            }
        }
    }
}

private struct CodexBrowse: View {
    @Environment(Shell.self) private var shell
    @State private var query = ""

    var body: some View {
        let store = shell.model.configuration
        let offered = (store.codexPlugins ?? []).filter { !$0.installed }
        VStack(alignment: .leading, spacing: 0) {
            TextField("Search Codex's plugins", text: $query)
                .textFieldStyle(.plain)
                .font(.ui(TypeSize.ui))
                .padding(.horizontal, 8)
                .frame(height: 24)
                .background(Palette.soft, in: .rounded(Radius.button))
                .padding(.vertical, 10)
                .accessibilityLabel("Search Codex's plugins")
            if store.codexPlugins != nil, offered.isEmpty {
                EmptyLine(
                    text: query.isEmpty ? "The marketplaces offer no plugins" : "No plugins match")
            }
            ForEach(offered) { plugin in
                CodexPluginRow(plugin: plugin)
            }
        }
        .task(id: query) {
            try? await store.loadCodexPlugins(query: query)
        }
    }
}

private struct CodexMarketplaces: View {
    @Environment(Shell.self) private var shell
    @State private var source = ""

    var body: some View {
        let store = shell.model.configuration
        VStack(alignment: .leading, spacing: 0) {
            ForEach(store.codexMarketplaces) { marketplace in
                SettingsListRow(title: marketplace.name, detail: marketplace.path, mono: true) {
                    SettingsBadge(symbol: "shippingbox")
                } trailing: {
                    Button("Remove") {
                        shell.settingsChange("Could not remove \(marketplace.name)") {
                            try await store.removeCodexMarketplace(marketplace.name)
                        }
                    }
                    .buttonStyle(.nest(.danger))
                    .disabled(store.busy.contains(marketplace.name))
                }
            }
            HStack(spacing: 6) {
                CardField(placeholder: "URL, path or GitHub repo", text: $source, submit: add)
                Button("Add", action: add)
                    .buttonStyle(.nest())
                    .disabled(source.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .padding(.top, 10)
        }
        .task { try? await store.loadCodexMarketplaces() }
    }

    private func add() {
        let text = source
        let store = shell.model.configuration
        shell.settingsChange("Could not add the marketplace") {
            if try await store.addCodexMarketplace(text) {
                source = ""
            }
        }
    }
}

// MARK: Pieces

/// A small grey label over a part of the page.
struct ConfigLabel: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.ui(11, .semibold))
            .foregroundStyle(Palette.t2)
            .padding(.top, 22)
            .padding(.bottom, 6)
    }
}

/// A row of the page with a thin line over it.
struct ConfigRow<Content: View>: View {
    @ViewBuilder let content: () -> Content

    var body: some View {
        HStack(spacing: 12) { content() }
            .font(.ui(TypeSize.ui))
            .padding(.vertical, 8)
            .frame(minHeight: 46)
            .overlay(alignment: .top) { Separator() }
    }
}

/// A row under a row, indented: a skill, a server, a plugin.
struct ConfigSubRow<Content: View>: View {
    @ViewBuilder let content: () -> Content

    var body: some View {
        HStack(spacing: 10) { content() }
            .font(.ui(TypeSize.meta))
            .padding(.leading, 30)
            .frame(minHeight: 34)
            .overlay(alignment: .top) { Separator().opacity(0.6) }
    }
}

struct ConfigIcon: View {
    let symbol: String

    var body: some View {
        Image(systemName: symbol)
            .font(.system(size: 13))
            .foregroundStyle(Palette.t2)
            .frame(width: 18)
    }
}

/// A small quiet chip, such as "yours" or "Codex".
struct ConfigChip: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.ui(10.5))
            .foregroundStyle(Palette.t2)
            .lineLimit(1)
            .fixedSize()
            .padding(.horizontal, 7)
            .padding(.vertical, 2)
            .background(Palette.soft, in: Capsule())
    }
}

/// "Open in VS Code" with a menu for the default app and Finder.
struct OpenMenu: View {
    let path: String

    var body: some View {
        HStack(spacing: 1) {
            Button("Open in VS Code") { LocalOpen.vscode(path) }
                .buttonStyle(.nest())
            Menu {
                Button("Open in the default app") { LocalOpen.defaultApp(path) }
                Button("Reveal in Finder") { LocalOpen.reveal(path) }
            } label: {
                Image(systemName: Icon.chevron).font(.system(size: 8, weight: .semibold))
            }
            .menuStyle(.button)
            .buttonStyle(.nest(iconOnly: true))
            .menuIndicator(.hidden)
            .fixedSize()
            .accessibilityLabel("More ways to open")
        }
    }
}

/// Opens configuration files on this Mac, where the daemon is too.
enum LocalOpen {
    static let vscodeID = "com.microsoft.VSCode"

    @MainActor
    static func vscode(_ path: String) {
        let url = URL(fileURLWithPath: path)
        guard let app = NSWorkspace.shared.urlForApplication(withBundleIdentifier: vscodeID)
        else {
            NSWorkspace.shared.open(url)
            return
        }
        NSWorkspace.shared.open(
            [url], withApplicationAt: app, configuration: NSWorkspace.OpenConfiguration())
    }

    @MainActor
    static func defaultApp(_ path: String) {
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }

    @MainActor
    static func reveal(_ path: String) {
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
    }

    @MainActor
    static func folder(_ path: String) {
        NSWorkspace.shared.open(URL(fileURLWithPath: path, isDirectory: true))
    }
}

extension Shell {
    /// Opens a configuration file in the editor sheet.
    func editConfiguration(_ path: String, title: String, note: String? = nil) {
        let store = model.configuration
        settingsChange("Could not read \(title)") {
            try await store.edit(path: path, title: title, note: note)
        }
    }
}
