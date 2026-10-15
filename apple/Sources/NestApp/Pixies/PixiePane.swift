import NestKit
import SwiftUI

/// A pixie's pane in the Pixies tab's workspace (B37): its one ongoing chat (D072) in the
/// same chrome as a chat's pane, tinted by its backdrop. It splits, moves, resizes,
/// maximizes and closes like a chat's pane.
struct PixiePane: View {
    let pixie: Pixie
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(spacing: 0) {
            PixiePaneHeader(pixie: pixie)
            Rectangle().fill(Palette.divider).frame(height: 1)
            Group {
                if let chat = pixie.chatSessionID {
                    // A new chat (after a reset or a fresh run) is a fresh transcript.
                    TranscriptView(chat: chat).id(chat)
                } else {
                    SayHi(pixie: pixie)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            if let chat = pixie.chatSessionID {
                PendingReviewBar(chat: chat)
            }
            Composer(pixie: pixie.id)
        }
        .modifier(
            PaneChrome(pane: pixie.id, chat: pixie.chatSessionID, backdrop: pixie.background)
        )
        // Its reports are read once its pane is on screen, as reports arrive too (B42).
        .task(id: ReadKey(unread: shell.reports.unread(of: pixie.id), visible: visible)) {
            if visible && shell.reports.unread(of: pixie.id) > 0 {
                shell.markReportsRead(of: pixie.id)
            }
        }
        // The daemon lists no pixie chats: read this one so its state and context show.
        .task(id: pixie.chatSessionID) {
            guard let chat = pixie.chatSessionID, shell.sessions.session(chat) == nil else {
                return
            }
            try? await shell.sessions.fetch(chat)
        }
    }

    /// The app is on screen.
    private var visible: Bool { shell.model.visibility.isVisible }
}

private struct ReadKey: Hashable {
    let unread: Int
    let visible: Bool
}

/// Grip, sprite, name, @slug and the chat's status, then Details, maximize and close;
/// drag it to move the pane, double click to maximize.
private struct PixiePaneHeader: View {
    let pixie: Pixie
    @Environment(Shell.self) private var shell
    @Environment(\.paneFit) private var fit

    var body: some View {
        let session = pixie.chatSessionID.flatMap(shell.sessions.session)
        let tone = session.map(shell.tone(of:)) ?? .done
        let showing = shell.pixieDetailsOpen && shell.workspaceState.layout.focused == pixie.id
        HStack(spacing: 8) {
            GripDots()
                .foregroundStyle(Palette.t3)
                .frame(width: 14, height: 24)
                .contentShape(Rectangle())
                .help("Drag to move")
            SpriteView(mascot: pixie.mascot, color: pixie.color, size: 16)
                .allowsHitTesting(false)
            Text(pixie.name)
                .font(.ui(TypeSize.ui, .medium))
                .foregroundStyle(Palette.t1)
                .lineLimit(1)
                .layoutPriority(0.5)
                .allowsHitTesting(false)
            if fit.showsPlaceName {
                Text("@\(pixie.slug)")
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t3)
                    .lineLimit(1)
                    .allowsHitTesting(false)
            }
            if let session {
                StatusLabel(
                    tone: tone, label: shell.statusLabel(of: session),
                    hollow: shell.isHollow(session), showsLabel: fit.showsStatusLabel
                )
                .allowsHitTesting(false)
            }
            Spacer(minLength: 0)
            Button {
                shell.togglePixieDetails(pixie.id)
            } label: {
                if fit.showsElapsed {
                    Label("Details", systemImage: Icon.rightPanel)
                } else {
                    Image(systemName: Icon.rightPanel)
                }
            }
            .buttonStyle(.nest(showing ? .soft : .plain, iconOnly: !fit.showsElapsed))
            .help(showing ? "Hide details" : "Show details")
            .accessibilityLabel("Details")
            .accessibilityAddTraits(showing ? .isSelected : [])
            PaneButtons(pane: pixie.id)
        }
        .padding(.leading, 10)
        .padding(.trailing, 8)
        .frame(height: Metrics.headerHeight)
        // Behind the content, as in a chat's header, so the buttons never wait to see
        // whether a second click follows.
        .background {
            Color.clear
                .contentShape(Rectangle())
                .onTapGesture(count: 2) { shell.toggleMaximize(pixie.id) }
        }
        .modifier(PaneDragHandle(pane: pixie.id, title: pixie.name, tone: tone))
        .accessibilityElement(children: .contain)
        .accessibilityLabel(pixie.name)
    }
}

/// Before the first message: the big sprite and a hello.
private struct SayHi: View {
    let pixie: Pixie

    var body: some View {
        VStack(spacing: 6) {
            SpriteView(mascot: pixie.mascot, color: pixie.color, size: 64)
                .padding(.bottom, 10)
            Text("Say hi to \(pixie.name)")
                .font(.ui(TypeSize.body, .semibold))
                .foregroundStyle(Palette.t1)
            Text("It remembers what matters across chats.")
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t3)
        }
        .multilineTextAlignment(.center)
        .padding(24)
    }
}
