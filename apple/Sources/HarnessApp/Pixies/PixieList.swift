import HarnessKit
import SwiftUI

/// The pixies down the left, as the sidebar lists chats, with New pixie. A click opens a
/// pixie's pane; drag one onto the workspace to split it like a chat, or onto another
/// pixie to put it there. Move Up and Move Down in its menu reorder by keyboard.
struct PixieList: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let pixies = shell.listedPixies
        let hidden = shell.pixies.pixies.count { $0.hidden }
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Text("Pixies")
                    .font(.ui(TypeSize.reading, .semibold))
                    .foregroundStyle(Palette.t1)
                CountBadge(count: shell.pixies.visible.count)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 8)
            .frame(height: 30)

            Button {
                shell.createPixie(CreatePixieRequest(name: "New pixie"), details: true)
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: Icon.plus).font(.system(size: 11, weight: .medium))
                    Text("New pixie")
                    Spacer(minLength: 0)
                }
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t2)
                .padding(.horizontal, 10)
                .frame(height: Metrics.rowHeight)
                .contentShape(Rectangle())
            }
            .buttonStyle(RowHoverStyle())
            .padding(.top, 2)
            .padding(.bottom, 8)

            ScrollView {
                LazyVStack(spacing: 0) {
                    let ids = pixies.map(\.id)
                    ForEach(pixies) { pixie in
                        PixieRow(pixie: pixie, listed: ids)
                    }
                }
            }
            .scrollIndicators(.never)

            if hidden > 0 {
                Button {
                    shell.showsHiddenPixies.toggle()
                } label: {
                    Label(
                        shell.showsHiddenPixies ? "Hide hidden" : "Show hidden (\(hidden))",
                        systemImage: shell.showsHiddenPixies ? "eye.slash" : "eye")
                }
                .buttonStyle(.harness(.plain))
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.leading, 4)
            }
        }
        .padding(EdgeInsets(top: 8, leading: 6, bottom: 8, trailing: 6))
        .frame(width: Sidebar.width)
        .frame(maxHeight: .infinity, alignment: .top)
        .sideSurface()
    }
}

/// A pixie: its sprite, name and @slug; a dot while its chat runs, and a count of what
/// waits for the user. Selected while its pane has focus, softly filled while it is open.
private struct PixieRow: View {
    let pixie: Pixie
    /// The listed pixies' ids, in order.
    let listed: [String]
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @State private var hovering = false
    /// Another pixie is dragged over this one.
    @State private var targeted = false

    var body: some View {
        let state = shell.app.pixieState
        let selected = state.layout.focused == pixie.id
        let open = state.layout.contains(pixie.id)
        let chat = pixie.chatSessionID.flatMap(shell.sessions.session)
        let running = chat.map { $0.state == .running || $0.state == .starting } ?? false
        let waiting = shell.approvals.pending.count { $0.repo == "\(Pixie.repoPrefix)\(pixie.id)" }
        HStack(spacing: 8) {
            SpriteView(mascot: pixie.mascot, color: pixie.color, size: 16)
                .frame(width: 18)
                .opacity(pixie.hidden ? 0.5 : 1)
            HStack(spacing: 6) {
                Text(pixie.name)
                    .foregroundStyle(pixie.hidden ? Palette.t2 : Palette.t1)
                    .layoutPriority(1)
                Text(pixie.hidden ? "@\(pixie.slug) · Hidden" : "@\(pixie.slug)")
                    .foregroundStyle(Palette.t3)
            }
            .font(.ui(TypeSize.ui))
            .lineLimit(1)
            .frame(maxWidth: .infinity, alignment: .leading)
            if waiting > 0 {
                CountBadge(count: waiting, urgent: true)
            } else if running {
                StatusDot(tone: .running)
            }
        }
        .padding(.horizontal, 10)
        .frame(height: 30)
        .background(
            selected ? accent.selection : (open || hovering) ? Palette.soft : .clear,
            in: .rounded(Radius.row)
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
        .onHover { hovering = $0 }
        .onTapGesture { shell.openPixie(pixie.id) }
        // The same drag as a sidebar chat's, so the workspace takes it like one.
        .onDrag {
            shell.dragging = .chat(pixie.id)
            return .chat(pixie.id)
        } preview: {
            SpriteView(mascot: pixie.mascot, color: pixie.color, size: 28)
                .padding(6)
                .background(Palette.sheet, in: .rounded(Radius.row))
        }
        .onDrop(of: [.harnessChat], isTargeted: $targeted) { _ in drop() }
        .opacity(dragged == pixie.id ? 0.45 : 1)
        .contextMenu {
            Button {
                shell.openPixie(pixie.id)
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
            "\(pixie.name), @\(pixie.slug)\(running ? ", running" : "")\(waiting > 0 ? ", \(waiting) need you" : "")\(open ? ", open" : "")"
        )
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
        .accessibilityAction { shell.openPixie(pixie.id) }
        .accessibilityAction(named: "Move Up") { shell.movePixie(pixie.id, by: -1) }
        .accessibilityAction(named: "Move Down") { shell.movePixie(pixie.id, by: 1) }
    }

    /// The listed pixie being dragged, for where the drop line shows.
    private var dragged: String? {
        guard case .chat(let id) = shell.dragging, listed.contains(id) else { return nil }
        return id
    }

    /// A pixie dragged down the list lands below this one, else above it.
    private var dropsBelow: Bool {
        guard let dragged, let from = listed.firstIndex(of: dragged),
            let to = listed.firstIndex(of: pixie.id)
        else { return false }
        return from < to
    }

    /// A listed pixie dropped here takes this one's place.
    private func drop() -> Bool {
        guard let dragged else { return false }
        shell.movePixie(dragged, onto: pixie.id)
        shell.dragging = nil
        return true
    }
}
