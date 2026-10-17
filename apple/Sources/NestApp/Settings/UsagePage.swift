import NestKit
import SwiftUI

/// Settings > Usage (B86): what the usage popover shows, at the page's width, then the
/// usage settings.
struct UsagePage: View {
    var body: some View {
        UsagePanel(title: "Limits")
            .padding(.top, 18)
        UsageLimitsSection()
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
