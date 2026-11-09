import NestKit
import SwiftUI

/// The project trigger the sheet over Settings edits (B148); a nil id is a new one.
struct TriggerForm: Equatable {
    let repo: String
    let triggerID: String?
    let draft: TriggerDraft
}

/// A project's GitHub triggers (B148): each starts a chat here when its events happen.
struct ProjectTriggersTab: View {
    let repo: Repo
    @Environment(Shell.self) private var shell
    @State private var activity: [String: TriggerActivity] = [:]

    var body: some View {
        SettingsSection(title: "Triggers") {
            if repo.remoteURL == nil {
                note(TriggerText.noRemote)
            } else {
                if repo.triggers.isEmpty {
                    note(TriggerText.empty)
                }
                ForEach(repo.triggers) { trigger in
                    let last = TriggerText.activity(activity[trigger.id], now: .now)
                    SettingsListRow(
                        title: trigger.name,
                        detail: [TriggerText.summary(trigger), last].compactMap { $0 }
                            .joined(separator: " · ")
                    ) {
                        EmptyView()
                    } trailing: {
                        Button("Edit") { edit(trigger) }
                            .buttonStyle(.nest(.plain))
                        Switch(isOn: trigger.enabled, accent: true) {
                            let name = repo.name
                            shell.settingsChange("Could not change \(trigger.name)") {
                                try await shell.app.switchTrigger(
                                    name, id: trigger.id, on: !trigger.enabled)
                            }
                        }
                        .accessibilityLabel("\(trigger.name) on")
                    }
                }
                Button("Add trigger") {
                    shell.triggerForm = TriggerForm(
                        repo: repo.name, triggerID: nil, draft: TriggerDraft())
                }
                .buttonStyle(.nest(.soft))
                .padding(.top, 10)
            }
        }
        .task(id: repo.triggers) {
            activity = (try? await shell.app.triggerActivity(of: repo.name)) ?? activity
        }
    }

    private func note(_ text: String) -> some View {
        Text(text)
            .font(.ui(TypeSize.meta))
            .foregroundStyle(Palette.t3)
            .padding(.vertical, 8)
    }

    private func edit(_ trigger: ChatTrigger) {
        shell.triggerForm = TriggerForm(
            repo: repo.name, triggerID: trigger.id, draft: TriggerDraft(trigger: trigger))
    }
}

/// New and Edit trigger: a name, the events, the filters, and what the chat is told.
struct TriggerFormSheet: View {
    let form: TriggerForm
    @Environment(Shell.self) private var shell
    @State private var draft: TriggerDraft
    @State private var removing = false

    init(form: TriggerForm) {
        self.form = form
        _draft = State(initialValue: form.draft)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(form.triggerID == nil ? "New trigger" : "Edit trigger")
                .font(.ui(TypeSize.body, .semibold))
            FormLine(label: "Name") {
                CardField(placeholder: "Fix failing CI on main", text: $draft.name)
            }
            FormLine(label: "When") {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(GitHubEventKind.choices, id: \.self) { event in
                        Toggle(
                            event.label,
                            isOn: Binding(
                                get: { draft.events.contains(event) },
                                set: { on in
                                    if on {
                                        draft.events.insert(event)
                                    } else {
                                        draft.events.remove(event)
                                    }
                                })
                        )
                        .toggleStyle(.checkbox)
                    }
                }
            }
            FormLine(label: "Labels") {
                CardField(placeholder: "Any, or such as bug", text: $draft.labels)
            }
            FormLine(label: "Branches") {
                CardField(placeholder: "Any, or such as main, release/*", text: $draft.branches)
            }
            FormLine(label: "From") {
                SegmentPicker(
                    options: TriggerAuthors.choices.map { ($0, $0.label) },
                    selection: draft.authors
                ) { draft.authors = $0 }
            }
            if draft.authors != .members {
                WarningLine(text: TriggerText.outsidersWarning)
            }
            FormLine(label: "Runs with") {
                SegmentPicker(
                    options: TriggerText.modes.map { ($0, $0.label) },
                    selection: draft.permissionMode
                ) { draft.permissionMode = $0 }
            }
            FormLine(label: "Start a chat with") {
                TextEditor(text: $draft.prompt)
                    .font(.ui(TypeSize.ui))
                    .scrollContentBackground(.hidden)
                    .frame(height: 72)
                    .padding(4)
                    .background(Palette.soft, in: .rounded(Radius.button))
                    .accessibilityLabel("What the chat should do")
            }
            Text(TriggerText.triggerNote)
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
            HStack(spacing: 8) {
                if form.triggerID != nil {
                    Button("Delete") { removing = true }
                        .buttonStyle(.nest(.danger))
                }
                Spacer()
                Button("Cancel") { shell.triggerForm = nil }
                    .buttonStyle(.nest())
                Button("Save") { save() }
                    .buttonStyle(.nest(.primary))
                    .disabled(!draft.canSave)
                    .help(draft.problem ?? "Save the trigger")
                    .keyboardShortcut(.defaultAction)
            }
            .padding(.top, 6)
        }
        .font(.ui(TypeSize.ui))
        .foregroundStyle(Palette.t1)
        .padding(20)
        .frame(width: 520)
        .sheetSurface()
        .confirmationDialog(
            "Delete \(draft.name)?", isPresented: $removing, titleVisibility: .visible
        ) {
            Button("Delete", role: .destructive) { remove() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Chats it started stay.")
        }
    }

    private func save() {
        let form = form
        let body = draft.body
        shell.settingsChange("Could not save the trigger") {
            try await shell.app.saveTrigger(form.repo, id: form.triggerID, body)
            shell.triggerForm = nil
        }
    }

    private func remove() {
        guard let id = form.triggerID else { return }
        let repo = form.repo
        shell.settingsChange("Could not delete the trigger") {
            try await shell.app.deleteTrigger(repo, id: id)
            shell.triggerForm = nil
        }
    }
}
