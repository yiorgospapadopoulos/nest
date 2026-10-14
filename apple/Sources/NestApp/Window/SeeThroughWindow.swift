import AppKit
import SwiftUI

/// Makes the window see-through: non-opaque with a clear background and its content
/// under a transparent title bar, with the system's behind-window blur beneath
/// everything; `WindowBackground` lays the look's tint over it. The blur turns opaque by
/// itself with Reduce Transparency.
struct SeeThroughWindow: NSViewRepresentable {
    @Environment(\.offscreen) private var offscreen

    func makeNSView(context: Context) -> NSView {
        // Offscreen snapshots have no desktop to blur and keep their window as it is.
        guard !offscreen else { return NSView() }
        let view = SeeThroughEffectView()
        view.blendingMode = .behindWindow
        view.state = .active
        // macOS fixes the blur radius. A light material that follows the appearance: the
        // look's tint over it sets the color.
        view.material = .sidebar
        return view
    }

    func updateNSView(_ view: NSView, context: Context) {}
}

private final class SeeThroughEffectView: NSVisualEffectView {
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        guard let window else { return }
        window.isOpaque = false
        window.backgroundColor = .clear
        window.titlebarAppearsTransparent = true
        window.styleMask.insert(.fullSizeContentView)
    }
}
