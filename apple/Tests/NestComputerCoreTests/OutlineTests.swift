import NestComputerCore
import Testing

/// A tree of plain values standing in for the Accessibility API.
private final class FakeTree: TreeSource {
    var infos: [Int: NodeInfo] = [:]
    var kids: [Int: [Int]] = [:]

    func add(_ node: Int, under parent: Int, _ info: NodeInfo) {
        infos[node] = info
        kids[parent, default: []].append(node)
    }

    func info(_ node: Int) -> NodeInfo? { infos[node] }
    func children(_ node: Int) -> [Int] { kids[node] ?? [] }
}

@Suite struct OutlineTests {
    private static let window = Rect(x: 100, y: 50, width: 800, height: 600)

    private func build(
        _ tree: FakeTree, registry: inout IDRegistry<Int>, maxNodes: Int = 400, maxDepth: Int = 30
    ) -> Outline {
        OutlineBuilder(maxNodes: maxNodes, maxDepth: maxDepth).build(
            root: 0, source: tree, window: Self.window
        ) { registry.id(for: $0, owner: "w1") }
    }

    /// Window > nameless group > (Send button, password field, Notes area).
    private func form() -> FakeTree {
        let tree = FakeTree()
        tree.add(1, under: 0, NodeInfo(role: "AXGroup"))
        tree.add(
            2, under: 1,
            NodeInfo(
                role: "AXButton", title: "Send",
                frame: Rect(x: 110, y: 60, width: 40, height: 20), actions: ["AXPress"]))
        tree.add(
            3, under: 1,
            NodeInfo(role: "AXTextField", subrole: "AXSecureTextField", value: "hunter2"))
        tree.add(4, under: 1, NodeInfo(role: "AXTextArea", description: "Notes", value: "hi"))
        return tree
    }

    @Test func namelessContainersAreWalkedThroughNotListed() {
        var registry = IDRegistry<Int>(prefix: "e")
        let outline = build(form(), registry: &registry)
        #expect(outline.elements.map(\.role) == ["AXButton", "AXTextField", "AXTextArea"])
        #expect(outline.elements.map(\.depth) == [0, 0, 0])
        #expect(outline.elements.map(\.label) == ["Send", nil, "Notes"])
        #expect(!outline.truncated)
    }

    @Test func framesAreInWindowPoints() {
        var registry = IDRegistry<Int>(prefix: "e")
        let send = build(form(), registry: &registry).elements[0]
        #expect(send.frame == Rect(x: 10, y: 10, width: 40, height: 20))
    }

    @Test func secureFieldsAreMarkedAndTheirValueIsNeverSent() {
        var registry = IDRegistry<Int>(prefix: "e")
        let outline = build(form(), registry: &registry)
        let password = outline.elements[1]
        #expect(password.secure)
        #expect(password.field)
        #expect(password.value == nil)
        #expect(!outline.elements[2].secure)
        #expect(!outline.elements[2].field)
        #expect(Roles.isSecure(role: "AXSecureTextField", subrole: nil))
        #expect(!Roles.isSecure(role: "AXTextField", subrole: "AXSearchField"))
    }

    @Test func idsStayTheSameAcrossReads() {
        var registry = IDRegistry<Int>(prefix: "e")
        let tree = form()
        let first = build(tree, registry: &registry).elements.map(\.id)
        tree.add(5, under: 0, NodeInfo(role: "AXButton", title: "Cancel", actions: ["AXPress"]))
        let second = build(tree, registry: &registry).elements.map(\.id)
        #expect(first == ["e1", "e2", "e3"])
        #expect(second == ["e1", "e2", "e3", "e4"])
    }

    @Test func goneNodesAreSkipped() {
        var registry = IDRegistry<Int>(prefix: "e")
        let tree = form()
        tree.infos[2] = nil
        #expect(
            build(tree, registry: &registry).elements.map(\.role) == ["AXTextField", "AXTextArea"])
    }

    @Test func limitsCutTheOutlineAndSaySo() {
        var registry = IDRegistry<Int>(prefix: "e")
        let byCount = build(form(), registry: &registry, maxNodes: 2)
        #expect(byCount.elements.count == 2)
        #expect(byCount.truncated)
        // Depth 1 reaches only the nameless group, whose children are then left out.
        let byDepth = build(form(), registry: &registry, maxDepth: 1)
        #expect(byDepth.elements.isEmpty)
        #expect(byDepth.truncated)
    }

    @Test func listedParentsIndentTheirChildren() {
        var registry = IDRegistry<Int>(prefix: "e")
        let tree = FakeTree()
        tree.add(1, under: 0, NodeInfo(role: "AXToolbar", description: "Toolbar"))
        tree.add(2, under: 1, NodeInfo(role: "AXGroup"))
        tree.add(3, under: 2, NodeInfo(role: "AXButton", title: "Back", actions: ["AXPress"]))
        tree.add(4, under: 0, NodeInfo(role: "AXGroup", actions: ["AXShowMenu"]))
        let outline = build(tree, registry: &registry)
        #expect(outline.elements.map(\.label) == ["Toolbar", "Back"])
        #expect(outline.elements.map(\.depth) == [0, 1])
    }
}

@Suite struct RegistryTests {
    @Test func aGoneThingIsStaleAndANeverSeenOneUnknown() {
        var registry = IDRegistry<String>(prefix: "w")
        let id = registry.id(for: "mail", owner: "42")
        #expect(registry.id(for: "mail", owner: "42") == id)
        #expect(registry.lookup(id) == .found("mail", owner: "42"))
        registry.retire(id)
        #expect(registry.lookup(id) == .stale)
        #expect(registry.lookup("w99") == .unknown)
        // Seen again, it gets a new id: the old one stays stale.
        #expect(registry.id(for: "mail", owner: "42") != id)
    }

    @Test func retiringAnOwnerRetiresAllItsIds() {
        var registry = IDRegistry<Int>(prefix: "e")
        let a = registry.id(for: 1, owner: "w1")
        let b = registry.id(for: 2, owner: "w1")
        let other = registry.id(for: 3, owner: "w2")
        #expect(registry.retire(owner: "w1") == [a, b])
        #expect(registry.lookup(a) == .stale)
        #expect(registry.lookup(b) == .stale)
        #expect(registry.lookup(other) == .found(3, owner: "w2"))
    }
}
