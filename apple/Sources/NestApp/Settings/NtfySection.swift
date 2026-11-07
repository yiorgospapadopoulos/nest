import NestKit
import SwiftUI

/// ntfy's switch and fields, saved on the daemon as they change; a refused one goes back
/// (B130). Settings > Notifications shows them; the guide's step has the switch in its own
/// row, over the same fields.
struct NtfyFields: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.notificationRules
        // A stack, not a group: with no rules yet a group is nothing, and nothing has no task.
        VStack(alignment: .leading, spacing: 0) {
            if let ntfy = store.rules?.ntfy {
                VStack(alignment: .leading, spacing: 0) {
                    SettingsRow(label: "Send to ntfy") {
                        Switch(isOn: ntfy.enabled) { shell.saveNtfy { $0.enabled.toggle() } }
                            .accessibilityLabel("Send to ntfy")
                    }
                    NtfyDetails(ntfy: ntfy)
                }
                .overlay(alignment: .top) { Separator() }
            }
        }
        .task { try? await store.load() }
    }
}

/// The server, topic and link address, and the warning about public topics.
struct NtfyDetails: View {
    private static let warning =
        "Anyone who knows a public topic can read it. Use a long, random one."

    let ntfy: NtfySettings
    /// Turned on while there was no topic yet, which the daemon refuses: the first topic
    /// turns it on with it.
    var enablesWithTopic = false
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            NtfyField(label: "Server", value: ntfy.server) { server in
                shell.saveNtfy { $0.server = server.trimmingCharacters(in: .whitespaces) }
            }
            NtfyField(label: "Topic", value: ntfy.topic ?? "") { topic in
                let enables = enablesWithTopic
                shell.saveNtfy {
                    $0.topic = Self.optional(topic)
                    if enables, $0.topic != nil {
                        $0.enabled = true
                    }
                }
            }
            NtfyField(
                label: "Link address", value: ntfy.clickBaseURL ?? "",
                placeholder: "https://computer.tailnet.ts.net"
            ) { address in
                shell.saveNtfy { $0.clickBaseURL = Self.optional(address) }
            }
            WarningLine(text: Self.warning).padding(.top, 10)
        }
    }

    /// An emptied optional field is none.
    private static func optional(_ text: String) -> String? {
        let trimmed = text.trimmingCharacters(in: .whitespaces)
        return trimmed.isEmpty ? nil : trimmed
    }
}

extension Shell {
    func saveNtfy(_ apply: @escaping (inout NtfySettings) -> Void) {
        let store = model.notificationRules
        settingsChange("Could not save ntfy") { try await store.changeNtfy(apply) }
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
