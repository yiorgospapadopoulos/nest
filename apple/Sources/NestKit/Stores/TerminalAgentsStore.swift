import Foundation
import Observation

/// Settings > Terminal agents (B151): the outside clients and the level each has.
@MainActor @Observable
public final class TerminalAgentsStore {
    /// Nil until loaded.
    public private(set) var clients: [OutsideClient]?
    /// The client whose change the daemon is making.
    public private(set) var changing: OutsideClientKind?

    let api: any NestAPI

    public init(api: any NestAPI) {
        self.api = api
    }

    public func load() async throws {
        clients = try await api.outsideClients()
    }

    /// Switches the client on at `access`, or off with nil, and shows it as the daemon
    /// reports it after. A refused change, as when Claude Code is missing, leaves it.
    public func set(_ kind: OutsideClientKind, _ access: OutsideAccess?) async throws {
        changing = kind
        defer { changing = nil }
        let changed =
            if let access {
                try await api.turnOnOutsideClient(kind, access)
            } else {
                try await api.turnOffOutsideClient(kind)
            }
        clients = clients?.map { $0.kind == kind ? changed : $0 }
    }
}
