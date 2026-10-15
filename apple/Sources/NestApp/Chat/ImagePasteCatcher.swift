import AppKit
import NestKit
import SwiftUI

/// Cmd+V in a focused composer attaches copied image files or image data, as Claude
/// Code does (B59); any other paste reaches the field as usual (`ImagePaste.choice`).
/// It sits behind the field and only listens while its field has focus in its window.
struct ImagePasteCatcher: NSViewRepresentable {
    let isActive: Bool
    let attachFiles: ([URL]) -> Void
    let attachData: (Data, String) -> Void

    func makeNSView(context: Context) -> CatcherView {
        CatcherView()
    }

    func updateNSView(_ view: CatcherView, context: Context) {
        view.isActive = isActive
        view.attachFiles = attachFiles
        view.attachData = attachData
    }

    static func dismantleNSView(_ view: CatcherView, coordinator: ()) {
        view.stop()
    }

    final class CatcherView: NSView {
        var isActive = false
        var attachFiles: ([URL]) -> Void = { _ in }
        var attachData: (Data, String) -> Void = { _, _ in }
        private var monitor: Any?

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            stop()
            guard window != nil else { return }
            monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
                let handled = MainActor.assumeIsolated { self?.paste(event) ?? false }
                return handled ? nil : event
            }
        }

        func stop() {
            if let monitor {
                NSEvent.removeMonitor(monitor)
            }
            monitor = nil
        }

        override func hitTest(_ point: NSPoint) -> NSView? { nil }

        /// Whether the event was a paste this composer took.
        private func paste(_ event: NSEvent) -> Bool {
            guard isActive, event.window === window, event.window?.isKeyWindow == true,
                event.modifierFlags.intersection(.deviceIndependentFlagsMask) == .command,
                event.charactersIgnoringModifiers?.lowercased() == "v"
            else { return false }
            let board = NSPasteboard.general
            let urls =
                board.readObjects(
                    forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true])
                as? [URL] ?? []
            let types = board.types?.map(\.rawValue) ?? []
            switch ImagePaste.choice(types: types, fileURLs: urls) {
            case .files(let images):
                attachFiles(images)
                return true
            case .data(let type):
                guard let data = board.data(forType: NSPasteboard.PasteboardType(type)) else {
                    return false
                }
                attachData(data, type)
                return true
            case .text:
                return false
            }
        }
    }
}
