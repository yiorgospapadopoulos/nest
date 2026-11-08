import AppKit
import ApplicationServices
import NestComputerCore

/// Actions through the Accessibility API; they work with the app in the background.
extension Desktop {
    func press(element id: String, action: String) async throws(HelperError) {
        let (element, window) = try element(id)
        await prepare(window.pid)
        try AX.check(AX.perform(element, action), doing: action)
    }

    func setValue(element id: String, text: String) async throws(HelperError) {
        let (element, window) = try element(id)
        try refuseSecure(element)
        await prepare(window.pid)
        try AX.check(AX.set(element, kAXValueAttribute, text as CFString), doing: "setting text")
    }

    func focus(element id: String) async throws(HelperError) {
        let (element, window) = try element(id)
        await prepare(window.pid)
        try AX.check(AX.set(element, kAXFocusedAttribute, kCFBooleanTrue), doing: "focus")
    }

    /// Chooses a menu bar item by its titles, such as ["File", "New Window"], and returns
    /// the windows the app announces within 1.5 seconds.
    func menu(pid: pid_t, path: [String]) async throws(HelperError) -> [JSONValue] {
        await prepare(pid)
        let app = AXUIElementCreateApplication(pid)
        guard let bar = AX.element(app, kAXMenuBarAttribute) else {
            throw HelperError(.notFound, "the app has no menu bar")
        }
        var item = bar
        for title in path {
            // A menu bar's children are its items; a menu item's only child is its menu.
            let menu = AX.role(item) == kAXMenuBarRole ? item : AX.children(item).first ?? item
            guard let next = AX.children(menu).first(where: { matches($0, title) }) else {
                throw HelperError(.notFound, "no menu item \"\(title)\"")
            }
            item = next
        }
        guard AX.bool(item, kAXEnabledAttribute) ?? true else {
            throw HelperError(.failed, "the menu item \"\(path.joined(separator: " > "))\" is off")
        }
        let before = created.count
        try AX.check(AX.perform(item, kAXPressAction), doing: "the menu item")
        let deadline = ContinuousClock.now + .milliseconds(1500)
        while ContinuousClock.now < deadline {
            try? await Task.sleep(for: .milliseconds(50))
            if created.count > before {
                // Give a window opened with others a moment to announce them too.
                try? await Task.sleep(for: .milliseconds(150))
                break
            }
        }
        return created.dropFirst(before).compactMap { id in
            (try? window(id)).map(json)
        }
    }

    func scroll(target: ScrollTarget, direction: ScrollDirection, amount: Int)
        async throws(HelperError)
    {
        switch target {
        case .element(let id):
            let (element, window) = try element(id)
            await prepare(window.pid)
            try scroll(element: element, direction: direction, amount: amount)
        case .pid(let pid):
            await prepare(pid)
            Input.scrollWheel(pid: pid, direction: direction, amount: amount, at: frontFrame(pid))
        }
    }

    /// Brings the app, and the window when given, to the front.
    func front(pid: pid_t, window id: String?) throws(HelperError) {
        guard let app = NSRunningApplication(processIdentifier: pid) else {
            throw HelperError(.notFound, "no app with pid \(pid)")
        }
        if let id {
            let window = try window(id)
            _ = AX.perform(window.element, kAXRaiseAction)
            _ = AX.set(window.element, kAXMainAttribute, kCFBooleanTrue)
        }
        // Setting AXFrontmost works from a background app, where macOS may refuse activate().
        let frontmost = AX.set(
            AXUIElementCreateApplication(pid), kAXFrontmostAttribute, kCFBooleanTrue)
        guard frontmost == .success || app.activate(options: [.activateAllWindows]) else {
            throw HelperError(.failed, "macOS did not bring the app to the front")
        }
    }

    func launch(bundleID: String) async throws(HelperError) -> pid_t {
        guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleID) else {
            throw HelperError(.notFound, "no app with bundle id \(bundleID)")
        }
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = false
        configuration.addsToRecentItems = false
        do {
            let app = try await NSWorkspace.shared.openApplication(
                at: url, configuration: configuration)
            observe(app.processIdentifier)
            return app.processIdentifier
        } catch {
            throw HelperError(.failed, "could not open \(bundleID): \(error.localizedDescription)")
        }
    }

    func refuseSecure(_ element: AXUIElement) throws(HelperError) {
        let role = AX.role(element) ?? ""
        if Roles.isSecure(role: role, subrole: AX.string(element, kAXSubroleAttribute)) {
            throw HelperError(.secureField, "this is a password field; ask the user to type it")
        }
    }

    private func matches(_ item: AXUIElement, _ title: String) -> Bool {
        guard let name = AX.string(item, kAXTitleAttribute) else { return false }
        return Self.menuTitle(name) == Self.menuTitle(title)
    }

    /// Menu titles compare without case and without a trailing ellipsis ("Save As…").
    private static func menuTitle(_ title: String) -> String {
        var text = title.trimmingCharacters(in: .whitespaces).lowercased()
        for suffix in ["…", "..."] where text.hasSuffix(suffix) {
            text = String(text.dropLast(suffix.count))
        }
        return text
    }

    /// Scrolls the element's scroll area: by page actions where the area has them, or by
    /// moving its scroll bar a tenth for each step.
    private func scroll(element: AXUIElement, direction: ScrollDirection, amount: Int)
        throws(HelperError)
    {
        guard let area = scrollArea(around: element) else {
            throw HelperError(.notFound, "nothing scrolls there")
        }
        let page: String
        switch direction {
        case .up: page = "AXScrollUpByPage"
        case .down: page = "AXScrollDownByPage"
        case .left: page = "AXScrollLeftByPage"
        case .right: page = "AXScrollRightByPage"
        }
        if AX.actions(area).contains(page) {
            for _ in 0..<amount { try AX.check(AX.perform(area, page), doing: "scrolling") }
            return
        }
        let vertical = direction == .up || direction == .down
        let barName = vertical ? kAXVerticalScrollBarAttribute : kAXHorizontalScrollBarAttribute
        guard let bar = AX.element(area, barName),
            let position = (AX.attribute(bar, kAXValueAttribute) as? NSNumber)?.doubleValue
        else { throw HelperError(.failed, "that area cannot scroll \(direction.rawValue)") }
        let step = (direction == .down || direction == .right ? 0.1 : -0.1) * Double(amount)
        let next = min(1, max(0, position + step))
        try AX.check(AX.set(bar, kAXValueAttribute, next as NSNumber), doing: "scrolling")
    }

    /// The element itself or its nearest scroll area: up its parents first, then down.
    private func scrollArea(around element: AXUIElement) -> AXUIElement? {
        var current: AXUIElement? = element
        while let node = current {
            if AX.role(node) == kAXScrollAreaRole { return node }
            current = AX.element(node, kAXParentAttribute)
        }
        var queue = AX.children(element)
        var seen = 0
        while !queue.isEmpty, seen < 500 {
            let node = queue.removeFirst()
            seen += 1
            if AX.role(node) == kAXScrollAreaRole { return node }
            queue.append(contentsOf: AX.children(node))
        }
        return nil
    }

    private func frontFrame(_ pid: pid_t) -> Rect? {
        let app = AXUIElementCreateApplication(pid)
        let window =
            AX.element(app, kAXFocusedWindowAttribute) ?? AX.element(app, kAXMainWindowAttribute)
        return window.flatMap(AX.frame)
    }
}
