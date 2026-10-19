import NestKit
import SwiftUI
import UniformTypeIdentifiers

/// The split workspace of the project, or of the Pixies tab (B37): up to four panes
/// placed by the layout engine. Panes are keyed by chat (or pixie), so closing, opening or
/// swapping one keeps the others' views (and their transcripts) alive instead of
/// rebuilding the split tree. The panes fill the area edge to edge, split by 1 point
/// dividers (B93 "focus dim").
struct WorkspaceView: View {
    /// The coordinate space of pane placements, where pane drags are followed.
    static let space = "workspace"
    @Environment(Shell.self) private var shell

    var body: some View {
        let layout = shell.workspaceState.layout
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
                        .environment(\.paneDimmed, layout.isDimmed(placement.chat))
                        .environment(\.paneSize, frame.size)
                        .environment(\.paneFit, PaneFit(width: frame.width))
                        .zIndex(hidden ? 0 : 1)
                }
                if maximized == nil {
                    ForEach(layout.gutterFrames(in: size), id: \.split) { gutter in
                        let frame = gutter.grabArea
                        Gutter(gutter: gutter)
                            .frame(width: frame.width, height: frame.height)
                            .position(x: frame.midX, y: frame.midY)
                            .zIndex(2)
                    }
                }
                PaneDragGhost().zIndex(3)
            }
            .coordinateSpace(.named(Self.space))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onGeometryChange(for: CGRect.self) {
            $0.frame(in: .global)
        } action: {
            shell.workspaceSize = $0.size
            shell.workspaceFrame = $0
        }
    }
}

/// A chat, terminal or browser pane, by the kind its id tells; on the Pixies tab, a
/// pixie's pane.
private struct PaneContent: View {
    let pane: String
    @Environment(Shell.self) private var shell

    var body: some View {
        if shell.pixiesOpen {
            if let pixie = shell.pixie(pane) {
                PixiePane(pixie: pixie)
            }
        } else {
            projectPane
        }
    }

    @ViewBuilder private var projectPane: some View {
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

/// The 1 point divider between two panes, grabbed over a wider area that reaches over both
/// panes' edges; a short handle shows while the pointer is over it, and dragging it
/// resizes the panes within the engine's minimums.
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
            .overlay {
                Rectangle()
                    .fill(Palette.divider)
                    .frame(
                        width: row ? WorkspaceLayout.gutter : nil,
                        height: row ? nil : WorkspaceLayout.gutter)
            }
            .overlay {
                Capsule()
                    .fill(accent.focus)
                    .frame(width: row ? 3 : 36, height: row ? 36 : 3)
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
        shell.resize(split: gutter.split, ratio: newRatio)
    }
}

/// Shown before any chat (or, on the Pixies tab, any pixie) is open; accepts a dropped
/// chat or pixie. A project's is the start screen (B90): "What should we work on in
/// <project>?" over the composer, whose first message starts a chat in the project.
private struct EmptyWorkspace: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let targeted = shell.dropHighlight != nil && shell.dropHighlight?.pane == nil
        Group {
            if shell.pixiesOpen {
                NoPixiePanes()
            } else {
                StartSession()
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .contentShape(Rectangle())
        .overlay {
            if targeted {
                DropHighlightView(zone: .open, size: nil)
            }
        }
        .onDrop(of: [.nestChat], delegate: PaneDropDelegate(pane: nil, shell: shell))
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
        let layout = shell.workspaceState.layout
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

/// The highlight over the part of a pane a drop would take, with its label.
struct DropHighlightView: View {
    let zone: DropZone
    /// The pane's size; nil fills the whole space.
    let size: CGSize?
    @Environment(\.accentColors) private var accent

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
        // A small radius: the panes it lies over are square (B93).
        let shape = RoundedRectangle.rounded(Radius.chip)
        return ZStack {
            shape.fill(accent.selection)
            shape.strokeBorder(accent.focus, lineWidth: 1)
            HStack(spacing: 6) {
                Image(systemName: zone == .replace ? Icon.open : Icon.workspace)
                    .foregroundStyle(Palette.t2)
                Text(zone.label)
            }
            .font(.ui(TypeSize.ui, .medium))
            .foregroundStyle(Palette.t1)
            .padding(.horizontal, 12)
            .frame(height: 28)
            .sheetSurface(radius: Radius.card)
        }
        .frame(width: rect.width, height: rect.height)
        .offset(x: rect.minX, y: rect.minY)
    }
}
