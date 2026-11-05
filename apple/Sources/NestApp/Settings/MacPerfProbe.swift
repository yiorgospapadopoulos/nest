import AppKit
import Darwin
import NestKit
import SwiftUI

/// Settings > Performance's Mac app section (B115, C14): opens the biggest chat's page as
/// a pane would, offscreen, times how long until its messages show, and reads the app's
/// memory before and after. The page's own process is not in that memory.
@MainActor
enum MacPerfProbe {
    /// The offscreen pane, about a chat pane's size.
    static let size = CGSize(width: 720, height: 900)
    /// The most the page may take before it counts as not measured.
    static let limit = Duration.seconds(90)

    enum Failure: LocalizedError {
        case noChat

        var errorDescription: String? { "There is no chat to open" }
    }

    /// The metrics by the ids `POST /api/perf/client` takes: `layout_ms` (the chat opening
    /// until its messages show), `memory_before` and `memory_after`; one that could not be
    /// measured is left out.
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
        let container = PaneContentView()
        container.frame = CGRect(origin: .zero, size: size)
        window.contentView = container
        let target = WebPaneBridge.Target.probe(chat)
        let panes = shell.webPanes
        defer {
            panes.release(target, from: container)
            panes.retry(target)
            window.contentView = nil
            window.close()
        }

        let clock = ContinuousClock()
        let start = clock.now
        let page = panes.hold(target, in: container, transient: true)
        while clock.now - start < limit, panes.shows(target) {
            if await page.showsMessages() {
                metrics["layout_ms"] = milliseconds(clock.now - start)
                break
            }
            try? await Task.sleep(for: .milliseconds(16))
        }
        metrics["memory_after"] = footprint()
        return metrics
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
