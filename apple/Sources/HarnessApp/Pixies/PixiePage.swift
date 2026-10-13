import HarnessKit
import SwiftUI

/// A pixie's page: its one ongoing chat over its background, and the details panel on
/// the right where everything about it is set (D057).
struct PixiePage: View {
    static let detailsWidth = 320.0

    let pixie: Pixie
    @Environment(Shell.self) private var shell
    @Environment(\.glass) private var glass

    var body: some View {
        HStack(spacing: glass.spacing.gap) {
            PixieChat(pixie: pixie)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            if shell.pixieDetailsOpen {
                PixieDetailsPanel(pixie: pixie)
                    .frame(width: Self.detailsWidth)
                    .frame(maxHeight: .infinity)
                    .panelGlass(radius: glass.radius.panel)
                    .transition(.move(edge: .trailing).combined(with: .opacity))
            }
        }
    }
}

/// The header, the transcript (or a hello before the first message) and the composer.
private struct PixieChat: View {
    let pixie: Pixie
    @Environment(Shell.self) private var shell
    @Environment(\.glass) private var glass

    var body: some View {
        let shape = glass.rounded(glass.radius.pane)
        VStack(spacing: 0) {
            PixieHeader(pixie: pixie)
            Rectangle().fill(Palette.hair).frame(height: 1)
            Group {
                if let chat = pixie.chatSessionID {
                    // A new chat (after a reset or a fresh run) is a fresh transcript.
                    TranscriptView(chat: chat).id(chat)
                } else {
                    SayHi(pixie: pixie)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            Composer(pixie: pixie.id)
        }
        .background(PixieBackdrop(background: pixie.background))
        .clipShape(shape)
        .panelGlass(radius: glass.radius.pane, tint: .reading)
        // The daemon lists no pixie chats: read this one so its state and context show.
        .task(id: pixie.chatSessionID) {
            guard let chat = pixie.chatSessionID, shell.sessions.session(chat) == nil else {
                return
            }
            try? await shell.sessions.fetch(chat)
        }
    }
}

/// Sprite, name, @slug and the chat's status, with the Details toggle.
private struct PixieHeader: View {
    let pixie: Pixie
    @Environment(Shell.self) private var shell

    var body: some View {
        let session = pixie.chatSessionID.flatMap(shell.sessions.session)
        HStack(spacing: 9) {
            SpriteView(mascot: pixie.mascot, color: pixie.color, size: 24)
            Text(pixie.name)
                .font(.ui(13.5, .semibold))
                .foregroundStyle(Palette.t1)
                .lineLimit(1)
            Text("@\(pixie.slug)")
                .font(.ui(TypeSize.small))
                .foregroundStyle(Palette.t3)
                .lineLimit(1)
            if let session {
                StatusPill(
                    tone: shell.tone(of: session), label: shell.statusLabel(of: session),
                    hollow: shell.isHollow(session))
            }
            Spacer(minLength: 0)
            Button {
                withAnimation(.smooth(duration: 0.22)) { shell.pixieDetailsOpen.toggle() }
            } label: {
                Label("Details", systemImage: Icon.rightPanel)
            }
            .buttonStyle(.harness(shell.pixieDetailsOpen ? .plain : .ghost, height: 26))
            .help(shell.pixieDetailsOpen ? "Hide details" : "Show details")
            .accessibilityAddTraits(shell.pixieDetailsOpen ? .isSelected : [])
        }
        .padding(.leading, 14)
        .padding(.trailing, 8)
        .frame(height: 44)
    }
}

/// Before the first message: the big sprite and a hello.
private struct SayHi: View {
    let pixie: Pixie

    var body: some View {
        VStack(spacing: 6) {
            SpriteView(mascot: pixie.mascot, color: pixie.color, size: 96)
                .padding(.bottom, 10)
            Text("Say hi to \(pixie.name)")
                .font(.ui(TypeSize.headline, .semibold))
                .foregroundStyle(Palette.t1)
            Text("It remembers what matters across chats.")
                .font(.ui(TypeSize.callout))
                .foregroundStyle(Palette.t2)
        }
        .multilineTextAlignment(.center)
        .padding(24)
    }
}
