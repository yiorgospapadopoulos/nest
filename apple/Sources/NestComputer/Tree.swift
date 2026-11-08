import ApplicationServices
import Foundation
import NestComputerCore

/// The Accessibility API as a tree for `OutlineBuilder`.
struct AXTree: TreeSource {
    private static let names = [
        kAXRoleAttribute, kAXSubroleAttribute, kAXTitleAttribute, kAXDescriptionAttribute,
        kAXPlaceholderValueAttribute, kAXValueAttribute, kAXEnabledAttribute,
        kAXFocusedAttribute, kAXPositionAttribute, kAXSizeAttribute,
    ]

    func info(_ node: AXUIElement) -> NodeInfo? {
        // One round trip for all attributes; a missing one comes back as an AXValue error.
        var values: CFArray?
        let result = AXUIElementCopyMultipleAttributeValues(
            node, Self.names as CFArray, [], &values)
        guard result == .success, let list = values as? [AnyObject], list.count == Self.names.count
        else { return nil }
        let value = list.map { Self.isError($0) ? nil : $0 }
        guard let role = value[0] as? String else { return nil }
        let subrole = value[1] as? String
        return NodeInfo(
            role: role, subrole: subrole, title: AX.text(value[2]),
            description: AX.text(value[3]), placeholder: AX.text(value[4]),
            value: Roles.isSecure(role: role, subrole: subrole) ? nil : AX.text(value[5]),
            enabled: (value[6] as? NSNumber)?.boolValue ?? true,
            focused: (value[7] as? NSNumber)?.boolValue ?? false,
            frame: AX.frame(position: value[8], size: value[9]), actions: AX.actions(node))
    }

    func children(_ node: AXUIElement) -> [AXUIElement] {
        AX.children(node)
    }

    private static func isError(_ value: AnyObject) -> Bool {
        CFGetTypeID(value) == AXValueGetTypeID()
            && AXValueGetType(value as! AXValue) == .axError
    }
}

extension Desktop {
    func tree(window id: String, maxNodes: Int, maxDepth: Int) async throws(HelperError)
        -> [String: JSONValue]
    {
        let window = try window(id)
        await prepare(window.pid)
        let builder = OutlineBuilder(maxNodes: maxNodes, maxDepth: maxDepth)
        let outline = builder.build(
            root: window.element, source: AXTree(), window: AX.frame(window.element)
        ) { elementID($0, window: id) }
        return [
            "title": .optional(AX.string(window.element, kAXTitleAttribute)),
            "elements": .array(outline.elements.map(\.json)),
            "truncated": .bool(outline.truncated),
        ]
    }
}
