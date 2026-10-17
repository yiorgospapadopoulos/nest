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

// MARK: Agents

struct AgentsPage: View {
    var body: some View {
        NewChatsSection()
        UsageLimitsSection()
        StuckSection()
    }
}

/// What new chats start with, kept on the daemon and shared with the iPhone.
private struct NewChatsSection: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let agents = shell.agents
        let defaults = agents.current
        SettingsSection(title: "New chats") {
            SettingsRow(label: "Model") {
                DropdownMenu(title: agents.label(for: defaults.model)) {
                    ModelItems(current: defaults.model) { info in
                        change { try await agents.setDefaultModel(info.value) }
                    }
                }
            }
            SettingsRow(label: "Thinking") {
                DropdownMenu(
                    title: defaults.effort?.label
                        ?? agents.defaultEffortLabel(for: defaults.model)
                ) {
                    ThinkingItems(
                        model: defaults.model, effort: defaults.effort, offersDefault: true
                    ) { effort in
                        change { try await agents.setDefaultEffort(effort) }
                    }
                }
            }
            SettingsRow(label: "Permissions") {
                DropdownMenu(title: PermissionMode.label(defaults.permissionMode)) {
                    PermissionItems(
                        modes: agents.permissionModes(for: defaults.model),
                        current: defaults.permissionMode, offersDefault: true
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

/// How often the daemon asks Claude for the limits (D031), and the warning before them.
private struct UsageLimitsSection: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let usage = shell.model.usage
        let settings = usage.settings
        SettingsSection(title: "Usage limits") {
            SettingsRow(label: "Check limits") {
                DropdownMenu(title: UsageText.refreshInterval(usage.refreshMinutes)) {
                    ForEach(UsageText.refreshChoices, id: \.self) { minutes in
                        Button(UsageText.refreshInterval(minutes)) {
                            change { try await usage.setRefreshMinutes(minutes) }
                        }
                    }
                }
                .disabled(settings == nil)
            }
            SettingsRow(label: "Warn me at") {
                DropdownMenu(
                    title: settings.map { UsageText.warnLevel($0.warnPercent) } ?? "-", width: 100
                ) {
                    ForEach(UsageText.warnChoices, id: \.self) { percent in
                        Button(UsageText.warnLevel(percent)) {
                            change { try await usage.setWarnPercent(percent) }
                        }
                    }
                }
                .disabled(settings == nil)
            }
            SettingsRow(label: "Also as a notification") {
                let on = settings?.warnNotify ?? false
                Switch(isOn: on) { change { try await usage.setWarnNotify(!on) } }
                    .disabled(settings == nil || settings?.warnPercent == nil)
                    .accessibilityLabel("Usage warning as a notification")
            }
        }
        .task { try? await usage.loadSettings() }
    }

    private func change(_ action: @escaping @MainActor () async throws -> Void) {
        shell.settingsChange("Could not change the usage settings", action)
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
