import Foundation

/// The Add server and Edit form (B97): a command with its arguments and environment, or
/// a URL with its headers, as text fields with one entry per line.
public struct MCPServerForm: Sendable, Hashable {
    public var name: String
    public var transport: MCPTransport
    public var command: String
    /// One argument per line.
    public var args: String
    /// `KEY=value` per line.
    public var env: String
    public var url: String
    /// `Name: value` per line.
    public var headers: String
    /// Editing keeps the name; a new server is named in the form.
    public let isNew: Bool

    public init() {
        name = ""
        transport = .stdio
        command = ""
        args = ""
        env = ""
        url = ""
        headers = ""
        isNew = true
    }

    /// The form for an existing server.
    public init(name: String, spec: MCPServerSpec) {
        self.name = name
        transport = spec.transport == .unknown ? .stdio : spec.transport
        command = spec.command ?? ""
        args = spec.args.joined(separator: "\n")
        env = spec.env.sorted { $0.key < $1.key }.map { "\($0.key)=\($0.value)" }
            .joined(separator: "\n")
        url = spec.url ?? ""
        headers = spec.headers.sorted { $0.key < $1.key }.map { "\($0.key): \($0.value)" }
            .joined(separator: "\n")
        isNew = false
    }

    public var trimmedName: String { name.trimmingCharacters(in: .whitespaces) }

    /// Nil while the form is incomplete: a name, and a command or a URL for its kind.
    public var spec: MCPServerSpec? {
        guard !trimmedName.isEmpty else { return nil }
        if transport == .stdio {
            let command = command.trimmingCharacters(in: .whitespaces)
            guard !command.isEmpty else { return nil }
            return MCPServerSpec(
                transport: .stdio, command: command, args: Self.lines(args),
                env: Self.pairs(env, separator: "="))
        }
        let url = url.trimmingCharacters(in: .whitespaces)
        guard !url.isEmpty else { return nil }
        return MCPServerSpec(
            transport: transport, url: url, headers: Self.pairs(headers, separator: ":"))
    }

    static func lines(_ text: String) -> [String] {
        text.split(whereSeparator: \.isNewline)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
    }

    /// Lines without the separator are left out.
    static func pairs(_ text: String, separator: Character) -> [String: String] {
        var result: [String: String] = [:]
        for line in lines(text) {
            guard let index = line.firstIndex(of: separator) else { continue }
            let key = line[..<index].trimmingCharacters(in: .whitespaces)
            guard !key.isEmpty else { continue }
            result[key] = line[line.index(after: index)...].trimmingCharacters(in: .whitespaces)
        }
        return result
    }
}
