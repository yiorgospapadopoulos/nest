import NestKit
import SwiftUI

/// A selector that reads as plain text, highlights on hover and opens a list. Its title
/// truncates when the row is short of room; `tint` colours it instead of the greys, and
/// `chevron` adds a small one after it.
struct QuietMenu<Items: View>: View {
    let title: String
    let help: String
    var tint: Color?
    var chevron = false
    @ViewBuilder let items: () -> Items
    @State private var hovering = false
    @Environment(\.paneFit) private var fit

    var body: some View {
        Menu {
            items()
        } label: {
            HStack(spacing: 4) {
                Text(title)
                    .lineLimit(1)
                    .truncationMode(.tail)
                if chevron {
                    Image(systemName: Icon.chevron)
                        .font(.system(size: 8, weight: .semibold))
                }
            }
            .font(.ui(TypeSize.button))
            .foregroundStyle(tint ?? (hovering ? Palette.t1 : Palette.t2))
            .padding(.horizontal, fit.compact ? 4 : 6)
            .frame(height: Metrics.buttonHeight)
            .background(hovering ? Palette.soft : .clear, in: .rounded(Radius.button))
            .contentShape(Rectangle())
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .menuIndicator(.hidden)
        .fixedSize(horizontal: false, vertical: true)
        .onHover { hovering = $0 }
        .help(help)
        .accessibilityLabel("\(help): \(title)")
    }
}

/// A checkmarked menu item with a one-line description.
struct OptionItem: View {
    let title: String
    let detail: String
    let checked: Bool
    let pick: () -> Void

    var body: some View {
        Toggle(isOn: Binding(get: { checked }, set: { _ in pick() })) {
            Text(title)
            if !detail.isEmpty {
                Text(detail)
            }
        }
    }
}

/// The chat's model, one menu for both engines (B91): a new chat lists each engine's
/// models under its name, with its plan or that it is not signed in, and choosing a model
/// chooses its engine; a chat that exists lists only its own engine's.
struct ModelMenu: View {
    let chat: String
    let model: String?
    @Environment(Shell.self) private var shell
    @Environment(\.paneFit) private var fit

    var body: some View {
        let label = shell.catalog(forChat: chat).label(for: model)
        let provider = shell.provider(forChat: chat)
        QuietMenu(title: fit.compact ? PaneFit.shortModel(label) : label, help: "Model") {
            EngineModelItems(provider: provider, current: model, isDraft: shell.isDraft(chat)) {
                shell.setModel($0, on: $1, for: chat)
            }
        }
    }
}

/// Claude Code's model list with descriptions and a checkmark on the current model; a
/// model the list does not have shows only as the menu's title. Real models only (B94).
struct ModelItems: View {
    let current: String?
    let pick: (ModelInfo) -> Void
    @Environment(Shell.self) private var shell

    var body: some View {
        let agents = shell.agents.catalog
        Section("Model") {
            if agents.models.isEmpty {
                Button("Models unavailable") {}.disabled(true)
            }
            ForEach(agents.models) { info in
                OptionItem(
                    title: info.displayName, detail: info.description,
                    checked: agents.isSelected(info, current: current)
                ) { pick(info) }
            }
        }
    }
}

/// Every engine's models under its name with its plan or that it is not signed in (B91);
/// choosing one picks its engine too. A chat that exists (`isDraft` false) lists only its
/// own engine's. The composer's menu and the agent defaults' (B94).
struct EngineModelItems: View {
    /// Nil is Claude.
    let provider: String?
    let current: String?
    var isDraft = true
    let pick: (ModelInfo, String) -> Void
    @Environment(Shell.self) private var shell

    var body: some View {
        ForEach(
            shell.providers.modelSections(
                claude: shell.agents.catalog, provider: provider, isDraft: isDraft)
        ) { section in
            Section(section.title) {
                if !section.detail.isEmpty {
                    Text(section.detail)
                }
                if section.catalog.models.isEmpty {
                    Button("Models unavailable") {}.disabled(true)
                }
                ForEach(section.catalog.models) { info in
                    OptionItem(
                        title: info.displayName, detail: info.description,
                        checked: section.isSelected(info, provider: provider, model: current)
                    ) { pick(info, section.provider) }
                }
            }
        }
    }
}

struct EffortMenu: View {
    let chat: String
    let model: String?
    let effort: Effort?
    /// Open chats take a new effort from their next message on.
    let isOpen: Bool
    @Environment(Shell.self) private var shell
    @Environment(\.paneFit) private var fit

    var body: some View {
        let label = fit.compact ? effort?.shortLabel : effort?.label
        let catalog = shell.catalog(forChat: chat)
        let levels = catalog.thinkingLevels(for: model)
        QuietMenu(title: label ?? (levels.isEmpty ? "No thinking" : "Thinking"), help: "Thinking") {
            ThinkingItems(model: model, effort: effort, catalog: catalog) { level in
                shell.setEffort(level, for: chat)
            }
            if isOpen && !levels.isEmpty {
                Divider()
                Text("Applies from your next message")
            }
        }
    }
}

/// The model's own thinking levels, no default entry (B94).
struct ThinkingItems: View {
    let model: String?
    let effort: Effort?
    /// The chat's engine's models; nil for Claude Code's.
    var catalog: ModelCatalog?
    let pick: (Effort) -> Void
    @Environment(Shell.self) private var shell

    var body: some View {
        let catalog = catalog ?? shell.agents.catalog
        let levels = catalog.thinkingLevels(for: model)
        Section("Thinking") {
            if levels.isEmpty {
                Button("Not available for this model") {}.disabled(true)
            } else {
                ForEach(levels, id: \.self) { level in
                    OptionItem(title: level.label, detail: "", checked: effort == level) {
                        pick(level)
                    }
                }
            }
        }
    }
}

struct PermissionMenu: View {
    let chat: String
    let model: String?
    let mode: PermissionMode
    /// Bypass in the warning colour, as the empty workspace shows it.
    var warnsOnBypass = false
    @Environment(Shell.self) private var shell
    @Environment(\.paneFit) private var fit

    var body: some View {
        let label = fit.compact ? mode.shortLabel : mode.label
        let warns = warnsOnBypass && mode == .bypassPermissions
        QuietMenu(
            title: label, help: "Permission mode", tint: warns ? StatusTone.waiting.color : nil
        ) {
            PermissionItems(
                modes: shell.catalog(forChat: chat).permissionModes(for: model), current: mode
            ) {
                shell.setPermission($0, for: chat)
            }
        }
    }
}

/// The permission modes with their descriptions: Auto only for models that offer it, no
/// default entry (B94).
struct PermissionItems: View {
    let modes: [PermissionMode]
    let current: PermissionMode?
    let pick: (PermissionMode) -> Void

    var body: some View {
        Section("Permission mode") {
            ForEach(modes, id: \.self) { option in
                OptionItem(
                    title: option.label, detail: option.summary, checked: current == option
                ) { pick(option) }
            }
        }
    }
}
