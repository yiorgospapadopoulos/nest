import NestKit
import SwiftUI

/// A form over Settings > Configuration or a project's Configuration tab (B97).
enum ConfigurationForm: Equatable {
    /// Add or edit a server; a repo's go to its `.mcp.json`.
    case server(MCPServerForm, repo: String?)
    /// A new skill in the shared folder, or a repo's `.claude/skills`.
    case skill(repo: String?)
}

/// The editor sheet, the copy popup and the forms, drawn over the Settings window with a
/// scrim, as the main window draws its sheets.
struct ConfigurationModals: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.configuration
        ZStack {
            if let editor = store.editor {
                scrim { store.closeEditor() }
                ConfigEditorSheet(editor: editor).padding(40)
            } else if let flow = store.copy {
                scrim { store.cancelCopy() }
                CopySheet(flow: flow).padding(40)
            } else if let form = shell.configurationForm {
                scrim { shell.configurationForm = nil }
                switch form {
                case .server(let fields, let repo):
                    ServerFormSheet(form: fields, repo: repo).padding(40)
                case .skill(let repo):
                    SkillFormSheet(repo: repo).padding(40)
                }
            }
        }
        .animation(.smooth(duration: 0.15), value: store.editor?.id)
    }

    private func scrim(close: @escaping () -> Void) -> some View {
        Palette.scrim
            .ignoresSafeArea()
            .onTapGesture(perform: close)
            .overlay {
                Button("Close", action: close)
                    .keyboardShortcut(.cancelAction)
                    .opacity(0)
                    .frame(width: 0, height: 0)
                    .accessibilityHidden(true)
            }
    }
}

// MARK: Editor

/// A file in place: title and path, VS Code and Finder, the "changed on disk" bar, the
/// text in mono, and Save.
private struct ConfigEditorSheet: View {
    @Bindable var editor: ConfigFileEditor
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.configuration
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 6) {
                        Text(editor.title).font(.ui(TypeSize.body, .semibold))
                        Text(URL(fileURLWithPath: editor.path).lastPathComponent)
                            .font(.mono(TypeSize.meta))
                            .foregroundStyle(Palette.t3)
                    }
                    HStack(spacing: 0) {
                        Text(ConfigurationText.shortPath(editor.path)).font(.mono(TypeSize.meta))
                        if let note = editor.note {
                            Text(" · \(note)")
                        }
                    }
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                    .lineLimit(1)
                    .truncationMode(.middle)
                }
                Spacer(minLength: 8)
                Button("Open in VS Code") { LocalOpen.vscode(editor.path) }
                    .buttonStyle(.nest())
                Button("Reveal in Finder") { LocalOpen.reveal(editor.path) }
                    .buttonStyle(.nest())
            }
            .padding(EdgeInsets(top: 16, leading: 20, bottom: 12, trailing: 20))
            .overlay(alignment: .bottom) { Separator() }
            if editor.onDisk != nil {
                HStack(spacing: 10) {
                    StatusMark(tone: .waiting, hollow: false, slot: false, animates: false)
                    Text("This file changed on disk since you opened it.")
                        .foregroundStyle(Palette.t1)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    Button("Reload") { editor.reload() }
                        .buttonStyle(.nest())
                    Button("Keep mine") { editor.keepMine() }
                        .buttonStyle(.nest())
                }
                .font(.ui(TypeSize.ui))
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(StatusTone.waiting.soft, in: .rounded(8))
                .overlay(
                    RoundedRectangle.rounded(8)
                        .strokeBorder(StatusTone.waiting.color.opacity(0.35), lineWidth: 1)
                )
                .padding(.horizontal, 20)
                .padding(.top, 12)
            }
            TextEditor(text: $editor.text)
                .font(.mono(TypeSize.meta))
                .lineSpacing(4)
                .foregroundStyle(Palette.t1)
                .scrollContentBackground(.hidden)
                .disabled(!editor.loaded)
                .padding(10)
                .background(Palette.windowOpaque, in: .rounded(8))
                .overlay(RoundedRectangle.rounded(8).strokeBorder(Palette.divider, lineWidth: 1))
                .padding(.horizontal, 20)
                .padding(.vertical, 12)
                .accessibilityLabel(editor.title)
            HStack(spacing: 8) {
                Group {
                    // The daemon's reason it refused the text, such as invalid TOML.
                    if let error = editor.error {
                        Text(error)
                            .foregroundStyle(StatusTone.failed.color)
                            .textSelection(.enabled)
                            .lineLimit(3)
                    } else {
                        Text(ConfigurationText.editorFooter).foregroundStyle(Palette.t3)
                    }
                }
                .font(.ui(TypeSize.meta))
                .frame(maxWidth: .infinity, alignment: .leading)
                Button("Cancel") { store.closeEditor() }
                    .buttonStyle(.nest())
                Button("Save") { save() }
                    .buttonStyle(.nest(.primary))
                    .keyboardShortcut("s")
                    .disabled(!editor.loaded || editor.saving)
            }
            .padding(EdgeInsets(top: 12, leading: 20, bottom: 16, trailing: 20))
            .overlay(alignment: .top) { Separator() }
        }
        .foregroundStyle(Palette.t1)
        .frame(maxWidth: 800, maxHeight: 660)
        .sheetSurface()
    }

    private func save() {
        let store = shell.model.configuration
        let title = editor.title
        shell.settingsChange("Could not save \(title)") {
            if try await editor.save() {
                shell.show("Saved \(title)", kind: .done)
                store.closeEditor()
            }
        }
    }
}

// MARK: Copy to Shared

/// What copying an engine's setup to Shared adds, replaces and leaves, with Compare and
/// "Keep instructions as they are".
private struct CopySheet: View {
    let flow: CopyFlow
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent

    var body: some View {
        let store = shell.model.configuration
        VStack(alignment: .leading, spacing: 0) {
            Text(ConfigurationText.copyTitle(flow.engine))
                .font(.ui(TypeSize.body, .semibold))
            Text(ConfigurationText.copyIntro(flow.preview))
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t2)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 4)
                .padding(.bottom, 8)
            if flow.preview.instructions != nil {
                CopySectionRow(title: "Instructions") {
                    Text(ConfigurationText.replaceWarning(flow.engine))
                        .foregroundStyle(
                            flow.keepInstructions ? Palette.t3 : StatusTone.waiting.color
                        )
                        .fixedSize(horizontal: false, vertical: true)
                    HStack(spacing: 14) {
                        Button(flow.compare == nil ? "Compare the two files" : "Hide the files") {
                            shell.settingsChange("Could not read the instructions") {
                                try await store.toggleCompare()
                            }
                        }
                        .buttonStyle(.nest())
                        Checkbox(
                            isOn: flow.keepInstructions, label: "Keep instructions as they are"
                        ) {
                            store.setKeepInstructions(!flow.keepInstructions)
                        }
                    }
                    .padding(.top, 6)
                    if let compare = flow.compare {
                        HStack(alignment: .top, spacing: 8) {
                            ComparePane(
                                title: "\(ConfigurationText.engineName(flow.engine))'s",
                                text: compare.engine)
                            ComparePane(title: "Shared now", text: compare.shared)
                        }
                        .padding(.top, 8)
                    }
                }
            }
            ForEach(ConfigurationText.copySections(flow.preview, engine: flow.engine)) {
                section in
                CopySectionRow(title: section.title) {
                    if let lead = section.lead {
                        let bold = Text(lead).fontWeight(.semibold)
                        Text("\(bold)\(section.names.map { " \($0)" } ?? "")")
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    ForEach(section.notes, id: \.self) { note in
                        Text(note)
                            .foregroundStyle(Palette.t3)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            HStack(spacing: 8) {
                Spacer()
                Button("Cancel") { store.cancelCopy() }
                    .buttonStyle(.nest())
                Button("Copy to Shared") {
                    shell.settingsChange("Could not copy to Shared") { try await store.applyCopy() }
                }
                .buttonStyle(.nest(.primary))
                .disabled(store.busy.contains("copy:\(flow.engine)"))
                .keyboardShortcut(.defaultAction)
            }
            .padding(.top, 16)
        }
        .font(.ui(TypeSize.ui))
        .foregroundStyle(Palette.t1)
        .padding(20)
        .frame(width: 640)
        .sheetSurface()
        .accessibilityElement(children: .contain)
        .accessibilityLabel(ConfigurationText.copyTitle(flow.engine))
    }
}

private struct CopySectionRow<Content: View>: View {
    let title: String
    @ViewBuilder let content: () -> Content

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Text(title)
                .font(.ui(TypeSize.ui, .medium))
                .frame(width: 130, alignment: .leading)
            VStack(alignment: .leading, spacing: 3) { content() }
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.vertical, 10)
        .overlay(alignment: .top) { Separator() }
    }
}

private struct ComparePane: View {
    let title: String
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.ui(TypeSize.meta, .medium)).foregroundStyle(Palette.t2)
            ScrollView {
                Text(text.isEmpty ? "Empty" : text)
                    .font(.mono(TypeSize.meta))
                    .foregroundStyle(text.isEmpty ? Palette.t3 : Palette.t1)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(8)
            }
            .frame(height: 180)
            .background(Palette.windowOpaque, in: .rounded(6))
            .overlay(RoundedRectangle.rounded(6).strokeBorder(Palette.divider, lineWidth: 1))
        }
    }
}

/// A checkbox in the user's accent.
struct Checkbox: View {
    let isOn: Bool
    let label: String
    let toggle: () -> Void
    @Environment(\.accentColors) private var accent

    var body: some View {
        Button(action: toggle) {
            HStack(spacing: 7) {
                RoundedRectangle.rounded(3.5)
                    .fill(isOn ? accent.accent : Palette.soft)
                    .overlay(
                        RoundedRectangle.rounded(3.5)
                            .strokeBorder(isOn ? .clear : Palette.divider, lineWidth: 1)
                    )
                    .overlay {
                        if isOn {
                            Image(systemName: "checkmark")
                                .font(.system(size: 8, weight: .bold))
                                .foregroundStyle(accent.onAccent)
                        }
                    }
                    .frame(width: 14, height: 14)
                Text(label)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .accessibilityAddTraits(isOn ? [.isToggle, .isSelected] : .isToggle)
    }
}

// MARK: Forms

/// Add server or Edit: a command with its arguments and environment, or a URL with its
/// headers.
private struct ServerFormSheet: View {
    @State var form: MCPServerForm
    let repo: String?
    @Environment(Shell.self) private var shell
    @State private var removing = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(form.isNew ? "Add server" : "Edit \(form.name)")
                .font(.ui(TypeSize.body, .semibold))
            Text(
                repo == nil
                    ? "Nest writes it into every engine that uses shared MCP servers."
                    : "Saved in the project's .mcp.json, which only Claude reads."
            )
            .foregroundStyle(Palette.t2)
            FormLine(label: "Name") {
                if form.isNew {
                    CardField(placeholder: "playwright", text: $form.name)
                } else {
                    Text(form.name).font(.mono(TypeSize.ui))
                }
            }
            FormLine(label: "Kind") {
                SegmentPicker(
                    options: MCPTransport.choices.map {
                        ($0, $0 == .stdio ? "Command" : $0.rawValue.uppercased())
                    },
                    selection: form.transport
                ) { form.transport = $0 }
            }
            if form.transport == .stdio {
                FormLine(label: "Command") {
                    CardField(placeholder: "npx", text: $form.command)
                }
                FormLine(label: "Arguments") {
                    LinesField(placeholder: "One per line", text: $form.args)
                }
                FormLine(label: "Environment") {
                    LinesField(placeholder: "KEY=value, one per line", text: $form.env)
                }
            } else {
                FormLine(label: "URL") {
                    CardField(placeholder: "https://example.com/mcp", text: $form.url)
                }
                FormLine(label: "Headers") {
                    LinesField(placeholder: "Name: value, one per line", text: $form.headers)
                }
            }
            HStack(spacing: 8) {
                if !form.isNew {
                    Button("Remove") { removing = true }
                        .buttonStyle(.nest(.danger))
                }
                Spacer()
                Button("Cancel") { shell.configurationForm = nil }
                    .buttonStyle(.nest())
                Button(form.isNew ? "Add" : "Save") { save() }
                    .buttonStyle(.nest(.primary))
                    .disabled(form.spec == nil)
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
            "Remove \(form.name)?", isPresented: $removing, titleVisibility: .visible
        ) {
            Button("Remove", role: .destructive) { remove() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(
                repo == nil
                    ? "It is removed from every engine that uses shared MCP servers. A backup is kept."
                    : "It is removed from the project's .mcp.json.")
        }
    }

    private func save() {
        guard let spec = form.spec else { return }
        let name = form.trimmedName
        let store = shell.model.configuration
        let repo = repo
        shell.settingsChange("Could not save \(name)") {
            if let repo {
                try await store.saveRepoServer(repo, name, spec)
            } else {
                try await store.saveServer(name, spec)
            }
            shell.configurationForm = nil
        }
    }

    private func remove() {
        let name = form.trimmedName
        let store = shell.model.configuration
        let repo = repo
        shell.settingsChange("Could not remove \(name)") {
            if let repo {
                try await store.deleteRepoServer(repo, name)
            } else {
                try await store.deleteServer(name)
            }
            shell.configurationForm = nil
        }
    }
}

/// New skill: a name and a line saying when to use it; the new SKILL.md opens next.
private struct SkillFormSheet: View {
    let repo: String?
    @Environment(Shell.self) private var shell
    @State private var name = ""
    @State private var description = ""

    var body: some View {
        let valid = ConfigurationText.isValidSkillName(name)
        VStack(alignment: .leading, spacing: 10) {
            Text("New skill").font(.ui(TypeSize.body, .semibold))
            Text(
                repo == nil
                    ? "Made in the shared skills folder, so every engine can use it."
                    : "Made in the project's .claude/skills, which only Claude reads."
            )
            .foregroundStyle(Palette.t2)
            FormLine(label: "Name") {
                CardField(placeholder: "release-notes", text: $name)
            }
            FormLine(label: "Description") {
                CardField(placeholder: "When the agent should use it", text: $description)
            }
            if !name.isEmpty && !valid {
                Text("Lower case letters, digits and dashes only.")
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(StatusTone.failed.color)
            }
            HStack(spacing: 8) {
                Spacer()
                Button("Cancel") { shell.configurationForm = nil }
                    .buttonStyle(.nest())
                Button("Create") { create() }
                    .buttonStyle(.nest(.primary))
                    .disabled(!valid)
                    .keyboardShortcut(.defaultAction)
            }
            .padding(.top, 6)
        }
        .font(.ui(TypeSize.ui))
        .foregroundStyle(Palette.t1)
        .padding(20)
        .frame(width: 460)
        .sheetSurface()
    }

    private func create() {
        let store = shell.model.configuration
        let (name, description, repo) = (name, description, repo)
        shell.settingsChange("Could not make \(name)") {
            if let repo {
                try await store.createRepoSkill(repo, name: name, description: description)
                shell.configurationForm = nil
                if let path = store.repos[repo]?.skills.first(where: { $0.name == name })?.path {
                    shell.editConfiguration(path, title: name, note: "project skill")
                }
            } else {
                try await store.createSkill(name: name, description: description)
                shell.configurationForm = nil
                if let skill = store.page?.shared.skills.items.first(where: { $0.name == name }) {
                    shell.editConfiguration(skill.path, title: name, note: "shared skill")
                }
            }
        }
    }
}

private struct FormLine<Content: View>: View {
    let label: String
    @ViewBuilder let content: () -> Content

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(label)
                .foregroundStyle(Palette.t2)
                .frame(width: 92, alignment: .leading)
            content().frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

/// A few lines of plain text in mono, such as arguments.
private struct LinesField: View {
    let placeholder: String
    @Binding var text: String

    var body: some View {
        TextEditor(text: $text)
            .font(.mono(TypeSize.meta))
            .scrollContentBackground(.hidden)
            .frame(height: 54)
            .padding(4)
            .background(Palette.soft, in: .rounded(Radius.button))
            .overlay(alignment: .topLeading) {
                Placeholder(text: placeholder, shown: text.isEmpty)
                    .font(.ui(TypeSize.meta))
                    .padding(.leading, 9)
                    .padding(.top, 4)
                    .allowsHitTesting(false)
            }
            .accessibilityLabel(placeholder)
    }
}

/// A few choices side by side, the chosen one in the accent.
struct SegmentPicker<Value: Hashable>: View {
    let options: [(Value, String)]
    let selection: Value
    let select: (Value) -> Void
    @Environment(\.accentColors) private var accent

    var body: some View {
        HStack(spacing: 2) {
            ForEach(options, id: \.0) { value, title in
                let on = value == selection
                Button {
                    select(value)
                } label: {
                    Text(title)
                        .font(.ui(TypeSize.button, on ? .medium : .regular))
                        .foregroundStyle(on ? accent.onAccent : Palette.t2)
                        .padding(.horizontal, 10)
                        .frame(height: 22)
                        .background(on ? accent.accent : .clear, in: .rounded(5))
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .pointerStyle(.link)
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
        .padding(2)
        .background(Palette.soft, in: .rounded(Radius.button))
        .fixedSize()
    }
}
