import HarnessKit
import SwiftUI

/// A selector that reads as plain text, highlights on hover and opens a list. Its title
/// truncates when the row is short of room.
struct QuietMenu<Items: View>: View {
    let title: String
    let help: String
    @ViewBuilder let items: () -> Items
    @State private var hovering = false
    @Environment(\.paneFit) private var fit

    var body: some View {
        Menu {
            items()
        } label: {
            Text(title)
                .font(.ui(TypeSize.callout, .medium))
                .foregroundStyle(hovering ? Palette.t1 : Palette.t2)
                .lineLimit(1)
                .truncationMode(.tail)
                .padding(.horizontal, fit.compact ? 4 : 7)
                .frame(height: 26)
                .background(
                    hovering ? Palette.fill : .clear,
                    in: RoundedRectangle(cornerRadius: 7, style: .continuous)
                )
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
/// model the list does not have shows only as the menu's title.
struct ModelItems: View {
    let current: String?
    let pick: (ModelInfo) -> Void
    @Environment(Shell.self) private var shell

    var body: some View {
        let agents = shell.agents
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
                    OptionItem(title: "Model default", detail: "", checked: effort == nil) {
                        pick(nil)
                    }
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
    let mode: PermissionMode?
    @Environment(Shell.self) private var shell
    @Environment(\.paneFit) private var fit

    var body: some View {
        let label = fit.compact ? mode?.shortLabel : mode?.label
        QuietMenu(title: label ?? "Ask", help: "Permission mode") {
            Section("Permission mode") {
                ForEach(PermissionMode.selectable, id: \.self) { option in
                    OptionItem(title: option.label, detail: option.summary, checked: mode == option)
                    {
                        shell.setPermission(option, for: chat)
                    }
                }
            }
        }
    }
}

/// New chats only: run in a worktree or in the project folder.
struct ModeMenu: View {
    @Bindable var draft: ComposerDraft

    var body: some View {
        QuietMenu(title: draft.mode == .inPlace ? "In place" : "Worktree", help: "Where it works") {
            Section("Where it works") {
                OptionItem(
                    title: "Worktree", detail: "A separate checkout on its own branch",
                    checked: draft.mode != .inPlace
                ) { draft.mode = .worktree }
                OptionItem(
                    title: "In place", detail: "The project folder itself",
                    checked: draft.mode == .inPlace
                ) { draft.mode = .inPlace }
            }
        }
    }
}
