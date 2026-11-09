/// What the helper read from one accessibility element.
public struct NodeInfo: Sendable, Equatable {
    public var role: String
    public var subrole: String?
    public var title: String?
    public var description: String?
    public var placeholder: String?
    public var value: String?
    public var enabled: Bool
    public var focused: Bool
    /// In screen points.
    public var frame: Rect?
    public var actions: [String]

    public init(
        role: String, subrole: String? = nil, title: String? = nil, description: String? = nil,
        placeholder: String? = nil, value: String? = nil, enabled: Bool = true,
        focused: Bool = false, frame: Rect? = nil, actions: [String] = []
    ) {
        self.role = role
        self.subrole = subrole
        self.title = title
        self.description = description
        self.placeholder = placeholder
        self.value = value
        self.enabled = enabled
        self.focused = focused
        self.frame = frame
        self.actions = actions
    }
}

/// One line of a window's outline, as the `tree` op sends it.
public struct Element: Sendable, Equatable {
    public var id: String
    public var role: String
    public var subrole: String?
    public var label: String?
    public var value: String?
    public var depth: Int
    public var enabled: Bool
    public var focused: Bool
    public var secure: Bool
    public var field: Bool
    public var actions: [String]
    /// In window points.
    public var frame: Rect?

    public var json: JSONValue {
        var object: [String: JSONValue] = [
            "id": .string(id), "role": .string(role), "label": .optional(label),
            "value": .optional(value), "depth": .int(depth), "enabled": .bool(enabled),
            "focused": .bool(focused), "secure": .bool(secure), "field": .bool(field),
            "actions": .array(actions.map(JSONValue.string)), "frame": frame?.json ?? .null,
        ]
        if let subrole { object["subrole"] = .string(subrole) }
        return .object(object)
    }
}

/// A tree the outline can be built from: the Accessibility API in the helper, plain values
/// in tests. `info` is nil for a node that is gone.
public protocol TreeSource {
    associatedtype Node: Hashable
    func info(_ node: Node) -> NodeInfo?
    func children(_ node: Node) -> [Node]
}

public struct Outline: Sendable, Equatable {
    public var elements: [Element]
    public var truncated: Bool
}

/// Builds a window's outline: the elements worth naming, depth first. Nameless containers
/// with nothing to do are walked through but not listed, so their children sit one level
/// under the nearest listed ancestor.
public struct OutlineBuilder {
    /// Actions every element of some apps offers; they do not make an element worth listing.
    static let quietActions: Set<String> = ["AXShowMenu", "AXScrollToVisible"]
    /// Actions left out of the outline.
    static let hiddenActions: Set<String> = [
        "AXScrollToVisible", "AXShowDefaultUI", "AXShowAlternateUI",
    ]
    static let editableRoles: Set<String> = [
        "AXTextField", "AXTextArea", "AXComboBox", "AXSecureTextField", "AXSearchField",
    ]
    /// Longer values (a whole document) are cut to this many characters.
    public static let maxValueLength = 2000

    public var maxNodes: Int
    public var maxDepth: Int
    /// Elements read in all, listed or not, so a huge tree cannot stall the helper.
    public var maxVisits: Int

    public init(maxNodes: Int, maxDepth: Int, maxVisits: Int = 8000) {
        self.maxNodes = maxNodes
        self.maxDepth = maxDepth
        self.maxVisits = maxVisits
    }

    /// The outline under `root` (the window, which is not listed itself). `window` is the
    /// window's frame, for element frames in window points; `register` gives each listed
    /// node its id.
    public func build<Source: TreeSource>(
        root: Source.Node, source: Source, window: Rect?,
        register: (Source.Node) -> String
    ) -> Outline {
        var elements: [Element] = []
        var truncated = false
        var visits = 0
        // Depth first, in order: a stack of (node, AX depth, outline depth), reversed children.
        var stack: [(node: Source.Node, depth: Int, level: Int)] = source.children(root)
            .reversed().map { ($0, 1, 0) }
        while let (node, depth, level) = stack.popLast() {
            if elements.count >= maxNodes || visits >= maxVisits {
                truncated = true
                break
            }
            visits += 1
            guard let info = source.info(node) else { continue }
            var childLevel = level
            if Self.isListed(info) {
                elements.append(element(info, id: register(node), level: level, window: window))
                childLevel = level + 1
            }
            let children = source.children(node)
            if depth >= maxDepth {
                if !children.isEmpty { truncated = true }
                continue
            }
            stack.append(contentsOf: children.reversed().map { ($0, depth + 1, childLevel) })
        }
        return Outline(elements: elements, truncated: truncated)
    }

    static func isListed(_ info: NodeInfo) -> Bool {
        if label(info) != nil || !(info.value ?? "").isEmpty { return true }
        if editableRoles.contains(info.role) { return true }
        return info.actions.contains { !quietActions.contains($0) }
    }

    static func label(_ info: NodeInfo) -> String? {
        [info.title, info.description, info.placeholder].lazy.compactMap { $0 }
            .first { !$0.isEmpty }
    }

    private func element(_ info: NodeInfo, id: String, level: Int, window: Rect?) -> Element {
        let secure = Roles.isSecure(role: info.role, subrole: info.subrole)
        var value = secure ? nil : info.value
        if let text = value, text.count > Self.maxValueLength {
            value = String(text.prefix(Self.maxValueLength)) + "…"
        }
        return Element(
            id: id, role: info.role, subrole: info.subrole, label: Self.label(info),
            value: value, depth: level, enabled: info.enabled, focused: info.focused,
            secure: secure, field: Roles.isSingleLineField(role: info.role, subrole: info.subrole),
            actions: info.actions.filter { !Self.hiddenActions.contains($0) },
            frame: window.flatMap { origin in info.frame.map { $0.relative(to: origin) } })
    }
}
