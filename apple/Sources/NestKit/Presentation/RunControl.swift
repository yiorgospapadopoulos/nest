import Foundation

/// A listening port of a run, as a chip (B108).
public struct RunPort: Sendable, Hashable, Identifiable {
    public let port: Int
    /// The first port: the green dot, the one a click on the control opens.
    public let live: Bool
    /// The page a click opens in a browser pane; nil while the daemon runs on another
    /// machine, whose localhost this Mac cannot reach.
    public let url: String?
    public let help: String

    public var id: Int { port }
    public var label: String { String(port) }
}

/// The Run control of a chat's pane header, by its folder's run state (B108).
public enum RunControl: Sendable, Hashable {
    /// Play and "Run": stopped, never started, or exited with 0.
    case run(help: String)
    /// A spinner and "Starting"; a click stops it.
    case starting(help: String)
    /// The port chips, "+N" for those left out, then stop.
    case running(ports: [RunPort], more: Int, moreHelp: String?, stopHelp: String)
    /// Red play and "Exited N"; a click runs it again.
    case exited(label: String, help: String)

    /// More ports than this show the first two and "+N".
    public static let maximumChips = 3

    /// Nil when the chat has no run command (or its status is not read yet). `compact`
    /// panes show only the first port; `machine` names the daemon's machine when it is
    /// another one.
    public init?(status: RunStatus?, compact: Bool = false, machine: String? = nil) {
        guard let status, status.available, let command = status.command else { return nil }
        switch status.state {
        case .starting:
            self = .starting(help: "Starting \(command). Click to stop")
        case .running where !status.listening.isEmpty:
            let ports = Self.ports(status, machine: machine)
            let shown =
                compact
                ? 1 : ports.count > Self.maximumChips ? Self.maximumChips - 1 : ports.count
            let rest = ports.dropFirst(shown).map(\.label)
            self = .running(
                ports: Array(ports.prefix(shown)), more: rest.count,
                moreHelp: rest.isEmpty ? nil : "Also \(rest.joined(separator: ", "))",
                stopHelp: "Stop \(command)")
        case .running:
            self = .starting(help: "Starting \(command). Click to stop")
        case .exited:
            guard let code = status.exitCode, code != 0 else {
                self = .run(help: "Run \(command)")
                return
            }
            self = .exited(
                label: "Exited \(code)",
                help: "\(command) exited with code \(code). Click to run again")
        case .stopped, .unknown:
            self = .run(help: "Run \(command)")
        }
    }

    /// Every listening port as a chip, the first one live.
    public static func ports(_ status: RunStatus, machine: String? = nil) -> [RunPort] {
        status.listening.enumerated().map { index, port in
            RunPort(
                port: port, live: index == 0,
                url: machine == nil ? "http://localhost:\(port)" : nil,
                help: help(port, block: status.block, machine: machine))
        }
    }

    static func help(_ port: Int, block: PortBlock?, machine: String?) -> String {
        if let machine {
            return "Runs on \(machine)"
        }
        if let block, !block.contains(port) {
            return "Outside this folder's ports \(block.start) to \(block.end)"
        }
        return "Open localhost:\(port)"
    }
}

/// The output pane's header (B108).
public enum RunPaneText {
    /// The title: the run's command.
    public static func title(_ status: RunStatus?) -> String {
        status?.command ?? "Run"
    }

    /// The muted name beside it: the chat's branch, else its project.
    public static func place(_ session: Session?) -> String? {
        session.map { $0.branch ?? $0.repo }
    }
}

/// Feeds a terminal from a `RunOutputBuffer`: everything once, then only what was added
/// since, and everything again after the buffer started over.
public struct RunOutputFeed: Sendable, Equatable {
    private var generation: Int?
    /// UTF-8 bytes of the buffer fed so far.
    private var fed = 0

    public init() {}

    /// What to write next: `reset` clears the terminal first. Line feeds come with the
    /// carriage return a terminal needs, as the run writes to a pipe, not a terminal.
    public mutating func next(_ buffer: RunOutputBuffer) -> (reset: Bool, text: String) {
        let reset = generation != buffer.generation || buffer.text.utf8.count < fed
        if reset {
            generation = buffer.generation
            fed = 0
        }
        let utf8 = buffer.text.utf8
        let new = String(decoding: utf8.dropFirst(fed), as: UTF8.self)
        fed = utf8.count
        return (reset, Self.terminalText(new))
    }

    /// Each bare line feed as carriage return and line feed.
    public static func terminalText(_ text: String) -> String {
        var result = ""
        var previous: Unicode.Scalar?
        for scalar in text.unicodeScalars {
            if scalar == "\n" && previous != "\r" {
                result.unicodeScalars.append("\r")
            }
            result.unicodeScalars.append(scalar)
            previous = scalar
        }
        return result
    }
}
