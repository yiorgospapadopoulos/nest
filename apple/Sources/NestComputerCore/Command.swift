/// A permission the helper can ask macOS for.
public enum Permission: String, Sendable {
    case accessibility
    case screenRecording = "screen_recording"
}

public enum ScrollDirection: String, Sendable {
    case up, down, left, right
}

/// What a `scroll` scrolls: an element (its scroll area) or an app's front window.
public enum ScrollTarget: Sendable, Equatable {
    case element(String)
    case pid(Int32)
}

/// A request's op with its arguments checked.
public enum Command: Sendable, Equatable {
    case hello
    case askPermission(Permission)
    case apps
    case launch(bundleID: String)
    case tree(window: String, maxNodes: Int, maxDepth: Int)
    case menu(pid: Int32, path: [String])
    case press(element: String, action: String)
    case setValue(element: String, text: String)
    case focus(element: String)
    case type(pid: Int32, text: String)
    case key(pid: Int32, code: UInt16, modifiers: Set<Modifier>)
    case scroll(target: ScrollTarget, direction: ScrollDirection, amount: Int)
    case click(window: String, x: Double, y: Double)
    case front(pid: Int32, window: String?)
    case screenshot(window: String)

    public static let maxTypedLength = 10_000

    /// Every op but these reads or drives other apps, which needs Accessibility.
    public var needsAccessibility: Bool {
        switch self {
        case .hello, .askPermission, .launch: false
        default: true
        }
    }

    public init(_ request: Request) throws(HelperError) {
        let args = Arguments(request.args)
        switch request.op {
        case "hello": self = .hello
        case "ask_permission":
            let name = try args.string("name")
            guard let permission = Permission(rawValue: name) else {
                throw HelperError(.badRequest, "name must be accessibility or screen_recording")
            }
            self = .askPermission(permission)
        case "apps": self = .apps
        case "launch": self = .launch(bundleID: try args.string("bundle_id"))
        case "tree":
            self = .tree(
                window: try args.id("window", prefix: "w"),
                maxNodes: try args.int("max_nodes", default: 400, in: 1...2000),
                maxDepth: try args.int("max_depth", default: 30, in: 1...100))
        case "menu":
            let path = try args.strings("path")
            guard (1...10).contains(path.count) else {
                throw HelperError(.badRequest, "path must have 1 to 10 items")
            }
            self = .menu(pid: try args.pid(), path: path)
        case "press":
            let action = try args.optionalString("action") ?? "AXPress"
            guard action.hasPrefix("AX") else {
                throw HelperError(.badRequest, "action must be an AX action name")
            }
            self = .press(element: try args.id("element", prefix: "e"), action: action)
        case "set_value":
            self = .setValue(
                element: try args.id("element", prefix: "e"),
                text: try args.string("text", allowEmpty: true))
        case "focus": self = .focus(element: try args.id("element", prefix: "e"))
        case "type":
            let text = try args.string("text")
            guard text.count <= Self.maxTypedLength else {
                throw HelperError(.badRequest, "text is longer than \(Self.maxTypedLength)")
            }
            self = .type(pid: try args.pid(), text: text)
        case "key":
            let name = try args.string("key")
            guard let code = KeyCodes.code(for: name) else {
                throw HelperError(.badRequest, "unknown key \"\(name)\"")
            }
            var modifiers: Set<Modifier> = []
            for name in try args.strings("modifiers", required: false) {
                guard let modifier = Modifier(rawValue: name) else {
                    throw HelperError(.badRequest, "unknown modifier \"\(name)\"")
                }
                modifiers.insert(modifier)
            }
            self = .key(pid: try args.pid(), code: code, modifiers: modifiers)
        case "scroll":
            let target: ScrollTarget
            if args.has("element") {
                target = .element(try args.id("element", prefix: "e"))
            } else if args.has("pid") {
                target = .pid(try args.pid())
            } else {
                throw HelperError(.badRequest, "scroll needs element or pid")
            }
            let direction = try args.string("direction")
            guard let parsed = ScrollDirection(rawValue: direction) else {
                throw HelperError(.badRequest, "direction must be up, down, left or right")
            }
            self = .scroll(
                target: target, direction: parsed,
                amount: try args.int("amount", default: 3, in: 1...50))
        case "click":
            self = .click(
                window: try args.id("window", prefix: "w"), x: try args.number("x"),
                y: try args.number("y"))
        case "front":
            self = .front(
                pid: try args.pid(),
                window: args.has("window") ? try args.id("window", prefix: "w") : nil)
        case "screenshot": self = .screenshot(window: try args.id("window", prefix: "w"))
        default:
            throw HelperError(.badRequest, "unknown op \"\(request.op)\"")
        }
    }
}

/// Typed reads of a request's arguments; a missing or wrong argument is `bad_request`.
struct Arguments {
    let values: [String: JSONValue]

    init(_ values: [String: JSONValue]) {
        self.values = values
    }

    func has(_ name: String) -> Bool {
        if case nil = values[name] { return false }
        if case .null? = values[name] { return false }
        return true
    }

    func optionalString(_ name: String) throws(HelperError) -> String? {
        switch values[name] {
        case nil, .null: return nil
        case .string(let value): return value
        default: throw HelperError(.badRequest, "\(name) must be a string")
        }
    }

    func string(_ name: String, allowEmpty: Bool = false) throws(HelperError) -> String {
        guard let value = try optionalString(name) else {
            throw HelperError(.badRequest, "\(name) is missing")
        }
        guard allowEmpty || !value.isEmpty else {
            throw HelperError(.badRequest, "\(name) is empty")
        }
        return value
    }

    func strings(_ name: String, required: Bool = true) throws(HelperError) -> [String] {
        switch values[name] {
        case nil, .null:
            if required { throw HelperError(.badRequest, "\(name) is missing") }
            return []
        case .array(let items):
            var result: [String] = []
            for item in items {
                guard case .string(let value) = item, !value.isEmpty else {
                    throw HelperError(.badRequest, "\(name) must hold non-empty strings")
                }
                result.append(value)
            }
            return result
        default:
            throw HelperError(.badRequest, "\(name) must be a list of strings")
        }
    }

    func int(_ name: String, default fallback: Int, in range: ClosedRange<Int>)
        throws(HelperError) -> Int
    {
        let value: Int
        switch values[name] {
        case nil, .null: return fallback
        case .int(let number): value = number
        default: throw HelperError(.badRequest, "\(name) must be an integer")
        }
        guard range.contains(value) else {
            throw HelperError(
                .badRequest, "\(name) must be from \(range.lowerBound) to \(range.upperBound)")
        }
        return value
    }

    func number(_ name: String) throws(HelperError) -> Double {
        switch values[name] {
        case .int(let value)?: return Double(value)
        case .double(let value)? where value.isFinite: return value
        case nil, .null?: throw HelperError(.badRequest, "\(name) is missing")
        default: throw HelperError(.badRequest, "\(name) must be a number")
        }
    }

    func pid() throws(HelperError) -> Int32 {
        guard case .int(let value)? = values["pid"] else {
            throw HelperError(.badRequest, "pid must be an integer")
        }
        guard value > 0, value <= Int(Int32.max) else {
            throw HelperError(.badRequest, "pid is not a process id")
        }
        return Int32(value)
    }

    /// A window ("w3") or element ("e12") id.
    func id(_ name: String, prefix: String) throws(HelperError) -> String {
        let value = try string(name)
        let digits = value.dropFirst(prefix.count)
        guard value.hasPrefix(prefix), !digits.isEmpty, digits.allSatisfy(\.isASCIIDigit) else {
            throw HelperError(.badRequest, "\(name) must be an id like \(prefix)1")
        }
        return value
    }
}

extension Character {
    fileprivate var isASCIIDigit: Bool { isASCII && isNumber }
}
