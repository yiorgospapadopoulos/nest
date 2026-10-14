import AppKit
import NestKit
import SwiftUI
import WebKit

/// The live side of the terminal and browser panes: a shell or a web view per pane id.
/// They outlive the pane's SwiftUI view, so moving a pane, maximizing it or switching
/// project tabs keeps the shell and the page; closing the pane ends them.
@MainActor
final class ToolSessions {
    private var terminals: [String: TerminalSession] = [:]
    private var browsers: [String: BrowserSession] = [:]

    func terminal(for pane: ToolPane) -> TerminalSession {
        if let session = terminals[pane.id] {
            return session
        }
        let session = TerminalSession(folder: pane.folder ?? NSHomeDirectory())
        terminals[pane.id] = session
        return session
    }

    /// The pane's web view; `navigated` hears each page it moves to.
    func browser(for pane: ToolPane, navigated: @escaping (String) -> Void) -> BrowserSession {
        if let session = browsers[pane.id] {
            return session
        }
        let session = BrowserSession(url: pane.url, navigated: navigated)
        browsers[pane.id] = session
        return session
    }

    /// Ends every session whose pane is not in `panes`.
    func keep(_ panes: Set<String>) {
        for (id, session) in terminals where !panes.contains(id) {
            session.end()
            terminals[id] = nil
        }
        for (id, session) in browsers where !panes.contains(id) {
            session.end()
            browsers[id] = nil
        }
    }
}

/// A container for a pane's AppKit content that reports clicks, so a click into the
/// terminal or the page focuses its pane like a click anywhere else in a pane. It clips
/// its content to its bounds, since SwiftUI's clip shapes do not reach AppKit views and
/// views no longer clip by default, and it keeps the content exactly its own size.
final class PaneContentView: NSView {
    var onClick: (() -> Void)?

    init() {
        super.init(frame: .zero)
        wantsLayer = true
        clipsToBounds = true
        layer?.masksToBounds = true
        // The pane's panel is rounded and SwiftUI's clip does not reach AppKit content: its
        // bottom corners (the header covers the top) round with the panel, inside its ring.
        layer?.cornerRadius = PaneColors.radius - 1
        layer?.cornerCurve = .continuous
        layer?.maskedCorners = [.layerMinXMinYCorner, .layerMaxXMinYCorner]
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) is not supported")
    }

    override func layout() {
        super.layout()
        for subview in subviews where subview.frame != bounds {
            subview.frame = bounds
        }
    }

    override func hitTest(_ point: NSPoint) -> NSView? {
        let hit = super.hitTest(point)
        if hit != nil, NSApp.currentEvent?.type == .leftMouseDown {
            onClick?()
        }
        return hit
    }

    /// Shows `content` filling the container, replacing what it showed.
    func show(_ content: NSView) {
        guard content.superview != self else { return }
        subviews.forEach { $0.removeFromSuperview() }
        content.translatesAutoresizingMaskIntoConstraints = true
        content.frame = bounds
        content.autoresizingMask = [.width, .height]
        addSubview(content)
    }

    /// The size SwiftUI offers, never the content's own (a web view or terminal would
    /// otherwise push the pane past its slot).
    static func fill(_ proposal: ProposedViewSize) -> CGSize {
        proposal.replacingUnspecifiedDimensions(by: CGSize(width: 100, height: 100))
    }
}

extension NSColor {
    /// A token resolved for light or dark, for AppKit views that need fixed components.
    static func resolved(_ themed: ThemedColor, dark: Bool) -> NSColor {
        let rgba = dark ? themed.dark : themed.light
        return NSColor(srgbRed: rgba.red, green: rgba.green, blue: rgba.blue, alpha: rgba.alpha)
    }
}

extension NSColor {
    /// A translucent token composited over an opaque one.
    static func resolved(_ top: ThemedColor, over base: ThemedColor, dark: Bool) -> NSColor {
        let a = dark ? top.dark : top.light
        let b = dark ? base.dark : base.light
        func mix(_ x: Double, _ y: Double) -> Double { x * a.alpha + y * (1 - a.alpha) }
        return NSColor(
            srgbRed: mix(a.red, b.red), green: mix(a.green, b.green), blue: mix(a.blue, b.blue),
            alpha: 1)
    }
}

extension NSAppearance {
    var isDark: Bool { bestMatch(from: [.aqua, .darkAqua]) == .darkAqua }
}
