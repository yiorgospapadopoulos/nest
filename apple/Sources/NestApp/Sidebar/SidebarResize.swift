import NestKit
import SwiftUI

extension View {
    /// Sized to the user's sidebar width (B45), with a handle on its right edge to drag
    /// it wider or narrower. The chats sidebar and the Pixies list share the width.
    func resizableSidebar() -> some View {
        modifier(ResizableSidebar())
    }
}

struct ResizableSidebar: ViewModifier {
    /// The handle's hit area, straddling the separator after the sidebar.
    static let handleWidth = 6.0

    @Environment(Shell.self) private var shell
    @Environment(\.windowSize) private var window
    /// The width when the drag began, and the width the drag shows; saved at its end.
    @State private var startWidth: Double?
    @State private var dragWidth: Double?

    func body(content: Content) -> some View {
        let width = SidebarWidth.clamp(
            dragWidth ?? shell.settings.sidebarWidth, available: available)
        content
            .frame(width: width)
            .overlay(alignment: .trailing) {
                handle(width: width)
                    .offset(x: Self.handleWidth / 2)
            }
            // Over the separator and workspace that follow it, so the handle's outer half
            // takes the pointer too.
            .zIndex(1)
    }

    private func handle(width: Double) -> some View {
        Color.clear
            .frame(width: Self.handleWidth)
            .frame(maxHeight: .infinity)
            .contentShape(Rectangle())
            .pointerStyle(.columnResize)
            .gesture(
                // Window coordinates: the handle moves with the width it sets.
                DragGesture(minimumDistance: 1, coordinateSpace: .global)
                    .onChanged { value in
                        let start = startWidth ?? width
                        startWidth = start
                        dragWidth = SidebarWidth.clamp(
                            start + value.translation.width, available: available)
                    }
                    .onEnded { _ in
                        if let dragWidth {
                            shell.settings.sidebarWidth = dragWidth
                        }
                        startWidth = nil
                        dragWidth = nil
                    }
            )
            .onTapGesture(count: 2) { shell.settings.sidebarWidth = SidebarWidth.standard }
            .help("Drag to resize the sidebar; double-click for its usual width")
            .accessibilityElement()
            .accessibilityLabel("Sidebar width")
            .accessibilityValue("\(Int(width.rounded())) points")
            .accessibilityAdjustableAction { direction in
                let step = direction == .increment ? 1 : -1
                shell.settings.sidebarWidth = SidebarWidth.clamp(
                    SidebarWidth.stepped(width, by: step), available: available)
            }
    }

    /// The width the sidebar and the workspace share: the window less the panel on the
    /// right (the activity panel, or a pixie's details), counted open so the sidebar
    /// keeps its width when that panel folds or opens.
    private var available: Double {
        window.width > 0 ? window.width - RightPanel.width - 2 : 0
    }
}
