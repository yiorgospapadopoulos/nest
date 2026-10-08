import HarnessKit
import SwiftUI
import UniformTypeIdentifiers

/// The project's split workspace: up to four panes placed by the layout engine. Panes
/// are keyed by chat, so closing, opening or swapping one keeps the others' views (and
/// their transcripts) alive instead of rebuilding the split tree.
struct WorkspaceView: View {
    /// The coordinate space of pane placements, where pane drags are followed.
    static let space = "workspace"
    @Environment(Shell.self) private var shell

    var body: some View {
        let layout = shell.projectState.layout
        GeometryReader { geometry in
            let size = geometry.size
            let maximized = layout.maximized
            ZStack(alignment: .topLeading) {
                if layout.root == nil {
                    EmptyWorkspace().frame(width: size.width, height: size.height)
                }
                ForEach(layout.placements(in: size), id: \.chat) { placement in
                    let hidden = maximized != nil && maximized != placement.chat
                    let frame =
                        maximized == placement.chat
                        ? CGRect(origin: .zero, size: size) : placement.frame
                    PaneContent(pane: placement.chat)
                        .frame(width: frame.width, height: frame.height)
                        .position(x: frame.midX, y: frame.midY)
                        .opacity(hidden ? 0 : 1)
                        .allowsHitTesting(!hidden)
                        .accessibilityHidden(hidden)
                        .environment(\.paneHidden, hidden)
                        .environment(\.paneSize, frame.size)
                        .environment(\.paneFit, PaneFit(width: frame.width))
                        .zIndex(hidden ? 0 : 1)
                }
                if maximized == nil {
                    ForEach(layout.gutterFrames(in: size), id: \.split) { gutter in
                        Gutter(gutter: gutter)
                            .frame(width: gutter.frame.width, height: gutter.frame.height)
                            .position(x: gutter.frame.midX, y: gutter.frame.midY)
                            .zIndex(2)
                    }
                }
                PaneDragGhost().zIndex(3)
            }
            .coordinateSpace(.named(Self.space))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onGeometryChange(for: CGSize.self) {
            $0.size
        } action: {
            shell.workspaceSize = $0
        }
    }
}

/// A chat, terminal or browser pane, by the kind its id tells.
private struct PaneContent: View {
    let pane: String
    @Environment(Shell.self) private var shell

    var body: some View {
        switch PaneKind(paneID: pane) {
        case .chat:
            PaneView(chat: pane)
        case .terminal, .browser:
            if let tool = shell.toolPane(pane) {
                if tool.kind == .terminal {
                    TerminalPaneView(pane: tool)
                } else {
                    BrowserPaneView(pane: tool)
                }
            }
        }
    }
}

/// The dragged pane's title, following the pointer.
private struct PaneDragGhost: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        if let drag = shell.paneDrag {
            DragGhost(title: drag.title, tone: drag.tone)
                .fixedSize()
                .position(drag.location)
                .allowsHitTesting(false)
        }
    }
}

/// The space between two panes; dragging it resizes them within the engine's minimums.
private struct Gutter: View {
    let gutter: GutterFrame
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @State private var hovering = false
    @State private var startRatio: Double?

    var body: some View {
        let row = gutter.direction == .row
        let ratio = gutter.ratio
        let active = hovering || startRatio != nil
        Rectangle()
            .fill(.clear)
            .frame(
                width: row ? WorkspaceLayout.gutter : nil,
                height: row ? nil : WorkspaceLayout.gutter
            )
            .overlay {
                Capsule()
                    .fill(active ? accent.accent : Palette.t3)
                    .frame(width: row ? 4 : 44, height: row ? 44 : 4)
                    .opacity(active ? 1 : 0)
            }
            .contentShape(Rectangle())
            .pointerStyle(row ? .columnResize : .rowResize)
            .onHover { hovering = $0 }
            .gesture(
                DragGesture(minimumDistance: 1, coordinateSpace: .global)
                    .onChanged { value in
                        let start = startRatio ?? ratio
                        startRatio = start
                        let moved = row ? value.translation.width : value.translation.height
                        resize(to: start + moved / max(gutter.span, 1))
                    }
                    .onEnded { _ in startRatio = nil }
            )
            .onTapGesture(count: 2) { resize(to: 0.5) }
            .accessibilityElement()
            .accessibilityLabel("Resize panes")
            .accessibilityValue("\(Int((gutter.ratio * 100).rounded())) percent")
            .accessibilityAdjustableAction { direction in
                resize(to: gutter.ratio + (direction == .increment ? 0.05 : -0.05))
            }
    }

    private func resize(to newRatio: Double) {
        let size = shell.workspaceSize
        shell.app.update { $0.layout.resize(split: gutter.split, ratio: newRatio, in: size) }
    }
}

/// Shown before any chat is open; accepts a dropped chat.
private struct EmptyWorkspace: View {
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @Environment(\.glass) private var glass

    var body: some View {
        let targeted = shell.dropHighlight != nil && shell.dropHighlight?.pane == nil
        let shape = glass.rounded(glass.radius.panel + 2)
        VStack(spacing: 8) {
            Image(systemName: Icon.workspace)
                .font(.system(size: 24))
                .foregroundStyle(accent.accent)
                .frame(width: 56, height: 56)
                .panelGlass(radius: glass.radius.panel - 2)
            Text("Drag chats here to work on them side by side")
                .font(.ui(16, .semibold))
                .foregroundStyle(Palette.t1)
            Button {
                shell.newChat()
            } label: {
                Label("New chat", systemImage: Icon.plus)
            }
            .buttonStyle(.harness(.primary))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(shape.fill(glass.subtle))
        .overlay(
            shape.strokeBorder(
                targeted ? accent.line : Palette.hair2,
                style: StrokeStyle(lineWidth: 2, dash: [6, 5]))
        )
        .overlay {
            if targeted {
                DropHighlightView(zone: .open, size: nil)
            }
        }
        .onDrop(of: [.harnessChat], delegate: PaneDropDelegate(pane: nil, shell: shell))
    }
}

/// Decides and shows where a chat dragged from the sidebar lands on a pane. A drop on
/// the chat's own pane is accepted and does nothing, so the system drag ends at once
/// instead of sliding back.
struct PaneDropDelegate: DropDelegate {
    let pane: String?
    let shell: Shell

    func validateDrop(info: DropInfo) -> Bool {
        shell.dragging != nil
    }

    func dropEntered(info: DropInfo) {
        update(info)
    }

    func dropUpdated(info: DropInfo) -> DropProposal? {
        update(info)
        return DropProposal(operation: .move)
    }

    func dropExited(info: DropInfo) {
        if shell.dropHighlight?.pane == pane {
            shell.dropHighlight = nil
        }
    }

    func performDrop(info: DropInfo) -> Bool {
        guard let item = shell.dragging else { return false }
        let zone = zone(for: item, at: info.location)
        shell.perform(item, onto: pane, zone: zone)
        return true
    }

    private func update(_ info: DropInfo) {
        guard let item = shell.dragging else { return }
        let highlight = DropHighlight(pane: pane, zone: zone(for: item, at: info.location))
        if shell.dropHighlight != highlight {
            withAnimation(.easeOut(duration: 0.14)) { shell.dropHighlight = highlight }
        }
    }

    private func zone(for item: DragItem, at point: CGPoint) -> DropZone {
        let layout = shell.projectState.layout
        let target = pane.map {
            DropZone.Target(
                isDraggedChat: $0 == item.chat, draggedIsOpen: layout.contains(item.chat),
                openCount: layout.leaves.count)
        }
        return DropZone.zone(at: point, in: paneSize, kind: item.kind, target: target)
    }

    /// Drops are hit-tested per pane, so the pane's own size comes with the location.
    private var paneSize: CGSize {
        shell.paneSizes[pane ?? ""] ?? shell.workspaceSize
    }
}

/// The glass highlight over the part of a pane a drop would take, with its label.
struct DropHighlightView: View {
    let zone: DropZone
    /// The pane's size; nil fills the whole space.
    let size: CGSize?
    @Environment(\.accentColors) private var accent
    @Environment(\.glass) private var glass

    var body: some View {
        GeometryReader { geometry in
            if let rect = zone.shownHighlight(in: size ?? geometry.size) {
                highlight(rect)
            }
        }
        .allowsHitTesting(false)
        .transition(.opacity)
    }

    private func highlight(_ rect: CGRect) -> some View {
        let shape = glass.rounded(glass.radius.card)
        return ZStack {
            shape.fill(accent.soft)
            shape.strokeBorder(accent.accent, lineWidth: 2)
            HStack(spacing: 6) {
                Image(systemName: zone == .replace ? Icon.open : Icon.workspace)
                    .foregroundStyle(accent.accent)
                Text(zone.label)
            }
            .font(.ui(TypeSize.callout, .semibold))
            .foregroundStyle(Palette.t1)
            .padding(.horizontal, 14)
            .frame(height: 30)
            .controlGlass()
        }
        .frame(width: rect.width, height: rect.height)
        .offset(x: rect.minX, y: rect.minY)
    }
}
