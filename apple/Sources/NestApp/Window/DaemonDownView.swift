import NestKit
import SwiftUI

/// The window while This Mac's daemon cannot be reached at launch (B130, screen Z): an
/// update's progress while one has the daemon down, else, once starting the service by itself
/// did not help, the line that repairs the install, and Try again.
struct DaemonDownView: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        Group {
            if case .updating(let update) = shell.daemonDown.screen {
                UpdatingNestView(update: update)
            } else {
                RepairView()
            }
        }
        .foregroundStyle(Palette.t1)
        .frame(width: 520)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Palette.windowOpaque)
        .ignoresSafeArea()
    }
}

private struct RepairView: View {
    @Environment(AppController.self) private var controller

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
    }
}

/// While the daemon is down for an update: never the repair line, as Nest sees to it. Looks
/// again every second, so the window moves on as soon as the daemon is back. One screen the
/// whole time (B130, fix 30b): the slow line's place is kept from the start, so nothing moves
/// when it appears.
private struct UpdatingNestView: View {
    let update: UpdateUnderWay
    @Environment(AppController.self) private var controller

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            VStack(alignment: .leading, spacing: 0) {
                Text("Updating Nest to \(update.toVersion)...")
                    .font(.ui(24, .semibold))
                    .padding(.bottom, 8)
                    .accessibilityAddTraits(.isHeader)
                Fireflies().padding(.top, 8)
                let slow = update.isSlow(at: context.date)
                SetupLine(text: "Taking longer than usual")
                    .padding(.top, 16)
                    .opacity(slow ? 1 : 0)
                    .accessibilityHidden(!slow)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                controller.followUpdate()
            }
        }
    }
}
