import AppKit
import NestKit
import SwiftUI

/// While a chat is using an app (B150), from its Allow until it lets go, a soft glow around
/// the edge of the screen its window is on, so it is plain to see even in the background;
/// the main screen until the chat has looked at the window. Clicks pass through it.
@MainActor
final class ComputerGlow {
    private let store: ComputerStore
    /// The glow on each screen, by its display number.
    private var windows: [CGDirectDisplayID: NSWindow] = [:]
    private var stopped = false

    init(store: ComputerStore) {
        self.store = store
    }

    func start() {
        refresh()
    }

    func stop() {
        stopped = true
        show(on: [])
    }

    private func refresh() {
        guard !stopped else { return }
        let targets = withObservationTracking {
            store.inUse
        } onChange: { [weak self] in
            Task { @MainActor in self?.refresh() }
        }
        show(on: Set(targets.compactMap(Self.screen(of:)).map(\.number)))
    }

    private func show(on numbers: Set<CGDirectDisplayID>) {
        for (number, window) in windows where !numbers.contains(number) {
            window.orderOut(nil)
            windows[number] = nil
        }
        for screen in NSScreen.screens where numbers.contains(screen.number) {
            if windows[screen.number] == nil {
                let window = Self.window(on: screen)
                window.orderFrontRegardless()
                windows[screen.number] = window
            }
        }
    }

    /// The screen a target's window is on, by its middle; the main screen while unknown.
    private static func screen(of target: ComputerTarget) -> NSScreen? {
        let main = NSScreen.screens.first
        guard let frame = target.frame, let main else { return main }
        // Accessibility measures from the main screen's top, AppKit from its bottom.
        let middle = NSPoint(
            x: frame.x + frame.width / 2, y: main.frame.maxY - (frame.y + frame.height / 2))
        return NSScreen.screens.first { $0.frame.contains(middle) } ?? main
    }

    private static func window(on screen: NSScreen) -> NSWindow {
        // Created by its global frame: made with `screen:` it stays off screen (B150 live
        // check).
        let window = NSWindow(
            contentRect: screen.frame, styleMask: .borderless, backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = false
        window.ignoresMouseEvents = true
        window.level = .screenSaver
        window.collectionBehavior = [
            .canJoinAllSpaces, .stationary, .fullScreenAuxiliary, .ignoresCycle,
        ]
        window.contentView = NSHostingView(rootView: GlowEdge())
        window.setFrame(screen.frame, display: false)
        return window
    }
}

extension NSScreen {
    /// The display's number, which stays the same while it is connected.
    fileprivate var number: CGDirectDisplayID {
        (deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber)?.uint32Value
            ?? 0
    }
}

/// The glowing edge: the link blue, breathing slowly unless motion is reduced.
private struct GlowEdge: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var bright = false

    var body: some View {
        let edge = RoundedRectangle(cornerRadius: 10)
        edge.strokeBorder(Palette.link, lineWidth: 4)
            .blur(radius: 8)
            .overlay(edge.strokeBorder(Palette.link.opacity(0.7), lineWidth: 1.5))
            .opacity(bright ? 1 : 0.5)
            .ignoresSafeArea()
            .accessibilityHidden(true)
            .onAppear {
                guard !reduceMotion else {
                    bright = true
                    return
                }
                withAnimation(.easeInOut(duration: 1.4).repeatForever()) { bright = true }
            }
    }
}
