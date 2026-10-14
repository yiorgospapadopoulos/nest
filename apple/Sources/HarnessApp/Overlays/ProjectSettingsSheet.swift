import HarnessKit
import SwiftUI

/// A project's settings: where new chats work, the files linked into worktrees and the
/// setup commands run there, and removing the project from harness (IMP-09). Changes are
/// saved as they are made.
struct ProjectSettingsSheet: View {
    let project: String
    @Environment(Shell.self) private var shell

    var body: some View {
        SheetFrame(title: "Project settings", width: 540) {
            if let repo = shell.app.repo(project) {
                VStack(alignment: .leading, spacing: 0) {
                    Text(repo.name).font(.ui(TypeSize.body, .semibold)).padding(.top, 14)
                    Text(repo.path)
                        .font(.mono(TypeSize.caption))
                        .foregroundStyle(Palette.t3)
                        .textSelection(.enabled)
                    if repo.git {
                        WorktreeSection(repo: repo)
                    }
                    RemoveSection(repo: repo)
                }
            } else {
                Text("This project is no longer registered.")
                    .font(.ui(TypeSize.small))
                    .foregroundStyle(Palette.t3)
                    .padding(.vertical, 20)
            }
        }
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
                    Text("Suggested").font(.ui(TypeSize.caption)).foregroundStyle(Palette.t3)
                    ForEach(suggestions.prefix(5), id: \.self) { path in
                        Button {
                            save { $0.addLink(path) }
                            suggestions.removeAll { $0 == path }
                        } label: {
                            Label(path, systemImage: Icon.plus)
                        }
                        .buttonStyle(.card(.ghost))
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
                    .font(.ui(TypeSize.small))
                    .foregroundStyle(Palette.t2)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 8)
                Button("Remove from harness") { confirming = true }
                    .buttonStyle(.card(.danger))
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
                .font(.ui(TypeSize.small))
                .foregroundStyle(Palette.t3)
                .padding(.vertical, 4)
        }
        ForEach(Array(items.enumerated()), id: \.offset) { index, item in
            HStack(spacing: 8) {
                Text(item)
                    .font(mono ? .mono(TypeSize.small) : .ui(TypeSize.small))
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .textSelection(.enabled)
                Spacer(minLength: 8)
                Button {
                    remove(index, item)
                } label: {
                    Image(systemName: Icon.close).font(.system(size: 9, weight: .bold))
                }
                .buttonStyle(.harness(.ghost, height: 22, iconOnly: true))
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
                .buttonStyle(.card(.plain))
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
            .font(.ui(TypeSize.small))
            .foregroundStyle(Palette.t3)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.vertical, 6)
    }
}
