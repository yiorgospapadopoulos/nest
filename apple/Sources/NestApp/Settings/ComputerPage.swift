import AppKit
import NestKit
import SwiftUI

/// Settings > Computer use (B150): the master switch, the helper's two permissions as macOS
/// reports them, whether pixies may use it, and whether the
/// simulators and the shared browser can be used here. The status is read again whenever
/// Nest comes back, as the permissions change in System Settings.
struct ComputerPage: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.computer
        let settings = store.settings ?? ComputerUseSettings()
        VStack(alignment: .leading, spacing: 0) {
            SettingsSection(title: "") {
                SettingsRow(label: "Let chats use apps") {
                    Switch(isOn: settings.enabled) { change { $0.enabled.toggle() } }
                        .accessibilityLabel("Let chats use apps")
                }
            }
            if let status = store.status, status.kind(.mac) != nil {
                SettingsSection(title: "Permissions") {
                    ComputerPermissionRow(
                        title: "Accessibility for Nest Computer", permission: .accessibility,
                        granted: status.accessibility)
                    ComputerPermissionRow(
                        title: "Screen Recording for Nest", permission: .screenRecording,
                        granted: status.screenRecording)
                }
            }
            SettingsSection(title: "") {
                SettingsRow(label: "Pixies may use it") {
                    Switch(isOn: settings.pixies) { change { $0.pixies.toggle() } }
                        .accessibilityLabel("Pixies may use it")
                }
            }
            if let status = store.status {
                SettingsSection(title: "Simulators and browser") {
                    ForEach([ComputerKind.ios, .android, .browser], id: \.self) { kind in
                        KindRow(kind: kind, availability: status.kind(kind))
                    }
                }
            }
        }
        .disabled(store.settings == nil)
        .task { await load() }
        .onReceive(
            NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)
        ) { _ in Task { try? await store.loadStatus() } }
    }

    private func load() async {
        let store = shell.model.computer
        try? await store.loadSettings()
        try? await store.loadStatus()
    }

    private func change(_ edit: @escaping (inout ComputerUseSettings) -> Void) {
        let store = shell.model.computer
        shell.settingsChange("Could not change computer use") {
            try await store.update(edit)
            try? await store.loadStatus()
        }
    }
}

/// A permission the helper holds: on once macOS allows it. Turning it either way asks
/// macOS, which opens the right pane of System Settings, the only place it can change.
private struct ComputerPermissionRow: View {
    let title: String
    let permission: ComputerPermission
    /// Nil when the helper could not ask.
    let granted: Bool?
    @Environment(Shell.self) private var shell

    var body: some View {
        HStack(spacing: 16) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.ui(TypeSize.ui, .medium))
                    .fixedSize(horizontal: false, vertical: true)
                if granted == false {
                    HStack(spacing: 4) {
                        Text("Blocked in System Settings.")
                            .foregroundStyle(StatusTone.failed.color)
                        Button("Open", action: ask)
                            .buttonStyle(.plain)
                            .underline()
                            .foregroundStyle(Palette.t1)
                            .pointerStyle(.link)
                            .accessibilityLabel("Open System Settings for \(permission.title)")
                    }
                    .font(.ui(TypeSize.meta))
                }
            }
            Spacer(minLength: 8)
            Switch(isOn: granted == true, toggle: ask)
                .accessibilityLabel(title)
        }
        .padding(.vertical, 7)
        .frame(minHeight: 36)
        .overlay(alignment: .bottom) { Separator() }
    }

    private func ask() {
        let store = shell.model.computer
        shell.settingsChange("Could not ask macOS") { try await store.ask(permission) }
    }
}

/// A kind of device: ready, or why not and where to get what it needs.
private struct KindRow: View {
    let kind: ComputerKind
    let availability: ComputerAvailability?

    var body: some View {
        SettingsRow(label: kind.title) {
            if let availability, !availability.ready {
                SettingsValue(text: availability.reason ?? "Not available")
                if let link = availability.link.flatMap(SafeLink.url) {
                    Button("Get it") { NSWorkspace.shared.open(link) }
                        .buttonStyle(LinkButtonStyle())
                        .accessibilityLabel("Get \(kind.title)")
                }
            } else {
                SettingsValue(text: availability == nil ? "Not available" : "Ready")
            }
        }
    }
}
