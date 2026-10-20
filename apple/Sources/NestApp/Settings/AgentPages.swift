import NestKit
import SwiftUI

// MARK: Notifications

/// What reaches this Mac as a notification; the iPhone keeps its own choices.
struct NotificationsPage: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let settings = shell.settings
        let devices = shell.model.devices
        SettingsSection(title: "Notify me about") {
            ForEach(NotificationPreferences.kindToggles, id: \.title) { toggle in
                SettingsRow(label: toggle.title) {
                    Switch(isOn: settings.notifications[keyPath: toggle.path]) {
                        settings.notifications[keyPath: toggle.path].toggle()
                    }
                    .accessibilityLabel(toggle.title)
                }
                if toggle.path == \.pixieReports {
                    PixieReportLevelRow()
                }
            }
        }
        SettingsSection(title: "Delivery") {
            SettingsRow(label: "Sound") {
                Switch(isOn: settings.notifications.sound) {
                    settings.notifications.sound.toggle()
                }
                .accessibilityLabel("Sound")
            }
            SettingsRow(label: "iPhone push") {
                let on = (devices.pushDevices ?? 0) > 0
                StatusLabel(tone: on ? .review : .done, label: devices.pushText, hollow: !on)
            }
        }
        .task { try? await devices.loadPushStatus() }
    }
}

/// Which pixie reports reach the iPhone, one level for every pixie, kept on the daemon
/// (B85).
private struct PixieReportLevelRow: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.notificationRules
        SettingsRow(label: ReportSeverity.phoneLevelTitle) {
            Segmented(
                options: ReportSeverity.phoneLevels.map { ($0, $0.phoneLevelLabel) },
                selection: store.rules?.pixieReportLevel ?? .action
            ) { level in
                shell.settingsChange("Could not change where pixie reports go") {
                    try await store.setPixieReportLevel(level)
                }
            }
        }
        .disabled(store.rules == nil)
        .task { try? await store.load() }
    }
}

// MARK: Agents

struct AgentsPage: View {
    var body: some View {
        NewChatsSection()
        StuckSection()
    }
}

/// What new chats start with, kept on the daemon and shared with the iPhone: real choices
/// only (B94). The model menu has a section per engine, and the model chosen picks the
/// engine new chats run on; Thinking and Permissions follow that model.
private struct NewChatsSection: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let agents = shell.agents
        let defaults = agents.current
        let catalog = shell.providers.catalog(for: defaults.provider, claude: agents.catalog)
        let levels = catalog.thinkingLevels(for: defaults.model)
        SettingsSection(title: "New chats") {
            SettingsRow(label: "Model") {
                DropdownMenu(
                    title: shell.providers.modelTitle(
                        defaults.model, on: defaults.provider, claude: agents.catalog)
                ) {
                    EngineModelItems(provider: defaults.provider, current: defaults.model) {
                        info, provider in
                        let catalog = shell.providers.catalog(for: provider, claude: agents.catalog)
                        change {
                            try await agents.setDefaultModel(
                                info.value, provider: provider, catalog: catalog)
                        }
                    }
                }
            }
            SettingsRow(label: "Thinking") {
                DropdownMenu(
                    title: defaults.effort?.label ?? (levels.isEmpty ? "Not available" : "-")
                ) {
                    ThinkingItems(model: defaults.model, effort: defaults.effort, catalog: catalog)
                    { effort in
                        change { try await agents.setDefaultEffort(effort) }
                    }
                }
                .disabled(levels.isEmpty)
            }
            SettingsRow(label: "Permissions") {
                DropdownMenu(title: defaults.permissionMode.label) {
                    PermissionItems(
                        modes: catalog.permissionModes(for: defaults.model),
                        current: defaults.permissionMode
                    ) { mode in change { try await agents.setDefaultPermissionMode(mode) } }
                }
            }
            SettingsRow(label: "Work in") {
                Segmented(
                    options: [
                        (SessionMode.inPlace, "Current branch"), (.worktree, "New worktree"),
                    ],
                    selection: defaults.mode
                ) { mode in change { try await agents.setDefaultMode(mode) } }
            }
        }
    }

    private func change(_ action: @escaping @MainActor () async throws -> Void) {
        shell.settingsChange("Could not change the agent defaults", action)
    }
}

/// When the daemon flags a running chat as stuck (D036).
private struct StuckSection: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let settings = shell.model.stuck.settings
        SettingsSection(title: "Stuck chats") {
            ForEach(StuckThreshold.allCases, id: \.self) { threshold in
                let value = settings?[keyPath: threshold.keyPath] ?? 0
                SettingsRow(label: threshold.title) {
                    DropdownMenu(title: settings == nil ? "-" : threshold.label(value), width: 130)
                    {
                        ForEach(threshold.choices(including: value), id: \.self) { choice in
                            Button(threshold.label(choice)) {
                                shell.setStuckThreshold(threshold, to: choice)
                            }
                        }
                    }
                    .disabled(settings == nil)
                }
            }
        }
        .task { try? await shell.model.stuck.load() }
    }
}
