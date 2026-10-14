import HarnessKit
import SwiftUI

/// The pixies down the left, as the sidebar lists chats, with New pixie. Drag a pixie onto
/// another to put it there; Move Up and Move Down in its menu do the same by keyboard.
struct PixieList: View {
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @Environment(\.glass) private var glass
    /// The pixie being dragged, for where the drop line shows.
    @State private var dragged: String?

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
                    let ids = pixies.map(\.id)
                    ForEach(pixies) { pixie in
                        PixieRow(pixie: pixie, listed: ids, dragged: $dragged)
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
        // A drag that ends outside the list leaves nothing behind.
        .onDisappear { dragged = nil }
    }
}

/// A pixie: its sprite, name and @slug; the sprite glows in its colour while its chat
/// runs, and a count shows what waits for the user.
private struct PixieRow: View {
    let pixie: Pixie
    /// The listed pixies' ids, in order.
    let listed: [String]
    @Binding var dragged: String?
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @Environment(\.glass) private var glass
    @Environment(\.reducedMotion) private var reduceMotion
    @State private var hovering = false
    /// Another pixie is dragged over this one.
    @State private var targeted = false

    /// What a drag carries: "pixie:<id>", so other text dropped here is ignored.
    static func payload(_ id: String) -> String { Pixie.repoPrefix + id }

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
        .overlay(alignment: dropsBelow ? .bottom : .top) {
            if targeted && dragged != pixie.id {
                Capsule()
                    .fill(accent.accent)
                    .frame(height: 2)
                    .offset(y: dropsBelow ? 2 : -2)
                    .allowsHitTesting(false)
            }
        }
        .pointerStyle(.link)
        .onHover { inside in
            hovering = inside
            // No hover arrives while a drag runs: one now means the drag ended, dropped
            // elsewhere or cancelled, which SwiftUI does not report.
            if inside {
                dragged = nil
            }
        }
        .onTapGesture { shell.selectPixie(pixie.id) }
        .onDrag {
            dragged = pixie.id
            return NSItemProvider(object: Self.payload(pixie.id) as NSString)
        } preview: {
            SpriteView(mascot: pixie.mascot, color: pixie.color, size: 28)
                .padding(6)
                .background(glass.surface, in: glass.rounded(glass.radius.item))
        }
        .onDrop(of: [.plainText], isTargeted: $targeted) { providers in
            drop(providers)
        }
        .contextMenu {
            Button {
                shell.selectPixie(pixie.id)
                withAnimation(.smooth(duration: 0.22)) { shell.pixieDetailsOpen = true }
            } label: {
                Label("Details", systemImage: Icon.rightPanel)
            }
            Divider()
            Button("Move Up") { shell.movePixie(pixie.id, by: -1) }
                .disabled(listed.first == pixie.id)
            Button("Move Down") { shell.movePixie(pixie.id, by: 1) }
                .disabled(listed.last == pixie.id)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(
            "\(pixie.name), @\(pixie.slug)\(running ? ", running" : "")\(waiting > 0 ? ", \(waiting) need you" : "")"
        )
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
        .accessibilityAction { shell.selectPixie(pixie.id) }
        .accessibilityAction(named: "Move Up") { shell.movePixie(pixie.id, by: -1) }
        .accessibilityAction(named: "Move Down") { shell.movePixie(pixie.id, by: 1) }
    }

    /// A pixie dragged down the list lands below this one, else above it.
    private var dropsBelow: Bool {
        guard let dragged, let from = listed.firstIndex(of: dragged),
            let to = listed.firstIndex(of: pixie.id)
        else { return false }
        return from < to
    }

    private func drop(_ providers: [NSItemProvider]) -> Bool {
        guard let provider = providers.first else { return false }
        let target = pixie.id
        // Called on a background queue: nonisolated, then back to the main actor.
        _ = provider.loadObject(ofClass: NSString.self) { @Sendable text, _ in
            guard let text = text as? String, let id = Pixie.id(ofRepo: text) else { return }
            Task { @MainActor in shell.movePixie(id, onto: target) }
        }
        dragged = nil
        return true
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
