import HarnessKit
import SwiftUI

/// A project's settings: its icon, where new chats work, the files linked into worktrees and the
/// setup commands run there, and removing the project from harness (IMP-09). Changes are
/// saved as they are made.
struct ProjectSettingsSheet: View {
    let project: String
    @Environment(Shell.self) private var shell

    var body: some View {
        SheetFrame(title: "Project settings", width: 540) {
            if let repo = shell.app.repo(project) {
                VStack(alignment: .leading, spacing: 0) {
                    HStack(spacing: 10) {
                        ProjectIcon(project: repo.name, repo: repo, size: 22)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(repo.name).font(.ui(TypeSize.reading, .semibold))
                            Text(repo.path)
                                .font(.mono(TypeSize.meta))
                                .foregroundStyle(Palette.t3)
                                .textSelection(.enabled)
                        }
                    }
                    .padding(.top, 14)
                    IconSection(repo: repo)
                    if repo.git {
                        WorktreeSection(repo: repo)
                    }
                    RemoveSection(repo: repo)
                }
            } else {
                Text("This project is no longer registered.")
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t3)
                    .padding(.vertical, 20)
            }
        }
    }
}

/// The project's icon: its initials or a pixie sprite, and the sprite's colour. A click
/// saves the choice.
private struct IconSection: View {
    let repo: Repo
    @Environment(Shell.self) private var shell

    var body: some View {
        let color = repo.iconColor ?? PixieColor.standard
        SheetSection(title: "Icon") {
            HStack(spacing: 2) {
                IconChoice(label: "Initials", on: repo.icon == nil) {
                    ProjectIcon(name: repo.name, size: 18)
                } pick: {
                    save { $0.mascot = nil }
                }
                ForEach(Mascot.choices, id: \.self) { mascot in
                    IconChoice(label: mascot.rawValue.capitalized, on: repo.icon == mascot) {
                        SpriteView(mascot: mascot, color: color, size: 18)
                    } pick: {
                        save { $0.mascot = mascot }
                    }
                }
            }
            .padding(.vertical, 4)
            HStack(spacing: 2) {
                ForEach(PixieColors.presets, id: \.self) { preset in
                    Swatch(color: preset, on: color.uppercased() == preset) {
                        // The default colour is saved as no colour, so it follows the default.
                        let chosen: String? = preset == PixieColor.standard ? nil : preset
                        save { $0.color = chosen }
                    }
                }
            }
            .padding(.vertical, 4)
            .disabled(repo.icon == nil)
            .opacity(repo.icon == nil ? 0.4 : 1)
            Caption(text: "The sprite and its colour show on the project's tab and in its sidebar.")
        }
    }

    private func save(_ change: @escaping @Sendable (inout HarnessKit.ProjectIcon) -> Void) {
        let name = repo.name
        Task {
            do {
                try await shell.app.changeIcon(of: name, change)
            } catch {
                shell.show(error, doing: "Could not save the project icon")
            }
        }
    }
}

/// One icon to pick: a soft fill when chosen or hovered.
private struct IconChoice<Mark: View>: View {
    let label: String
    let on: Bool
    @ViewBuilder let mark: () -> Mark
    let pick: () -> Void
    @Environment(\.accentColors) private var accent

    var body: some View {
        Button(action: pick) {
            HoverReader { hovering in
                mark()
                    .frame(width: 32, height: 30)
                    .background(
                        on ? accent.selection : hovering ? Palette.soft : .clear,
                        in: .rounded(Radius.row)
                    )
                    .contentShape(Rectangle())
            }
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .help(label)
        .accessibilityLabel("Icon \(label)")
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}

/// A pixie colour to pick; the chosen one has a ring.
private struct Swatch: View {
    let color: String
    let on: Bool
    let pick: () -> Void

    var body: some View {
        Button(action: pick) {
            Circle()
                .fill(Color(hex: color))
                .frame(width: 14, height: 14)
                .padding(3)
                .overlay {
                    if on {
                        Circle().strokeBorder(Palette.t2, lineWidth: 1.2)
                    }
                }
                .frame(width: 32, height: 24)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .help(color)
        .accessibilityLabel("Colour \(color)")
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}

/// The worktree default, links and setup commands.
private struct WorktreeSection: View {
    let repo: Repo
    @Environment(Shell.self) private var shell
    @State private var newLink = ""
    @State private var newSetup = ""
    @State private var suggestions: [String] = []

    var body: some View {
        let config = repo.worktree
        let agentDefault = shell.agents.current.mode == .worktree ? "Worktree" : "In place"
        SheetSection(title: "New chats") {
            SheetRow(label: "Work in", first: true) {
                Segmented(
                    options: [(nil, "Agent default"), (true, "Worktree"), (false, "In place")],
                    selection: config.isDefault
                ) { value in save { $0.isDefault = value } }
            }
            Caption(text: "Agent default follows Settings, now \(agentDefault).")
        }
        SheetSection(title: "Linked files") {
            ListRows(items: config.link, mono: true) { _, path in
                save { $0.removeLink(path) }
            }
            AddRow(placeholder: "Path in the project, such as .env", text: $newLink) {
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
                        .buttonStyle(.harness(.plain))
                        .fixedSize()
                    }
                }
                .padding(.top, 6)
            }
            Caption(
                text:
                    "Gitignored files such as .env are linked into each new worktree, so chats there can use them."
            )
        }
        SheetSection(title: "Setup commands") {
            ListRows(items: config.setup, mono: true) { index, command in
                save { $0.removeSetup(command, at: index) }
            }
            AddRow(placeholder: "Command, such as npm ci", text: $newSetup) {
                let command = newSetup
                var changed = config
                if changed.addSetup(command) {
                    newSetup = ""
                    save { $0.addSetup(command) }
                }
            }
            Caption(text: "Run in order in each new worktree before the chat starts.")
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

/// Remove from harness, with a confirmation that says what goes.
private struct RemoveSection: View {
    let repo: Repo
    @Environment(Shell.self) private var shell
    @State private var confirming = false

    var body: some View {
        let chats = shell.sessions.sessions(in: repo.name).count
        SheetSection(title: "Remove") {
            HStack(spacing: 12) {
                Text(ProjectRemoval.consequence(chats: chats))
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t2)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 8)
                Button("Remove from harness") { confirming = true }
                    .buttonStyle(.harness(.danger))
                    .fixedSize()
            }
            .padding(.vertical, 6)
        }
        .confirmationDialog(
            "Remove \(repo.name) from harness?", isPresented: $confirming,
            titleVisibility: .visible
        ) {
            Button("Remove", role: .destructive) { shell.removeProject(repo.name) }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(ProjectRemoval.consequence(chats: chats))
        }
    }
}

/// Items with a remove button each; removing names the item and its place.
private struct ListRows: View {
    let items: [String]
    var mono = false
    let remove: (Int, String) -> Void

    var body: some View {
        if items.isEmpty {
            Text("None yet")
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t3)
                .padding(.vertical, 4)
        }
        ForEach(Array(items.enumerated()), id: \.offset) { index, item in
            HStack(spacing: 8) {
                Text(item)
                    .font(mono ? .mono(TypeSize.meta) : .ui(TypeSize.ui))
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .textSelection(.enabled)
                Spacer(minLength: 8)
                Button {
                    remove(index, item)
                } label: {
                    Image(systemName: Icon.close).font(.system(size: 9, weight: .bold))
                }
                .buttonStyle(.harness(.plain, height: 22, iconOnly: true))
                .help("Remove")
                .accessibilityLabel("Remove \(item)")
            }
            .padding(.vertical, 3)
        }
    }
}

/// A field with Add; Return adds too.
private struct AddRow: View {
    let placeholder: String
    @Binding var text: String
    let add: () -> Void

    var body: some View {
        HStack(spacing: 6) {
            CardField(placeholder: placeholder, text: $text, submit: add)
            Button("Add", action: add)
                .buttonStyle(.harness(.soft))
                .fixedSize()
                .disabled(text.trimmingCharacters(in: .whitespaces).isEmpty)
        }
        .padding(.top, 6)
    }
}

private struct Caption: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.ui(TypeSize.meta))
            .foregroundStyle(Palette.t3)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.vertical, 6)
    }
}
