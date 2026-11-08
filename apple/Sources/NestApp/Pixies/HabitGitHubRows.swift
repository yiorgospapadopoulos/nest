import NestKit
import SwiftUI

/// A habit editor's GitHub triggers (B148): the events, then their filters once one is
/// chosen. With no project chosen, every project on GitHub counts.
struct HabitGitHubRows: View {
    @Binding var draft: GitHubDraft
    @Environment(Shell.self) private var shell

    var body: some View {
        let onGitHub = shell.app.repos.filter { $0.git && $0.remoteURL != nil }.map(\.name)
        DetailHeading(title: "Also runs on GitHub when")
        DetailGroup {
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
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t1)
                .padding(.horizontal, 8)
                .frame(height: Metrics.rowHeight)
            }
            if !draft.events.isEmpty {
                PickerRow(title: "Projects", value: TriggerText.projects(draft.projects)) {
                    OptionItem(title: "All projects", detail: "", checked: draft.projects.isEmpty) {
                        draft.projects = []
                    }
                    ForEach(onGitHub, id: \.self) { name in
                        OptionItem(
                            title: name, detail: "", checked: draft.projects.contains(name)
                        ) {
                            if draft.projects.contains(name) {
                                draft.projects.removeAll { $0 == name }
                            } else {
                                draft.projects.append(name)
                            }
                        }
                    }
                }
                FilterField(title: "Labels", prompt: "Any label", text: $draft.labels)
                FilterField(title: "Branches", prompt: "Any branch", text: $draft.branches)
                PickerRow(title: "From", value: draft.authors.label) {
                    ForEach(TriggerAuthors.choices, id: \.self) { authors in
                        OptionItem(
                            title: authors.label, detail: "", checked: draft.authors == authors
                        ) { draft.authors = authors }
                    }
                }
            }
        }
        DetailNote(text: TriggerText.githubNote)
    }
}

/// A comma separated list, such as labels or branches.
struct FilterField: View {
    let title: String
    let prompt: String
    @Binding var text: String

    var body: some View {
        HStack {
            Text(title)
                .foregroundStyle(Palette.t1)
            Spacer(minLength: 8)
            TextField(prompt, text: $text)
                .textFieldStyle(.plain)
                .padding(.horizontal, 6)
                .frame(width: 160, height: 22)
                .background(Palette.soft, in: .rounded(Radius.button))
                .accessibilityLabel(title)
        }
        .font(.ui(TypeSize.ui))
        .padding(.horizontal, 8)
        .frame(height: Metrics.rowHeight + 4)
    }
}
