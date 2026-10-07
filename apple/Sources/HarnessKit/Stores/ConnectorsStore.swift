import Foundation
import Observation

/// The connectors sheet's two groups.
public enum ConnectorSectionKind: String, Sendable, CaseIterable {
    case claudeAI, claudeCode

    public var title: String {
        switch self {
        case .claudeAI: "claude.ai connectors"
        case .claudeCode: "Plugins and local servers"
        }
    }
}

public struct ConnectorSection: Sendable, Hashable, Identifiable {
    public let kind: ConnectorSectionKind
    public let connectors: [Connector]

    public var id: ConnectorSectionKind { kind }
    public var title: String { kind.title }

    /// What the folded group's header warns about, such as "1 needs sign-in, 2 failed";
    /// nil when nothing needs sign-in or failed.
    public var attention: String? {
        let states = connectors.map(\.state)
        let signIns = states.count(where: { $0 == .needsSignIn })
        let failures = states.count(where: { $0 == .failed })
        let parts = [
            signIns > 0 ? "\(signIns) \(signIns == 1 ? "needs" : "need") sign-in" : nil,
            failures > 0 ? "\(failures) failed" : nil,
        ].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: ", ")
    }
}

/// A connector's status as the sheet's pill shows it.
public enum ConnectorState: Sendable, Hashable {
    case connected, needsSignIn, failed, pending
    /// A status this app does not know, shown as Claude Code reported it.
    case other(String)

    public init(status: String) {
        switch status {
        case "connected": self = .connected
        case "needs-auth", "needs_auth": self = .needsSignIn
        case "failed": self = .failed
        case "pending": self = .pending
        default: self = .other(status)
        }
    }

    public var label: String {
        switch self {
        case .connected: "Connected"
        case .needsSignIn: "Needs sign-in"
        case .failed: "Failed"
        case .pending: "Pending"
        case .other(let status): status.prefix(1).uppercased() + status.dropFirst()
        }
    }

    public var tone: StatusTone {
        switch self {
        case .connected: .review
        case .needsSignIn: .waiting
        case .failed: .failed
        case .pending: .running
        case .other: .done
        }
    }
}

extension Connector {
    public var state: ConnectorState { ConnectorState(status: status) }

    /// claude.ai connectors are signed into on claude.ai; others are set up in Claude Code.
    public var managedOnClaudeAI: Bool {
        group == .claudeAI || manageHint == .claudeAI
    }
}

/// MCP servers and claude.ai connectors with the status Claude Code reported.
@MainActor @Observable
public final class ConnectorsStore {
    public private(set) var connectors: [Connector] = []

    let api: any HarnessAPI

    public init(api: any HarnessAPI) {
        self.api = api
    }

    public func load() async throws {
        connectors = try await api.connectors()
    }

    /// Where users sign in on claude.ai to the connectors that need it.
    public static let claudeAISettings = URL(string: "https://claude.ai/settings/connectors")!

    /// claude.ai connectors, then plugins and local servers; empty groups left out.
    public var sections: [ConnectorSection] {
        ConnectorSectionKind.allCases.compactMap { kind in
            let members = connectors.filter {
                ($0.group == .claudeAI ? ConnectorSectionKind.claudeAI : .claudeCode) == kind
            }
            return members.isEmpty ? nil : ConnectorSection(kind: kind, connectors: members)
        }
    }

    /// Connectors that are not connected, such as ones needing sign-in or failing.
    public var needingAttention: Int {
        connectors.count { $0.status != "connected" }
    }

    public func apply(_ event: Event) {
        if case .connectorsUpdated(let list) = event.body {
            connectors = list
        }
    }
}
