import AppKit
import ApplicationServices
import NestComputerCore

/// Keyboard and mouse events. Keys and scrolls go to one app's pid, so they work in the
/// background without touching the user's front app (B150 spike); a click is a real click
/// and needs the app in front.
enum Input {
    /// Return and Tab as typed text work only as key presses.
    private static let typedKeys: [Character: UInt16] = ["\n": 36, "\r": 36, "\t": 48]

    static func type(pid: pid_t, text: String) async {
        let source = CGEventSource(stateID: .privateState)
        for character in text {
            if let code = typedKeys[character] {
                post(pid: pid, code: code, flags: [], source: source)
            } else {
                var units = Array(String(character).utf16)
                for down in [true, false] {
                    guard
                        let event = CGEvent(
                            keyboardEventSource: source, virtualKey: 0, keyDown: down)
                    else { continue }
                    event.keyboardSetUnicodeString(
                        stringLength: units.count, unicodeString: &units)
                    event.postToPid(pid)
                }
            }
            try? await Task.sleep(for: .milliseconds(15))
        }
    }

    static func key(pid: pid_t, code: UInt16, modifiers: Set<Modifier>) {
        let flags = CGEventFlags(rawValue: Modifier.flags(modifiers))
        post(pid: pid, code: code, flags: flags, source: CGEventSource(stateID: .privateState))
    }

    /// A left click at a screen point, through the system like the user's own.
    static func click(at point: CGPoint) async {
        let source = CGEventSource(stateID: .hidSystemState)
        for type in [CGEventType.mouseMoved, .leftMouseDown, .leftMouseUp] {
            let event = CGEvent(
                mouseEventSource: source, mouseType: type, mouseCursorPosition: point,
                mouseButton: .left)
            if type != .mouseMoved { event?.setIntegerValueField(.mouseEventClickState, value: 1) }
            event?.post(tap: .cghidEventTap)
            try? await Task.sleep(for: .milliseconds(40))
        }
    }

    /// Wheel steps of five lines, aimed at the middle of `frame` (the app's front window).
    static func scrollWheel(pid: pid_t, direction: ScrollDirection, amount: Int, at frame: Rect?) {
        let lines = Int32(5)
        let (dy, dx): (Int32, Int32) =
            switch direction {
            case .up: (lines, 0)
            case .down: (-lines, 0)
            case .left: (0, lines)
            case .right: (0, -lines)
            }
        let source = CGEventSource(stateID: .privateState)
        for _ in 0..<amount {
            guard
                let event = CGEvent(
                    scrollWheelEvent2Source: source, units: .line, wheelCount: 2, wheel1: dy,
                    wheel2: dx, wheel3: 0)
            else { continue }
            if let frame {
                event.location = CGPoint(
                    x: frame.x + frame.width / 2, y: frame.y + frame.height / 2)
            }
            event.postToPid(pid)
        }
    }

    private static func post(pid: pid_t, code: UInt16, flags: CGEventFlags, source: CGEventSource?)
    {
        for down in [true, false] {
            guard let event = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: down)
            else { continue }
            event.flags = flags
            event.postToPid(pid)
        }
    }
}

extension Desktop {
    func type(pid: pid_t, text: String) async throws(HelperError) {
        await prepare(pid)
        if let focused = AX.element(AXUIElementCreateApplication(pid), kAXFocusedUIElementAttribute)
        {
            try refuseSecure(focused)
        }
        await Input.type(pid: pid, text: text)
    }

    func key(pid: pid_t, code: UInt16, modifiers: Set<Modifier>) async {
        await prepare(pid)
        Input.key(pid: pid, code: code, modifiers: modifiers)
    }

    /// A click at window points; only with the app in front, which the user allowed first.
    func click(window id: String, x: Double, y: Double) async throws(HelperError) {
        let window = try window(id)
        guard NSWorkspace.shared.frontmostApplication?.processIdentifier == window.pid else {
            throw HelperError(.notFront, "bring the app to the front first")
        }
        guard let frame = AX.frame(window.element) else {
            throw HelperError(.failed, "the window has no frame")
        }
        let point = try screenPoint(in: frame, x: x, y: y)
        await Input.click(at: CGPoint(x: point.x, y: point.y))
    }
}
