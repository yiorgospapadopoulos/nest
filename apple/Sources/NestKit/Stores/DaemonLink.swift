import Foundation
import Observation

/// Which daemon a model talks to: This Mac's, or a paired remote with its machine name,
/// which each connect reads again from `/api/health`.
@MainActor @Observable
public final class DaemonLink {
    /// The remote as saved when the model was built; nil is This Mac.
    public let remote: RemoteDaemon?
    public private(set) var machineName: String
    public private(set) var lastConnected: Date?
    /// Called after each connect to a remote, with its name then and the time.
    @ObservationIgnored public var onSeen: ((_ machine: String, _ at: Date) -> Void)?

    public init(remote: RemoteDaemon? = nil) {
        self.remote = remote
        machineName = remote?.machine ?? DaemonText.thisMac
        lastConnected = remote?.lastConnected
    }

    public var isRemote: Bool { remote != nil }
    public var baseURL: URL? { remote?.baseURL }

    /// A connect to the remote; This Mac keeps its name.
    func seen(machine: String?, at date: Date) {
        guard isRemote else { return }
        if let machine, !machine.isEmpty {
            machineName = machine
        }
        lastConnected = date
        onSeen?(machineName, date)
    }
}
