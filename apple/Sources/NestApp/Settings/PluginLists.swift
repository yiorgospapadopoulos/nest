import NestKit
import SwiftUI

/// Claude's installed plugins in Settings > Configuration (B97, from B81's Extensions):
/// each with its switch, removed from its context menu. Plugins change through Claude
/// Code's own commands.
struct ClaudePluginRows: View {
    @Environment(Shell.self) private var shell
    @State private var removing: InstalledPlugin?

    var body: some View {
        let extensions = shell.model.extensions
        VStack(alignment: .leading, spacing: 0) {
            if let plugins = extensions.plugins, plugins.isEmpty {
                ConfigSubRow { Text("No plugins installed").foregroundStyle(Palette.t3) }
            }
            ForEach(extensions.plugins ?? []) { plugin in
                ConfigSubRow {
                    HStack(spacing: 0) {
                        Text(plugin.name).font(.ui(TypeSize.ui, .medium))
                        Text(" · \(plugin.marketplace)").foregroundStyle(Palette.t3)
                    }
                    .lineLimit(1)
                    .layoutPriority(1)
                    Text(plugin.description ?? "")
                        .foregroundStyle(Palette.t3)
                        .lineLimit(1)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    Switch(isOn: plugin.enabled, accent: true) {
                        shell.settingsChange("Could not change \(plugin.name)") {
                            try await extensions.setEnabled(plugin, !plugin.enabled)
                        }
                    }
                    .disabled(extensions.busy.contains(plugin.id))
                    .accessibilityLabel(plugin.name)
                }
                .contextMenu {
                    Button("Remove \(plugin.name)") { removing = plugin }
                }
            }
        }
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
struct BrowseSection: View {
    @Environment(Shell.self) private var shell
    @State private var open: String?
    @State private var installing: AvailablePlugin?
    /// How many rows are drawn: drawing every marketplace plugin at once made Settings lag.
    @State private var shown = BrowseSection.page
    /// Searches every plugin the marketplaces offer, not only the rows drawn.
    @State private var query = ""

    private static let page = 10

    var body: some View {
        let extensions = shell.model.extensions
        SettingsSection(title: "Browse", bare: true) {
            if let all = extensions.available {
                let available = all.matching(query)
                VStack(alignment: .leading, spacing: 0) {
                    if !all.isEmpty {
                        TextField("Search \(all.count) plugins", text: $query)
                            .textFieldStyle(.plain)
                            .font(.ui(TypeSize.ui))
                            .padding(.horizontal, 8)
                            .frame(height: 24)
                            .background(Palette.soft, in: .rounded(Radius.button))
                            .padding(.vertical, 10)
                            .onChange(of: query) { shown = BrowseSection.page }
                            .accessibilityLabel("Search plugins")
                    }
                    if all.isEmpty {
                        EmptyLine(text: "The marketplaces offer no plugins")
                    } else if available.isEmpty {
                        EmptyLine(text: "No plugins match")
                    }
                    ForEach(available.prefix(shown)) { plugin in
                        AvailableRow(
                            plugin: plugin, open: open == plugin.id,
                            toggle: { toggle(plugin) }, install: { installing = plugin })
                    }
                    if available.count > shown {
                        Button("Load more (\(available.count - shown) left)") {
                            shown += BrowseSection.page
                        }
                        .buttonStyle(.nest(.plain))
                        .padding(.top, 10)
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
                        Fireflies()
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

struct MarketplacesSection: View {
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

struct EmptyLine: View {
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
