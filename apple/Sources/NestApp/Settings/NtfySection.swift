import NestKit
import SwiftUI

/// ntfy's switch in Settings > Notifications, with its fields under it while on, saved on the
/// daemon as they change; a refused one goes back (B130). The daemon turns it on only with a
/// topic, so turning it on with none makes a long random one, which the user can change.
struct NtfyFields: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.notificationRules
        // A stack, not a group: with no rules yet a group is nothing, and nothing has no task.
        VStack(alignment: .leading, spacing: 0) {
            if let ntfy = store.rules?.ntfy {
                VStack(alignment: .leading, spacing: 0) {
                    SettingsRow(label: "Send to ntfy") {
                        Switch(isOn: ntfy.enabled) {
                            shell.saveNtfy {
                                if $0.enabled {
                                    $0.enabled = false
                                } else {
                                    $0.turnOn()
                                }
                            }
                        }
                        .accessibilityLabel("Send to ntfy")
                    }
                    if ntfy.enabled {
                        NtfyDetails(ntfy: ntfy)
                    }
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
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            NtfyField(label: "Server", value: ntfy.server) { server in
                shell.saveNtfy { $0.server = server.trimmingCharacters(in: .whitespaces) }
            }
            NtfyField(label: "Topic", value: ntfy.topic ?? "") { topic in
                shell.saveNtfy { $0.topic = Self.optional(topic) }
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
