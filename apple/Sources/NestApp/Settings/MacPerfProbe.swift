import AppKit
import Darwin
import NestKit
import SwiftUI

/// Settings > Performance's Mac app section (B115, C14): opens the biggest chat's
/// transcript offscreen with the app's own transcript view, times how long it takes to lay
/// out whole and to scroll it through, and reads the app's memory before and after.
@MainActor
enum MacPerfProbe {
    /// The offscreen pane, about a chat pane's size.
    static let size = CGSize(width: 720, height: 900)
    /// Laid out once the transcript is loaded and its height has held this long.
    static let settled = Duration.milliseconds(600)
    /// The most a layout or a scroll may take before it counts as done.
    static let limit = Duration.seconds(90)
    /// The most earlier pages loaded for the scroll (100 events each).
    static let maxPages = 200

    enum Failure: LocalizedError {
        case noChat

        var errorDescription: String? { "There is no chat to open" }
    }

    /// The metrics by the ids `POST /api/perf/client` takes: `layout_ms` (the chat opening
    /// as it does), `scroll_ms` (the whole chat, scrolled from the end to the top), `memory_before` and `memory_after`; one that could not be measured is
    /// left out.
    static func measure(_ shell: Shell) async throws -> [String: Double] {
        let sessions = Array(shell.sessions.sessions.values).filter { !$0.isArchived }
        guard
            let chat = PerformanceStore.biggestChat(
                in: shell.model.performance.view, sessions: sessions)
        else { throw Failure.noChat }
        var metrics: [String: Double] = [:]
        metrics["memory_before"] = footprint()

        let window = NSWindow(
            contentRect: CGRect(origin: CGPoint(x: -30_000, y: -30_000), size: size),
            styleMask: [.borderless], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.alphaValue = 0
        window.ignoresMouseEvents = true
        let host = NSHostingView(
            rootView: TranscriptView(chat: chat)
                .environment(shell)
                .environment(\.accentColors, AccentColors(accent: shell.settings.accent))
                .frame(width: size.width, height: size.height)
                .background(Palette.windowOpaque))
        host.frame = CGRect(origin: .zero, size: size)
        defer {
            window.contentView = nil
            window.close()
        }

        let clock = ContinuousClock()
        let start = clock.now
        window.contentView = host
        let transcript = shell.model.transcripts.transcript(for: chat)
        let laidOut = await layOut(host, window: window, loaded: { transcript.isLoaded })
        if let laidOut {
            metrics["layout_ms"] = milliseconds(laidOut - start)
        }
        // A chat last opened at a message holds only the pages around it; the scroll goes
        // through all of it.
        var pages = 0
        while transcript.hasOlder, pages < maxPages, (try? await transcript.loadOlder()) != nil {
            pages += 1
        }
        _ = await layOut(host, window: window, loaded: { true })
        if let scroll = await scrollThrough(host, window: window) {
            metrics["scroll_ms"] = milliseconds(scroll)
        }
        metrics["memory_after"] = footprint()
        return metrics
    }

    /// Lays the view out every frame until the transcript is loaded and its height stops
    /// changing: the transcript lays out its latest messages first, then the rest a chunk
    /// per frame, as when the chat opens. Answers when the height last changed.
    private static func layOut(
        _ host: NSView, window: NSWindow, loaded: () -> Bool
    ) async -> ContinuousClock.Instant? {
        let clock = ContinuousClock()
        let deadline = clock.now + limit
        var height = -1.0
        var changed = clock.now
        while clock.now < deadline {
            host.layoutSubtreeIfNeeded()
            window.displayIfNeeded()
            let now = clock.now
            let current = scrollView(in: host)?.documentView?.frame.height ?? 0
            if current != height {
                height = current
                changed = now
            } else if loaded(), now - changed >= settled {
                return changed
            }
            try? await Task.sleep(for: .milliseconds(16))
        }
        return nil
    }

    /// Scrolls from the end to the top a little under a screen at a time, laying out and
    /// drawing each step as a scroll would, a frame apart; answers the time the steps took,
    /// without the waits between them.
    private static func scrollThrough(_ host: NSView, window: NSWindow) async -> Duration? {
        guard let scroll = scrollView(in: host), let document = scroll.documentView else {
            return nil
        }
        let clip = scroll.contentView
        let viewport = clip.bounds.height
        let travel = document.frame.height - viewport
        guard viewport > 0, travel > 0 else { return nil }
        let step = viewport * 0.8
        let steps = min(Int((travel / step).rounded(.up)), 5_000)
        let clock = ContinuousClock()
        var worked = Duration.zero
        for index in 0...steps {
            let stepStart = clock.now
            let fromEnd = min(Double(index) * step, travel)
            // A flipped document has its top at zero, an unflipped one at its far end.
            let y = document.isFlipped ? travel - fromEnd : fromEnd
            clip.scroll(to: NSPoint(x: clip.bounds.minX, y: y))
            scroll.reflectScrolledClipView(clip)
            host.layoutSubtreeIfNeeded()
            window.displayIfNeeded()
            worked += clock.now - stepStart
            // A frame apart, so the lazy stack lays out what scrolled in, as it would.
            try? await Task.sleep(for: .milliseconds(16))
            if worked > limit {
                break
            }
        }
        return worked
    }

    /// The transcript's scroll view: the largest one inside the host.
    private static func scrollView(in view: NSView) -> NSScrollView? {
        var found: [NSScrollView] = []
        func visit(_ view: NSView) {
            if let scroll = view as? NSScrollView {
                found.append(scroll)
            }
            view.subviews.forEach(visit)
        }
        visit(view)
        return found.max { $0.frame.height < $1.frame.height }
    }

    /// The app's memory as Activity Monitor counts it (`phys_footprint`), in bytes.
    static func footprint() -> Double? {
        var info = task_vm_info_data_t()
        var count = mach_msg_type_number_t(
            MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<integer_t>.size)
        let result = withUnsafeMutablePointer(to: &info) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &count)
            }
        }
        return result == KERN_SUCCESS ? Double(info.phys_footprint) : nil
    }

    private static func milliseconds(_ duration: Duration) -> Double {
        let parts = duration.components
        return Double(parts.seconds) * 1000 + Double(parts.attoseconds) / 1e15
    }
}
