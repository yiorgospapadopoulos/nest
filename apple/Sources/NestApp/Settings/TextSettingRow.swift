import NestKit
import SwiftUI

/// A short text in mono, or `unset` while there is none, with Change, which edits it in an
/// alert as Push to does.
struct TextSettingRow: View {
    let label: String
    let value: String?
    let unset: String
    /// The line under the alert's title.
    let message: String
    let placeholder: String
    let save: (String) -> Void
    @State private var editing = false
    @State private var text = ""

    var body: some View {
        SettingsRow(label: label) {
            if let value {
                SettingsValue(text: value, mono: true)
            } else {
                Text(unset)
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t3)
            }
            Button("Change") {
                text = value ?? ""
                editing = true
            }
            .buttonStyle(.nest(.soft))
            .accessibilityLabel("Change \(label)")
        }
        .alert(label, isPresented: $editing) {
            TextField(placeholder, text: $text)
            Button("Save") { save(text) }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(message)
        }
    }
}
