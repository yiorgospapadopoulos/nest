import AppKit
import ApplicationServices

/// The menu bar beside the notch (answer 1): with Accessibility, the frames of the front
/// app's menus and of every app's status items, read off the main thread. A slow app costs
/// at most its timeout per question, and one that times out is skipped for a few passes.
final class MenuBarScanner: @unchecked Sendable {
    /// Accessibility frames: top-left origin on the primary screen.
    struct Items: Sendable {
        var menus: [CGRect]
        var extras: [CGRect]
    }

    private let queue = DispatchQueue(label: "local.nest.island.menubar", qos: .utility)
    // Only touched on `queue`.
    private var extras: [pid_t: [CGRect]] = [:]
    private var skip: [pid_t: Int] = [:]

    /// Reads the front app's menus and, on a full pass, every app's status items (else only
    /// apps not read yet), then hands the frames to `done` on the main thread.
    func scan(
        front: pid_t?, apps: [pid_t], full: Bool,
        done: @escaping @MainActor @Sendable (Items) -> Void
    ) {
        queue.async { [self] in
            let menus = front.flatMap { Self.items(of: $0, bar: kAXMenuBarAttribute) } ?? []
            let running = Set(apps)
            extras = extras.filter { running.contains($0.key) }
            skip = skip.filter { running.contains($0.key) }
            for pid in apps where full || extras[pid] == nil {
                if let left = skip[pid], left > 0 {
                    skip[pid] = left - 1
                    continue
                }
                if let found = Self.items(of: pid, bar: "AXExtrasMenuBar") {
                    extras[pid] = found
                    skip[pid] = nil
                } else {
                    extras[pid] = []
                    skip[pid] = 6
                }
            }
            let items = Items(menus: menus, extras: extras.values.flatMap { $0 })
            DispatchQueue.main.async { done(items) }
        }
    }

    /// The frames of a menu bar's items; nil when the app did not answer in time.
    private static func items(of pid: pid_t, bar attribute: String) -> [CGRect]? {
        let app = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(app, 0.05)
        var value: CFTypeRef?
        let error = AXUIElementCopyAttributeValue(app, attribute as CFString, &value)
        if error == .cannotComplete { return nil }
        guard error == .success, let value, CFGetTypeID(value) == AXUIElementGetTypeID() else {
            return []
        }
        let menuBar = value as! AXUIElement
        AXUIElementSetMessagingTimeout(menuBar, 0.05)
        var children: CFTypeRef?
        guard
            AXUIElementCopyAttributeValue(menuBar, kAXChildrenAttribute as CFString, &children)
                == .success,
            let elements = children as? [AXUIElement]
        else { return [] }
        return elements.compactMap(frame)
    }

    private static func frame(of element: AXUIElement) -> CGRect? {
        AXUIElementSetMessagingTimeout(element, 0.05)
        var values: CFArray?
        guard
            AXUIElementCopyMultipleAttributeValues(
                element, [kAXPositionAttribute, kAXSizeAttribute] as CFArray, [], &values)
                == .success,
            let list = values as? [AnyObject], list.count == 2,
            CFGetTypeID(list[0]) == AXValueGetTypeID(), CFGetTypeID(list[1]) == AXValueGetTypeID()
        else { return nil }
        var point = CGPoint.zero
        var size = CGSize.zero
        guard AXValueGetValue(list[0] as! AXValue, .cgPoint, &point),
            AXValueGetValue(list[1] as! AXValue, .cgSize, &size), size.width > 0
        else { return nil }
        return CGRect(origin: point, size: size)
    }
}

enum MenuBarSpace {
    /// The rightmost app menu's right edge left of the notch and the leftmost visible
    /// status item's left edge right of it, on the island's screen, in screen points. A
    /// menu bar on another screen shows the same items: they are moved over, menus from
    /// the left edge and status items from the right.
    static func edges(
        of items: MenuBarScanner.Items, screen: NSScreen, barHeight: Double,
        notchMinX: Double, notchMaxX: Double
    ) -> (appMenuMaxX: Double?, statusItemMinX: Double?) {
        var menuEdge: Double?
        for rect in items.menus {
            guard let source = barScreen(holding: rect, barHeight: barHeight) else { continue }
            let x = screen.frame.minX + (rect.maxX - source.frame.minX)
            if x <= notchMinX + 1 { menuEdge = max(menuEdge ?? x, x) }
        }
        var statusEdge: Double?
        for rect in items.extras {
            guard let source = barScreen(holding: rect, barHeight: barHeight) else { continue }
            let x = screen.frame.maxX - (source.frame.maxX - rect.minX)
            if x >= notchMaxX - 1 { statusEdge = min(statusEdge ?? x, x) }
        }
        return (menuEdge, statusEdge)
    }

    /// The screen whose menu bar holds an Accessibility frame: hidden items lie elsewhere.
    private static func barScreen(holding rect: CGRect, barHeight: Double) -> NSScreen? {
        let primaryTop = NSScreen.screens.first?.frame.maxY ?? 0
        return NSScreen.screens.first { screen in
            let barTop = primaryTop - screen.frame.maxY
            return rect.midX >= screen.frame.minX && rect.midX <= screen.frame.maxX
                && rect.minY >= barTop - 1 && rect.minY < barTop + barHeight
        }
    }
}
