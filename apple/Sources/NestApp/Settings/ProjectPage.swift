import AppKit
import NestKit
import SwiftUI

/// A project's settings in tabs, in place of the old Project settings sheet (B81). Changes
/// are saved as they are made.
struct ProjectPage: View {
    let project: String
    @Environment(Shell.self) private var shell

    var body: some View {
        if let repo = shell.app.repo(project) {
            let tabs = ProjectSettingsTab.tabs(git: repo.git)
            let tab = tabs.contains(shell.projectTab) ? shell.projectTab : .general
            SettingsTabs(tabs: tabs.map { ($0, $0.rawValue) }, selection: tab) {
                shell.projectTab = $0
            }
            switch tab {
            case .general: ProjectGeneralTab(repo: repo)
            case .chats: ProjectChatsTab(repo: repo)
            case .worktrees: ProjectWorktreesTab(repo: repo)
            case .look: ProjectLookTab(repo: repo)
            case .artifacts: ProjectArtifactsTab(repo: repo)
            }
        }
    }
}

// MARK: General

private struct ProjectGeneralTab: View {
    let repo: Repo
    @Environment(Shell.self) private var shell
    @State private var branches: [String] = []
    @State private var removing = false

    var body: some View {
        let chats = shell.sessions.sessions(in: repo.name).count
        SettingsSection(title: "Project") {
            SettingsRow(label: "Name") { SettingsValue(text: repo.name) }
            SettingsRow(label: "Folder") {
                SettingsValue(text: Self.abbreviate(repo.path), mono: true)
                Button("Show in Finder") {
                    let name = repo.name
                    shell.settingsChange("Could not open the folder") {
                        try await shell.app.openProject(name, in: .finder)
                    }
                }
                .buttonStyle(.nest(.soft))
            }
            SettingsRow(label: "Kind") {
                SettingsValue(text: repo.git ? "Git repository" : "Plain folder")
            }
        }
        if repo.git {
            SettingsSection(title: "Git") {
                SettingsRow(label: "Default branch") {
                    DropdownMenu(title: repo.defaultBranch ?? "-", width: 140) {
                        ForEach(branches, id: \.self) { branch in
                            Button(branch) { save(RepoPatch(defaultBranch: branch)) }
                        }
                    }
                    .disabled(branches.isEmpty)
                }
                PushToRow(repo: repo)
            }
            .task(id: repo.name) {
                branches = (try? await shell.app.branches(of: repo.name)) ?? []
            }
        }
        SettingsSection(title: "Remove") {
            SettingsRow(label: "Remove \(repo.name) from Nest") {
                Button("Remove") { removing = true }
                    .buttonStyle(.nest(.danger))
            }
        }
        .confirmationDialog(
            "Remove \(repo.name) from Nest?", isPresented: $removing, titleVisibility: .visible
        ) {
            Button("Remove", role: .destructive) { shell.removeProject(repo.name) }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(ProjectRemoval.consequence(chats: chats))
        }
    }

    private func save(_ patch: RepoPatch) {
        let name = repo.name
        shell.settingsChange("Could not save the project settings") {
            try await shell.app.changeRepo(name, patch)
        }
    }

    /// The home folder as ~.
    static func abbreviate(_ path: String) -> String {
        let home = NSHomeDirectory()
        return path.hasPrefix(home + "/") ? "~" + path.dropFirst(home.count) : path
    }
}

/// The one address Nest pushes to: Change, or Set remote, with a confirmation.
private struct PushToRow: View {
    let repo: Repo
    @Environment(Shell.self) private var shell
    @State private var editing = false
    @State private var text = ""

    var body: some View {
        SettingsRow(label: "Push to") {
            if let url = repo.remoteURL {
                SettingsValue(text: url, mono: true)
            } else {
                Text("No remote yet")
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t3)
            }
            Button(repo.remoteURL == nil ? "Set remote" : "Change") {
                text = repo.remoteURL ?? ""
                editing = true
            }
            .buttonStyle(.nest(.soft))
        }
        .alert(
            repo.remoteURL == nil ? "Set the push address" : "Change the push address",
            isPresented: $editing
        ) {
            TextField("git@github.com:you/repo.git", text: $text)
            Button("Save") { save() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Nest pushes \(repo.name) only to this address.")
        }
    }

    private func save() {
        let url = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !url.isEmpty else { return }
        let name = repo.name
        shell.settingsChange("Could not save the push address") {
            try await shell.app.changeRepo(name, RepoPatch(remoteURL: url))
        }
    }
}

// MARK: Chats

private struct ProjectChatsTab: View {
    let repo: Repo
    @Environment(Shell.self) private var shell

    var body: some View {
        SettingsSection(title: "New chats in this project") {
            SettingsRow(label: "Work in") {
                Segmented(
                    options: [
                        (nil, "Follow default"), (false, "Current branch"), (true, "New worktree"),
                    ],
                    selection: repo.worktree.isDefault
                ) { value in shell.changeSettings(of: repo.name) { $0.isDefault = value } }
            }
        }
    }
}

// MARK: Worktrees

private struct ProjectWorktreesTab: View {
    let repo: Repo
    @Environment(Shell.self) private var shell
    @State private var newLink = ""
    @State private var newSetup = ""
    @State private var suggestions: [String] = []

    var body: some View {
        let config = repo.worktree
        SettingsSection(title: "When Nest makes a worktree") {
            SettingsRow(label: "Linked files") {
                Chips(items: config.link) { index, path in
                    save { $0.removeLink(path) }
                }
            }
            AddField(placeholder: "Path in the project, such as .env", text: $newLink) {
                var changed = config
                if changed.addLink(newLink) {
                    let path = newLink
                    newLink = ""
                    save { $0.addLink(path) }
                } else {
                    shell.show(
                        "Use a path inside the project that is not linked yet", kind: .failed)
                }
            }
            if !suggestions.isEmpty {
                HStack(spacing: 6) {
                    Text("Suggested").font(.ui(TypeSize.meta)).foregroundStyle(Palette.t3)
                    ForEach(suggestions.prefix(5), id: \.self) { path in
                        Button {
                            save { $0.addLink(path) }
                            suggestions.removeAll { $0 == path }
                        } label: {
                            Label(path, systemImage: Icon.plus)
                        }
                        .buttonStyle(.nest(.plain))
                        .fixedSize()
                    }
                }
                .padding(.vertical, 6)
                .frame(maxWidth: .infinity, alignment: .leading)
                .overlay(alignment: .bottom) { Separator() }
            }
            SettingsRow(label: "Setup commands") {
                Chips(items: config.setup) { index, command in
                    save { $0.removeSetup(command, at: index) }
                }
            }
            AddField(placeholder: "Command, such as npm ci", text: $newSetup) {
                let command = newSetup
                var changed = config
                if changed.addSetup(command) {
                    newSetup = ""
                    save { $0.addSetup(command) }
                }
            }
            SettingsRow(label: "Setup time limit") {
                let seconds = config.setupTimeoutSeconds
                DropdownMenu(title: SetupTimeout.label(seconds), width: 130) {
                    ForEach(SetupTimeout.choices(including: seconds), id: \.self) { choice in
                        Button(SetupTimeout.label(choice)) {
                            let name = repo.name
                            shell.settingsChange("Could not save the project settings") {
                                try await shell.app.changeRepo(
                                    name, RepoPatch(setupTimeoutSeconds: choice))
                            }
                        }
                    }
                }
            }
        }
        .task(id: repo.name) {
            suggestions = (try? await shell.app.linkSuggestions(for: repo.name)) ?? []
        }
    }

    /// Each change applies to the settings as last saved, not as this view shows them.
    private func save(_ change: @escaping @Sendable (inout WorktreeConfig) -> Void) {
        shell.changeSettings(of: repo.name, change)
    }
}

/// Small mono chips, each with a remove button.
private struct Chips: View {
    let items: [String]
    let remove: (Int, String) -> Void

    var body: some View {
        if items.isEmpty {
            Text("None yet").font(.ui(TypeSize.ui)).foregroundStyle(Palette.t3)
        }
        ForEach(Array(items.enumerated()), id: \.offset) { index, item in
            HStack(spacing: 4) {
                Text(item)
                    .font(.mono(TypeSize.meta))
                    .lineLimit(1)
                    .truncationMode(.middle)
                Button {
                    remove(index, item)
                } label: {
                    Image(systemName: Icon.close).font(.system(size: 7, weight: .bold))
                }
                .buttonStyle(.plain)
                .pointerStyle(.link)
                .foregroundStyle(Palette.t3)
                .help("Remove")
                .accessibilityLabel("Remove \(item)")
            }
            .foregroundStyle(Palette.t2)
            .padding(.leading, 8)
            .padding(.trailing, 6)
            .padding(.vertical, 2)
            .background(Palette.soft, in: Capsule())
        }
    }
}

/// A field with Add; Return adds too.
private struct AddField: View {
    let placeholder: String
    @Binding var text: String
    let add: () -> Void

    var body: some View {
        HStack(spacing: 6) {
            Spacer(minLength: 0)
            CardField(placeholder: placeholder, text: $text, submit: add)
                .frame(width: 260)
            Button("Add", action: add)
                .buttonStyle(.nest(.soft))
                .fixedSize()
                .disabled(text.trimmingCharacters(in: .whitespaces).isEmpty)
        }
        .padding(.vertical, 6)
        .overlay(alignment: .bottom) { Separator() }
    }
}

// MARK: Look

private struct ProjectLookTab: View {
    let repo: Repo
    @Environment(Shell.self) private var shell

    var body: some View {
        let color = repo.iconColor ?? PixieColor.standard
        SettingsSection(title: "Icon") {
            SettingsRow(label: "Tab icon") {
                Segmented(
                    options: [(false, "Initials"), (true, "Pixie sprite")],
                    selection: repo.icon != nil
                ) { sprite in
                    save { $0.mascot = sprite ? ($0.mascot ?? Mascot.choices.first) : nil }
                }
            }
            if repo.icon != nil {
                SettingsRow(label: "Sprite") {
                    HStack(spacing: 2) {
                        ForEach(Mascot.choices, id: \.self) { mascot in
                            SpriteChoice(mascot: mascot, color: color, on: repo.icon == mascot) {
                                save { $0.mascot = mascot }
                            }
                        }
                    }
                }
            }
            SettingsRow(label: "Colour") {
                HStack(spacing: 2) {
                    ForEach(PixieColors.presets, id: \.self) { preset in
                        ColorSwatch(color: preset, on: color.uppercased() == preset) {
                            // The default colour is saved as no colour, so it follows the
                            // default.
                            let chosen: String? = preset == PixieColor.standard ? nil : preset
                            save { $0.color = chosen }
                        }
                    }
                }
                .disabled(repo.icon == nil)
                .opacity(repo.icon == nil ? 0.4 : 1)
            }
        }
        ProjectBackgroundSection(project: repo.name)
    }

    private func save(_ change: @escaping @Sendable (inout NestKit.ProjectIcon) -> Void) {
        let name = repo.name
        shell.settingsChange("Could not save the project icon") {
            try await shell.app.changeIcon(of: name, change)
        }
    }
}

/// The project's own chat background image, in place of the one set in Appearance.
private struct ProjectBackgroundSection: View {
    let project: String
    @Environment(Shell.self) private var shell

    var body: some View {
        let own = shell.settings.chatBackground.projects[project]
        SettingsSection(title: "Chat background") {
            SettingsRow(label: "Background") {
                if own == nil {
                    Text("Same as everywhere")
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                }
                ImageButtons(hasImage: own != nil, removeTitle: "Use global") {
                    shell.chooseChatBackground(for: project)
                } remove: {
                    shell.removeChatBackground(for: project)
                }
            }
            if let own {
                BackgroundPreview(background: own)
                BackgroundRows(background: own) { changed in
                    shell.settings.chatBackground.projects[project] = changed
                }
            }
        }
    }
}

private struct SpriteChoice: View {
    let mascot: Mascot
    let color: String
    let on: Bool
    let pick: () -> Void
    @Environment(\.accentColors) private var accent

    var body: some View {
        Button(action: pick) {
            HoverReader { hovering in
                SpriteView(mascot: mascot, color: color, size: 16)
                    .frame(width: 28, height: 26)
                    .background(
                        on ? accent.selection : hovering ? Palette.soft : .clear,
                        in: .rounded(Radius.row)
                    )
                    .contentShape(Rectangle())
            }
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .help(mascot.rawValue.capitalized)
        .accessibilityLabel("Sprite \(mascot.rawValue)")
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}

private struct ColorSwatch: View {
    let color: String
    let on: Bool
    let pick: () -> Void

    var body: some View {
        Button(action: pick) {
            Circle()
                .fill(Color(hex: color))
                .frame(width: 16, height: 16)
                .padding(3)
                .overlay {
                    if on {
                        Circle().strokeBorder(Palette.t2, lineWidth: 1)
                    }
                }
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .help(color)
        .accessibilityLabel("Colour \(color)")
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}

// MARK: Artifacts

/// How many artifacts the project's chats saved, and the Artifacts view (B79). Before B79
/// the daemon has no list: the tab says None yet.
private struct ProjectArtifactsTab: View {
    let repo: Repo
    @Environment(Shell.self) private var shell
    @State private var count: Int?

    var body: some View {
        SettingsSection(title: "Artifacts") {
            SettingsRow(label: "Saved in this project") {
                SettingsValue(text: Self.countText(count))
                Button("Open Artifacts view") { shell.openArtifacts(project: repo.name) }
                    .buttonStyle(.nest(.soft))
            }
        }
        .task(id: repo.name) { count = await shell.app.artifactCount(of: repo.name) }
    }

    static func countText(_ count: Int?) -> String {
        switch count {
        case nil, 0: "None yet"
        case 1: "1 artifact"
        case let count?: "\(count) artifacts"
        }
    }
}

// MARK: Add project

/// A folder to add as a project, chosen or typed.
struct AddProjectPage: View {
    @Environment(Shell.self) private var shell
    @State private var path = NSHomeDirectory() + "/"

    var body: some View {
        SettingsSection(title: "") {
            SettingsRow(label: "Folder") {
                CardField(placeholder: "Folder", text: $path, submit: add)
                    .font(.mono(TypeSize.meta))
                    .frame(width: 260)
                Button("Choose…") { choose() }.buttonStyle(.nest(.soft))
                Button("Add", action: add)
                    .buttonStyle(.nest(.primary))
                    .disabled(path.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
    }

    private func choose() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.prompt = "Choose"
        if panel.runModal() == .OK, let url = panel.url {
            path = url.path
        }
    }

    private func add() {
        let text = path.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        let url = URL(fileURLWithPath: (text as NSString).expandingTildeInPath)
        shell.addProject(at: url)
        shell.openSettings(.project(url.standardizedFileURL.lastPathComponent))
    }
}
