import NestKit
import SwiftUI

/// The tabs of Settings > Extensions.
enum ExtensionsTab: Hashable {
    case plugins, connections
}

/// Claude Code on this Mac, its plugins, skills and marketplaces, and the connections
/// agents can reach (B81). Plugins change through Claude Code's own commands.
struct ExtensionsPage: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        ClaudeCodeSection()
        SettingsTabs(
            tabs: [(ExtensionsTab.plugins, "Skills and plugins"), (.connections, "Connections")],
            selection: shell.extensionsTab
        ) { shell.extensionsTab = $0 }
        .padding(.top, 14)
        switch shell.extensionsTab {
        case .plugins: PluginsTab()
        case .connections: ConnectorsList()
        }
    }
}

private struct ClaudeCodeSection: View {
    @Environment(Shell.self) private var shell
    @State private var confirming = false

    var body: some View {
        let extensions = shell.model.extensions
        let status = extensions.claudeCode
        SettingsSection(title: "Claude Code") {
            SettingsRow(label: "On this Mac") {
                if let status {
                    if status.installed {
                        SettingsValue(text: status.version ?? "Installed")
                        if let path = status.path {
                            SettingsValue(text: path, mono: true)
                        }
                    } else if extensions.isInstalling {
                        ProgressView().controlSize(.small)
                        SettingsValue(text: extensions.install?.message ?? "Installing")
                    } else {
                        SettingsValue(text: "Not installed")
                        Button("Install Claude Code") { confirming = true }
                            .buttonStyle(.nest(.primary))
                    }
                } else {
                    SettingsValue(text: "-")
                }
            }
            SettingsRow(label: "Agents use") {
                SettingsValue(text: status.map { "Built-in \($0.bundledVersion)" } ?? "-")
            }
            if let install = extensions.install, install.state == .failed {
                SettingsFailure(text: "Installing failed: \(install.message ?? "no reason given")")
            }
        }
        .task { try? await extensions.loadClaudeCode() }
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
            Text("Nest runs Anthropic's installer from claude.ai/install.sh on this Mac.")
        }
    }
}

private struct PluginsTab: View {
    @Environment(Shell.self) private var shell
    @State private var removing: InstalledPlugin?

    var body: some View {
        let extensions = shell.model.extensions
        SettingsSection(title: "Plugins", bare: true) {
            VStack(alignment: .leading, spacing: 0) {
                if let plugins = extensions.plugins, plugins.isEmpty {
                    EmptyLine(text: "No plugins installed")
                }
                ForEach(extensions.plugins ?? []) { plugin in
                    SettingsListRow(
                        title: plugin.name,
                        detail: [
                            plugin.description, plugin.version.map { "v\($0)" }, plugin.marketplace,
                        ]
                        .compactMap { $0 }.joined(separator: " · ")
                    ) {
                        SettingsBadge(text: String(plugin.name.prefix(2)).uppercased())
                    } trailing: {
                        Switch(isOn: plugin.enabled) {
                            shell.settingsChange("Could not change \(plugin.name)") {
                                try await extensions.setEnabled(plugin, !plugin.enabled)
                            }
                        }
                        .disabled(extensions.busy.contains(plugin.id))
                        .accessibilityLabel(plugin.name)
                        Button("Remove") { removing = plugin }
                            .buttonStyle(.nest(.danger))
                            .disabled(extensions.busy.contains(plugin.id))
                    }
                }
            }
            .overlay(alignment: .top) { Separator() }
        }
        if !extensions.skills.isEmpty {
            SettingsSection(title: "Skills", bare: true) {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(extensions.skills) { skill in
                        SettingsListRow(title: skill.name, detail: skill.description ?? skill.path)
                        {
                            SettingsBadge(symbol: "star")
                        } trailing: {
                            EmptyView()
                        }
                    }
                }
                .overlay(alignment: .top) { Separator() }
            }
        }
        BrowseSection()
        MarketplacesSection()
            .task { try? await extensions.loadInstalled() }
            .confirmationDialog(
                "Remove \(removing?.name ?? "this plugin")?", isPresented: removeBinding,
                titleVisibility: .visible
            ) {
                Button("Remove", role: .destructive) {
                    if let plugin = removing {
                        shell.settingsChange("Could not remove \(plugin.name)") {
                            try await extensions.uninstallPlugin(plugin.id)
                        }
                    }
                    removing = nil
                }
                Button("Cancel", role: .cancel) { removing = nil }
            } message: {
                Text("Claude Code uninstalls it. Agents stop using it when they next start.")
            }
    }

    private var removeBinding: Binding<Bool> {
        Binding(get: { removing != nil }, set: { if !$0 { removing = nil } })
    }
}

/// Browse: the plugins the marketplaces offer, each with what it brings, and Install.
private struct BrowseSection: View {
    @Environment(Shell.self) private var shell
    @State private var open: String?
    @State private var installing: AvailablePlugin?

    var body: some View {
        let extensions = shell.model.extensions
        SettingsSection(title: "Browse", bare: true) {
            if let available = extensions.available {
                VStack(alignment: .leading, spacing: 0) {
                    if available.isEmpty {
                        EmptyLine(text: "The marketplaces offer no plugins")
                    }
                    ForEach(available) { plugin in
                        AvailableRow(
                            plugin: plugin, open: open == plugin.id,
                            toggle: { toggle(plugin) }, install: { installing = plugin })
                    }
                }
                .overlay(alignment: .top) { Separator() }
            } else {
                Button("Browse plugins") {
                    shell.settingsChange("Could not list the marketplaces' plugins") {
                        try await extensions.loadAvailable()
                    }
                }
                .buttonStyle(.nest(.primary))
            }
        }
        .confirmationDialog(
            "Install \(installing?.name ?? "this plugin")?", isPresented: installBinding,
            titleVisibility: .visible
        ) {
            Button("Install") {
                if let plugin = installing {
                    shell.settingsChange("Could not install \(plugin.name)") {
                        try await extensions.installPlugin(plugin.id)
                    }
                }
                installing = nil
            }
            Button("Cancel", role: .cancel) { installing = nil }
        } message: {
            Text(
                "Plugins can run code on this Mac. Install only plugins from sources you trust.")
        }
    }

    private var installBinding: Binding<Bool> {
        Binding(get: { installing != nil }, set: { if !$0 { installing = nil } })
    }

    private func toggle(_ plugin: AvailablePlugin) {
        if open == plugin.id {
            open = nil
            return
        }
        open = plugin.id
        let extensions = shell.model.extensions
        if extensions.details[plugin.id] == nil {
            shell.settingsChange("Could not read \(plugin.name)") {
                try await extensions.loadDetails(plugin.id)
            }
        }
    }
}

private struct AvailableRow: View {
    let plugin: AvailablePlugin
    let open: Bool
    let toggle: () -> Void
    let install: () -> Void
    @Environment(Shell.self) private var shell

    var body: some View {
        let extensions = shell.model.extensions
        VStack(alignment: .leading, spacing: 0) {
            SettingsListRow(
                title: plugin.name,
                detail: [plugin.description, plugin.marketplace].compactMap { $0 }
                    .joined(separator: " · ")
            ) {
                SettingsBadge(text: String(plugin.name.prefix(2)).uppercased())
            } trailing: {
                Button(open ? "Hide details" : "Details", action: toggle)
                    .buttonStyle(.nest(.plain))
                if plugin.installed {
                    StatusLabel(tone: .review, label: "Installed")
                } else {
                    Button("Install", action: install)
                        .buttonStyle(.nest(.soft))
                        .disabled(extensions.busy.contains(plugin.id))
                }
            }
            if open {
                VStack(alignment: .leading, spacing: 4) {
                    if let details = extensions.details[plugin.id] {
                        if let components = details.components {
                            let summary = components.summary
                            Text(
                                summary.isEmpty
                                    ? "Brings nothing Claude Code lists"
                                    : summary.joined(separator: ", "))
                            ForEach(
                                [
                                    components.skills, components.agents, components.mcpServers,
                                ].filter { !$0.names.isEmpty }, id: \.self
                            ) { component in
                                Text(component.names.joined(separator: ", "))
                                    .font(.mono(TypeSize.meta))
                                    .foregroundStyle(Palette.t3)
                            }
                        } else {
                            Text("Its contents show once it is installed")
                        }
                        Text("Source: \(details.source)")
                            .font(.mono(TypeSize.meta))
                            .textSelection(.enabled)
                    } else {
                        ProgressView().controlSize(.small)
                    }
                }
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t2)
                .padding(.leading, 36)
                .padding(.vertical, 8)
                .overlay(alignment: .bottom) { Separator() }
            }
        }
    }
}

private struct MarketplacesSection: View {
    @Environment(Shell.self) private var shell
    @State private var source = ""
    @State private var removing: PluginMarketplace?

    var body: some View {
        let extensions = shell.model.extensions
        SettingsSection(title: "Marketplaces", bare: true) {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(extensions.marketplaces) { marketplace in
                    SettingsListRow(
                        title: marketplace.name, detail: marketplace.source, mono: true
                    ) {
                        SettingsBadge(symbol: "shippingbox")
                    } trailing: {
                        Button("Remove") { removing = marketplace }
                            .buttonStyle(.nest(.danger))
                            .disabled(extensions.busy.contains(marketplace.name))
                    }
                }
            }
            .overlay(alignment: .top) { Separator() }
            HStack(spacing: 6) {
                CardField(placeholder: "URL, path or GitHub repo", text: $source, submit: add)
                Button("Add", action: add)
                    .buttonStyle(.nest(.soft))
                    .disabled(source.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .padding(.top, 10)
        }
        .confirmationDialog(
            "Remove \(removing?.name ?? "this marketplace")?", isPresented: removeBinding,
            titleVisibility: .visible
        ) {
            Button("Remove", role: .destructive) {
                if let marketplace = removing {
                    shell.settingsChange("Could not remove \(marketplace.name)") {
                        try await extensions.removeMarketplace(marketplace.name)
                    }
                }
                removing = nil
            }
            Button("Cancel", role: .cancel) { removing = nil }
        } message: {
            Text("Its plugins can no longer be installed from it.")
        }
    }

    private var removeBinding: Binding<Bool> {
        Binding(get: { removing != nil }, set: { if !$0 { removing = nil } })
    }

    private func add() {
        let text = source
        let extensions = shell.model.extensions
        shell.settingsChange("Could not add the marketplace") {
            if try await extensions.addMarketplace(text) {
                source = ""
            }
        }
    }
}

private struct EmptyLine: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.ui(TypeSize.ui))
            .foregroundStyle(Palette.t3)
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .overlay(alignment: .bottom) { Separator() }
    }
}
