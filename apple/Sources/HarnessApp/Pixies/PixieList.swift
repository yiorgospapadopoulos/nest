import HarnessKit
import SwiftUI

/// The pixies down the left, as the sidebar lists chats, with New pixie.
struct PixieList: View {
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @Environment(\.glass) private var glass

    var body: some View {
        let pixies = shell.listedPixies
        let hidden = shell.pixies.pixies.count { $0.hidden }
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Text("Pixies")
                    .font(.ui(TypeSize.subhead, .bold))
                CountBadge(count: shell.pixies.visible.count, size: 18)
                Spacer(minLength: 0)
            }
            .padding(.leading, 6)
            .frame(height: 28)
            .padding(.bottom, 10)

            Button {
                shell.createPixie(CreatePixieRequest(name: "New pixie"), details: true)
            } label: {
                Label("New pixie", systemImage: Icon.plus)
                    .frame(maxWidth: .infinity)
                    .frame(height: 32)
                    .background(
                        accent.accent,
                        in: glass.rounded(min(glass.radius.item + 1, glass.radius.control))
                    )
                    .foregroundStyle(accent.onAccent)
                    .font(.ui(TypeSize.callout, .semibold))
                    .labelStyle(TightLabelStyle())
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .pointerStyle(.link)
            .padding(.bottom, 8)

            ScrollView {
                LazyVStack(spacing: 2) {
                    ForEach(pixies) { pixie in
                        PixieRow(pixie: pixie)
                    }
                }
                .padding(.horizontal, 4)
            }
            .scrollIndicators(.never)
            .padding(.horizontal, -4)

            if hidden > 0 {
                Button {
                    shell.showsHiddenPixies.toggle()
                } label: {
                    Label(
                        shell.showsHiddenPixies ? "Hide hidden" : "Show hidden (\(hidden))",
                        systemImage: shell.showsHiddenPixies ? "eye.slash" : "eye")
                }
                .buttonStyle(.harness(.ghost, height: 26))
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(EdgeInsets(top: 12, leading: 10, bottom: 10, trailing: 10))
        .frame(width: Sidebar.width)
        .frame(maxHeight: .infinity, alignment: .top)
        .panelGlass(radius: glass.radius.panel)
    }
}

/// A pixie: its sprite, name and @slug; the sprite glows in its colour while its chat
/// runs, and a count shows what waits for the user.
private struct PixieRow: View {
    let pixie: Pixie
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @Environment(\.glass) private var glass
    @Environment(\.reducedMotion) private var reduceMotion
    @State private var hovering = false

    var body: some View {
        let selected = shell.shownPixie?.id == pixie.id
        let chat = pixie.chatSessionID.flatMap(shell.sessions.session)
        let running = chat.map { $0.state == .running || $0.state == .starting } ?? false
        let waiting = shell.approvals.pending.count { $0.repo == "\(Pixie.repoPrefix)\(pixie.id)" }
        HStack(spacing: 10) {
            SpriteView(mascot: pixie.mascot, color: pixie.color, size: 28)
                .background {
                    if running {
                        RunningGlow(color: Color(hex: pixie.color), reduceMotion: reduceMotion)
                    }
                }
                .frame(width: 30)
                .opacity(pixie.hidden ? 0.5 : 1)
            VStack(alignment: .leading, spacing: 1) {
                Text(pixie.name)
                    .font(.ui(TypeSize.callout, selected ? .semibold : .regular))
                    .foregroundStyle(Palette.t1)
                    .lineLimit(1)
                Text(pixie.hidden ? "@\(pixie.slug) · Hidden" : "@\(pixie.slug)")
                    .font(.ui(TypeSize.caption))
                    .foregroundStyle(Palette.t3)
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if waiting > 0 {
                CountBadge(count: waiting, urgent: true, size: 18)
            } else if running {
                StatusDot(tone: .running, size: 7)
            }
        }
        .padding(.horizontal, 9)
        .padding(.vertical, 7)
        .background(
            selected ? accent.soft : hovering ? Palette.fill : .clear,
            in: glass.rounded(glass.radius.item)
        )
        .contentShape(Rectangle())
        .pointerStyle(.link)
        .onHover { hovering = $0 }
        .onTapGesture { shell.selectPixie(pixie.id) }
        .contextMenu {
            Button {
                shell.selectPixie(pixie.id)
                withAnimation(.smooth(duration: 0.22)) { shell.pixieDetailsOpen = true }
            } label: {
                Label("Details", systemImage: Icon.rightPanel)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(
            "\(pixie.name), @\(pixie.slug)\(running ? ", running" : "")\(waiting > 0 ? ", \(waiting) need you" : "")"
        )
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
        .accessibilityAction { shell.selectPixie(pixie.id) }
    }
}

/// A soft halo in the pixie's colour behind its sprite; steady with Reduce Motion.
private struct RunningGlow: View {
    let color: Color
    let reduceMotion: Bool

    var body: some View {
        if reduceMotion {
            halo(strong: true)
        } else {
            PhaseAnimator([false, true]) { strong in
                halo(strong: strong)
            } animation: { _ in
                .easeInOut(duration: DesignTokens.Motion.Duration.attention / 2)
            }
        }
    }

    private func halo(strong: Bool) -> some View {
        Circle()
            .fill(color.opacity(strong ? 0.38 : 0.18))
            .frame(width: 34, height: 34)
            .blur(radius: strong ? 7 : 5)
            .allowsHitTesting(false)
    }
}
