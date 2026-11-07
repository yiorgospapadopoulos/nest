import NestKit
import SwiftUI

/// The window while This Mac's daemon cannot be reached at launch (B130, screen Z): the line
/// that repairs the install, and Try again.
struct DaemonDownView: View {
    @Environment(AppController.self) private var controller
    @Environment(Shell.self) private var shell

    var body: some View {
        let service = controller.service
        let line = service.installCommand
        VStack(alignment: .leading, spacing: 0) {
            Text("Nest's background service isn't running")
                .font(.ui(24, .semibold))
                .padding(.bottom, 8)
                .accessibilityAddTraits(.isHeader)
            SetupLine(text: "Paste this in Terminal. Your chats stay.").padding(.bottom, 16)
            Text(line)
                .font(.mono(TypeSize.small))
                .lineSpacing(3)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(12)
                .background(Palette.soft, in: .rounded(7))
                .overlay(RoundedRectangle.rounded(7).strokeBorder(Palette.divider))
                .padding(.bottom, 16)
            HStack(spacing: 8) {
                CopyButton(text: line, kind: .primary, height: 30)
                Button("Try again") { controller.startService() }
                    .buttonStyle(.nest(.soft, height: 30))
                    .disabled(service.state == .starting)
                if service.state == .starting {
                    Fireflies()
                }
            }
            if case .failed(let reason) = service.state {
                SettingsFailure(text: reason).padding(.top, 8)
            }
        }
        .foregroundStyle(Palette.t1)
        .frame(width: 520)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Palette.windowOpaque)
        .ignoresSafeArea()
    }
}
