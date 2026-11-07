import NestKit
import SwiftUI

/// ntfy's switch and fields, saved on the daemon as they change; a refused one goes back
/// (B130). The guide's step and Settings > Notifications both show them.
struct NtfyFields: View {
    private static let warning =
        "Anyone who knows a public topic can read it. Use a long, random one."

    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.notificationRules
        // A stack, not a group: with no rules yet a group is nothing, and nothing has no task.
        VStack(alignment: .leading, spacing: 0) {
            if let ntfy = store.rules?.ntfy {
                VStack(alignment: .leading, spacing: 0) {
                    SettingsRow(label: "Send to ntfy") {
                        Switch(isOn: ntfy.enabled) { save { $0.enabled.toggle() } }
                            .accessibilityLabel("Send to ntfy")
                    }
                    NtfyField(label: "Server", value: ntfy.server) { server in
                        save { $0.server = server.trimmingCharacters(in: .whitespaces) }
                    }
                    NtfyField(label: "Topic", value: ntfy.topic ?? "") { topic in
                        save { $0.topic = Self.optional(topic) }
                    }
                    NtfyField(
                        label: "Link address", value: ntfy.clickBaseURL ?? "",
                        placeholder: "https://computer.tailnet.ts.net"
                    ) { address in
                        save { $0.clickBaseURL = Self.optional(address) }
                    }
                    WarningLine(text: Self.warning).padding(.top, 10)
                }
                .overlay(alignment: .top) { Separator() }
            }
        }
        .task { try? await store.load() }
    }

    /// An emptied optional field is none.
    private static func optional(_ text: String) -> String? {
        let trimmed = text.trimmingCharacters(in: .whitespaces)
        return trimmed.isEmpty ? nil : trimmed
    }

    private func save(_ apply: @escaping (inout NtfySettings) -> Void) {
        let store = shell.model.notificationRules
        shell.settingsChange("Could not save ntfy") { try await store.changeNtfy(apply) }
    }
}

/// A field that saves when it is left.
private struct NtfyField: View {
    let label: String
    let value: String
    var placeholder = ""
    let save: (String) -> Void
    @State private var typed: String?

    var body: some View {
        SettingsRow(label: label) {
            CardField(
                placeholder: placeholder,
                text: Binding(get: { typed ?? value }, set: { typed = $0 }),
                submit: commit, blur: commit
            )
            .accessibilityLabel(label)
            .frame(width: 280)
        }
        .onDisappear(perform: commit)
    }

    private func commit() {
        if let typed, typed != value {
            save(typed)
        }
        typed = nil
    }
}

struct NtfySection: View {
    var body: some View {
        SettingsSection(title: "ntfy", bare: true) { NtfyFields() }
    }
}
