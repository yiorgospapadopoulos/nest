import NestKit
import SwiftUI

/// Settings > Usage (B86): what the usage popover shows, at the page's width, then the
/// usage settings.
struct UsagePage: View {
    var body: some View {
        UsagePanel(title: "Limits")
            .padding(.top, 18)
        TopBarSection()
        UsageLimitsSection()
    }
}

/// Which engines the usage meter at the top right shows, on this Mac only (B94): a
/// checkmark per engine the daemon lists, in its order; a click on the row toggles it. One
/// not signed in shows once it is.
private struct TopBarSection: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let settings = shell.settings
        SettingsSection(title: "Top bar shows") {
            ForEach(
                shell.model.usage.meterEngines(
                    providers: shell.providers, hidden: settings.usageMeterHidden)
            ) { engine in
                SettingsRow(label: engine.name) {
                    if !engine.detail.isEmpty {
                        Text(engine.detail)
                            .font(.ui(TypeSize.meta))
                            .foregroundStyle(Palette.t3)
                    }
                    // A box, not a bare checkmark, so it reads as one of several choices.
                    ZStack {
                        RoundedRectangle(cornerRadius: 4)
                            .fill(engine.shown ? Palette.t1 : Color.clear)
                        RoundedRectangle(cornerRadius: 4)
                            .strokeBorder(engine.shown ? Palette.t1 : Palette.t3, lineWidth: 1.5)
                        Image(systemName: Icon.check)
                            .font(.system(size: 10, weight: .bold))
                            .foregroundStyle(Palette.windowOpaque)
                            .opacity(engine.shown ? 1 : 0)
                    }
                    .frame(width: 16, height: 16)
                }
                .contentShape(Rectangle())
                .onTapGesture { settings.setUsageMeter(engine.provider, shown: !engine.shown) }
                .accessibilityElement(children: .combine)
                .accessibilityAddTraits(engine.shown ? [.isButton, .isSelected] : .isButton)
                .accessibilityLabel("Show \(engine.name) in the top bar")
            }
        }
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
