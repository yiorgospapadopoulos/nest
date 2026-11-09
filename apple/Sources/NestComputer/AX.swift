import ApplicationServices
import Foundation
import NestComputerCore

/// Small typed reads and writes on the Accessibility API.
enum AX {
    static func attribute(_ element: AXUIElement, _ name: String) -> AnyObject? {
        var value: AnyObject?
        let result = AXUIElementCopyAttributeValue(element, name as CFString, &value)
        return result == .success ? value : nil
    }

    static func string(_ element: AXUIElement, _ name: String) -> String? {
        attribute(element, name) as? String
    }

    static func bool(_ element: AXUIElement, _ name: String) -> Bool? {
        (attribute(element, name) as? NSNumber)?.boolValue
    }

    static func elements(_ element: AXUIElement, _ name: String) -> [AXUIElement] {
        guard let value = attribute(element, name), CFGetTypeID(value) == CFArrayGetTypeID()
        else { return [] }
        return (value as? [AnyObject] ?? []).compactMap(asElement)
    }

    static func element(_ element: AXUIElement, _ name: String) -> AXUIElement? {
        attribute(element, name).flatMap(asElement)
    }

    static func children(_ element: AXUIElement) -> [AXUIElement] {
        elements(element, kAXChildrenAttribute)
    }

    static func role(_ element: AXUIElement) -> String? {
        string(element, kAXRoleAttribute)
    }

    static func pid(_ element: AXUIElement) -> pid_t? {
        var pid: pid_t = 0
        return AXUIElementGetPid(element, &pid) == .success ? pid : nil
    }

    /// The element's frame in screen points, top-left origin.
    static func frame(_ element: AXUIElement) -> Rect? {
        frame(
            position: attribute(element, kAXPositionAttribute),
            size: attribute(element, kAXSizeAttribute))
    }

    static func frame(position: AnyObject?, size: AnyObject?) -> Rect? {
        guard let position = position.flatMap(asValue), let size = size.flatMap(asValue)
        else { return nil }
        var point = CGPoint.zero
        var extent = CGSize.zero
        guard AXValueGetValue(position, .cgPoint, &point), AXValueGetValue(size, .cgSize, &extent)
        else { return nil }
        return Rect(x: point.x, y: point.y, width: extent.width, height: extent.height)
    }

    static func actions(_ element: AXUIElement) -> [String] {
        var names: CFArray?
        guard AXUIElementCopyActionNames(element, &names) == .success else { return [] }
        return names as? [String] ?? []
    }

    /// Whether the element still exists in its app.
    static func isAlive(_ element: AXUIElement) -> Bool {
        var value: AnyObject?
        return AXUIElementCopyAttributeValue(element, kAXRoleAttribute as CFString, &value)
            != .invalidUIElement
    }

    static func set(_ element: AXUIElement, _ name: String, _ value: AnyObject) -> AXError {
        AXUIElementSetAttributeValue(element, name as CFString, value)
    }

    static func perform(_ element: AXUIElement, _ action: String) -> AXError {
        AXUIElementPerformAction(element, action as CFString)
    }

    /// Stops a hung app from holding a request for the system's default six seconds.
    static func limitWaits(seconds: Float) {
        AXUIElementSetMessagingTimeout(AXUIElementCreateSystemWide(), seconds)
    }

    /// A text form of a value: strings as they are, numbers and booleans as digits.
    static func text(_ value: AnyObject?) -> String? {
        if let string = value as? String { return string }
        if let attributed = value as? NSAttributedString { return attributed.string }
        if let number = value as? NSNumber { return number.stringValue }
        return nil
    }

    /// Turns an AX failure into the protocol's error.
    static func check(_ result: AXError, doing what: String) throws(HelperError) {
        switch result {
        case .success: return
        case .apiDisabled:
            throw HelperError(.noPermission, "Nest Computer has no Accessibility permission")
        case .invalidUIElement: throw HelperError(.stale, "the element is gone")
        case .cannotComplete: throw HelperError(.failed, "the app did not answer to \(what)")
        case .actionUnsupported, .attributeUnsupported, .notImplemented:
            throw HelperError(.failed, "the element does not support \(what)")
        default:
            throw HelperError(.failed, "\(what) failed (AXError \(result.rawValue))")
        }
    }

    private static func asElement(_ value: AnyObject) -> AXUIElement? {
        guard CFGetTypeID(value) == AXUIElementGetTypeID() else { return nil }
        return (value as! AXUIElement)
    }

    private static func asValue(_ value: AnyObject) -> AXValue? {
        guard CFGetTypeID(value) == AXValueGetTypeID() else { return nil }
        return (value as! AXValue)
    }
}
