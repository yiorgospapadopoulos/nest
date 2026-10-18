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

struct ModelMenu: View {
    let chat: String
    let model: String?
    @Environment(Shell.self) private var shell
    @Environment(\.paneFit) private var fit

    var body: some View {
        let label = shell.agents.label(for: model)
        QuietMenu(title: fit.compact ? PaneFit.shortModel(label) : label, help: "Model") {
            ModelItems(current: model) { shell.setModel($0, for: chat) }
        }
    }
}

/// Claude Code's model list with descriptions and a checkmark on the current model; a
/// model the list does not have shows only as the menu's title. With `defaultItem` set
/// (a pixie), Default comes first and stands for no model of its own (nil).
struct ModelItems: View {
    let current: String?
    var defaultItem: DefaultItem?
    let pick: (ModelInfo) -> Void
    @Environment(Shell.self) private var shell

    struct DefaultItem {
        let detail: String
        let pick: () -> Void
    }

    var body: some View {
        let agents = shell.agents
        Section("Model") {
            if let defaultItem {
                OptionItem(title: "Default", detail: defaultItem.detail, checked: current == nil) {
                    defaultItem.pick()
                }
            }
            if agents.models.isEmpty {
                Button("Models unavailable") {}.disabled(true)
            }
            ForEach(agents.models) { info in
                OptionItem(
                    title: info.displayName, detail: info.description,
                    checked: (defaultItem == nil || current != nil)
                        && agents.isSelected(info, current: current)
                ) { pick(info) }
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
        QuietMenu(title: label ?? "Default", help: "Thinking") {
            ThinkingItems(model: model, effort: effort) { level in
                if let level {
                    shell.setEffort(level, for: chat)
                }
            }
            if isOpen && !shell.agents.thinkingLevels(for: model).isEmpty {
                Divider()
                Text("Applies from your next message")
            }
        }
    }
}

/// The model's own thinking levels; Model default (nil) only where `offersDefault` is set.
struct ThinkingItems: View {
    let model: String?
    let effort: Effort?
    var offersDefault = false
    let pick: (Effort?) -> Void
    @Environment(Shell.self) private var shell

    var body: some View {
        let levels = shell.agents.thinkingLevels(for: model)
        Section("Thinking") {
            if levels.isEmpty {
                Button("Not available for this model") {}.disabled(true)
            } else {
                if offersDefault {
                    OptionItem(
                        title: shell.agents.defaultEffortLabel(for: model), detail: "",
                        checked: effort == nil
                    ) { pick(nil) }
                }
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
    /// Nil only for a new chat whose agent default leaves it to Claude Code; menus do not
    /// offer it, as the daemon would start the chat with the agent default (audit BUG-87).
    let mode: PermissionMode?
    /// Bypass in the warning colour, as the empty workspace shows it.
    var warnsOnBypass = false
    @Environment(Shell.self) private var shell
    @Environment(\.paneFit) private var fit

    var body: some View {
        let label =
            fit.compact ? PermissionMode.shortLabel(mode) : PermissionMode.label(mode)
        let warns = warnsOnBypass && mode == .bypassPermissions
        QuietMenu(
            title: label, help: "Permission mode", tint: warns ? StatusTone.waiting.color : nil
        ) {
            PermissionItems(modes: shell.agents.permissionModes(for: model), current: mode) {
                shell.setPermission($0, for: chat)
            }
        }
    }
}

/// The permission modes with their descriptions: Auto only for models that offer it,
/// and Claude Code default (nil) where `offersDefault` is set (agent defaults only).
struct PermissionItems: View {
    let modes: [PermissionMode]
    let current: PermissionMode?
    var offersDefault = false
    let pick: (PermissionMode?) -> Void

    var body: some View {
        Section("Permission mode") {
            if offersDefault {
                OptionItem(
                    title: PermissionMode.claudeCodeDefaultLabel,
                    detail: PermissionMode.claudeCodeDefaultSummary, checked: current == nil
                ) { pick(nil) }
            }
            ForEach(modes, id: \.self) { option in
                OptionItem(
                    title: option.label, detail: option.summary, checked: current == option
                ) { pick(option) }
            }
        }
    }
}
