import AppKit
import NestKit
import SwiftUI

/// Settings > Terminal agents (B151): Claude Code, Codex, other AI apps and the `nest`
/// command, each switched on with its own level of access to Nest's chats. Read again when
/// Nest comes back, as another device may have changed it.
struct TerminalAgentsPage: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.terminalAgents
        VStack(alignment: .leading, spacing: 0) {
            ForEach(store.clients ?? []) { client in
                SettingsSection(title: "") {
                    ClientRow(client: client, busy: store.changing == client.kind)
                    if client.on, let line = client.commandLine {
                        SettingsRow(label: client.kind == .shell ? "Command" : "Run") {
                            SettingsValue(text: line, mono: true)
                        }
                    }
                }
            }
        }
        .task { try? await store.load() }
        .onReceive(
            NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)
        ) { _ in Task { try? await store.load() } }
    }
}

/// A client's switch, and while it is on, its level.
private struct ClientRow: View {
    let client: OutsideClient
    let busy: Bool
    @Environment(Shell.self) private var shell

    var body: some View {
        SettingsRow(label: client.label) {
            if client.on {
                DropdownMenu(title: (client.access ?? .unknown).title) {
                    ForEach(OutsideAccess.choices, id: \.self) { access in
                        OptionItem(
                            title: access.title, detail: "", checked: access == client.access
                        ) {
                            set(access)
                        }
                    }
                }
                .accessibilityLabel("\(client.label) access")
            }
            Switch(isOn: client.on) { set(client.on ? nil : .read) }
                .accessibilityLabel(client.label)
        }
        .disabled(busy)
    }

    private func set(_ access: OutsideAccess?) {
        let store = shell.model.terminalAgents
        let kind = client.kind
        shell.settingsChange("Could not change \(client.label)") {
            try await store.set(kind, access)
        }
    }
}
