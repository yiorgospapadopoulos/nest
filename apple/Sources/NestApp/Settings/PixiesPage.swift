import NestKit
import SwiftUI

/// The pixies with Open, Show hidden pixies and New pixie, then what new pixies start
/// with, the habits' switches and where reports go (B81).
struct PixiesPage: View {
    var body: some View {
        PixieListSection()
        PixieDefaultsSections()
    }
}

private struct PixieListSection: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let pixies = shell.listedPixies
        SettingsSection(title: "Your pixies", bare: true) {
            VStack(alignment: .leading, spacing: 0) {
                if pixies.isEmpty {
                    Text("No pixies yet")
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(Palette.t3)
                        .padding(.vertical, 8)
                        .overlay(alignment: .bottom) { Separator() }
                }
                ForEach(pixies) { pixie in
                    SettingsListRow(
                        title: pixie.name, detail: pixie.hidden ? "Hidden" : pixie.autonomy.label
                    ) {
                        SpriteView(mascot: pixie.mascot, color: pixie.color, size: 20)
                            .frame(width: 26, height: 26)
                            .background(Palette.soft, in: .rounded(6))
                            .opacity(pixie.hidden ? 0.5 : 1)
                    } trailing: {
                        Button("Open") {
                            shell.openPixie(pixie.id)
                            shell.showMainWindow()
                        }
                        .buttonStyle(.nest(.soft))
                        .accessibilityLabel("Open \(pixie.name)")
                    }
                }
            }
            .overlay(alignment: .top) { Separator() }
            SettingsRow(label: "Show hidden pixies") {
                Switch(isOn: shell.showsHiddenPixies) { shell.showsHiddenPixies.toggle() }
                    .accessibilityLabel("Show hidden pixies")
            }
            Button {
                shell.createPixie(CreatePixieRequest(name: "New pixie"), details: true)
                shell.showMainWindow()
            } label: {
                Label("New pixie", systemImage: Icon.plus)
            }
            .buttonStyle(.nest(.soft))
            .padding(.top, 10)
        }
    }
}

private struct PixieDefaultsSections: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.pixieSettings
        let settings = store.settings ?? PixieSettings()
        let loaded = store.settings != nil
        Group {
            SettingsSection(title: "New pixies start with") {
                SettingsRow(label: "Model") {
                    DropdownMenu(
                        title: settings.model.map { shell.agents.label(for: $0) }
                            ?? "Same as Agents"
                    ) {
                        ModelItems(
                            current: settings.model,
                            defaultItem: .init(detail: "Same as Agents") {
                                change { $0.model = nil }
                            }
                        ) { info in change { $0.model = info.value } }
                    }
                }
                SettingsRow(label: "Autonomy") {
                    DropdownMenu(title: settings.autonomy.label, width: 130) {
                        ForEach(Autonomy.choices, id: \.self) { autonomy in
                            Button(autonomy.label) { change { $0.autonomy = autonomy } }
                        }
                    }
                }
                SettingsRow(label: "Project files") {
                    Segmented(
                        options: ProjectAccess.choices.map { ($0, $0.label) },
                        selection: settings.projectAccess
                    ) { access in change { $0.projectAccess = access } }
                }
                SettingsRow(label: "Projects") {
                    DropdownMenu(
                        title: PixieSettingsText.projectsLabel(settings.projects), width: 150
                    ) {
                        ForEach([PixieProjects.all, .current], id: \.self) { projects in
                            Button(PixieSettingsText.projectsLabel(projects)) {
                                change { $0.projects = projects }
                            }
                        }
                    }
                }
                NumberRow(
                    label: "Chats running at once", value: settings.maxRunning,
                    choices: PixieSettingsText.maxRunningChoices
                ) { value in change { $0.maxRunning = value } }
                NumberRow(
                    label: "Chats started per day", value: settings.maxPerDay,
                    choices: PixieSettingsText.maxPerDayChoices
                ) { value in change { $0.maxPerDay = value } }
            }
            SettingsSection(title: "Habits") {
                SettingsRow(label: "Pause all habits") {
                    Switch(isOn: settings.habitsPaused) {
                        change { $0.habitsPaused.toggle() }
                    }
                    .accessibilityLabel("Pause all habits")
                }
                SettingsRow(label: "Skip habit runs above") {
                    DropdownMenu(title: "\(settings.habitUsagePercent)%", width: 100) {
                        ForEach(
                            PixieSettingsText.choices(
                                PixieSettingsText.habitUsageChoices,
                                including: settings.habitUsagePercent), id: \.self
                        ) { percent in
                            Button("\(percent)%") { change { $0.habitUsagePercent = percent } }
                        }
                    }
                }
            }
            SettingsSection(title: "Reports") {
                SettingsRow(label: "Send to the phone from") {
                    Segmented(
                        options: [
                            (ReportSeverity.info, "Info"), (.warn, "Warnings"), (.action, "Action"),
                        ],
                        selection: settings.reportPush
                    ) { severity in change { $0.reportPush = severity } }
                }
            }
        }
        .disabled(!loaded)
        .task { try? await store.load() }
    }

    private func change(_ apply: @escaping (inout PixieSettings) -> Void) {
        let store = shell.model.pixieSettings
        shell.settingsChange("Could not change the pixie settings") {
            try await store.update(apply)
        }
    }
}

/// A number picked from a few choices, keeping one set elsewhere.
private struct NumberRow: View {
    let label: String
    let value: Int
    let choices: [Int]
    let pick: (Int) -> Void

    var body: some View {
        SettingsRow(label: label) {
            DropdownMenu(title: "\(value)", width: 70) {
                ForEach(PixieSettingsText.choices(choices, including: value), id: \.self) {
                    choice in
                    Button("\(choice)") { pick(choice) }
                }
            }
        }
    }
}
