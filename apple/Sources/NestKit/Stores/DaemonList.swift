import Foundation
import Observation

/// A daemon on another machine this Mac paired with, reached at its `tailscale serve`
/// address with a device token kept in the Keychain (`KeychainTokenStore`).
public struct RemoteDaemon: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    /// The machine's name for people, as its daemon gives it.
    public var machine: String
    public var baseURL: URL
    /// This Mac's device on that daemon, and the name it was paired under.
    public var deviceID: String
    public var deviceName: String
    public var pairedAt: Date
    public var lastConnected: Date?

    public init(
        id: String = UUID().uuidString, machine: String, baseURL: URL, deviceID: String,
        deviceName: String, pairedAt: Date, lastConnected: Date? = nil
    ) {
        self.id = id
        self.machine = machine
        self.baseURL = baseURL
        self.deviceID = deviceID
        self.deviceName = deviceName
        self.pairedAt = pairedAt
        self.lastConnected = lastConnected
    }

    /// Where this daemon's tabs and panes are kept in the preferences, apart from This
    /// Mac's and other daemons'.
    public var preferencesPrefix: String { "daemon.\(id)." }
}

/// Which daemon the window talks to.
public enum DaemonChoice: Sendable, Equatable {
    case local
    case remote(RemoteDaemon)
}

/// The daemons this Mac can talk to, one at a time: This Mac, always first and never
/// removed (where `DaemonLocation` says, so `NEST_DAEMON_URL` and `NEST_DATA_DIR` stay a
/// launch-time override for it only), and the paired remotes. Kept on this Mac only, with
/// the selected one.
@MainActor @Observable
public final class DaemonList {
    static let key = "daemons"

    private struct Saved: Codable {
        var remotes: [RemoteDaemon]
        var selected: String?
    }

    public let local: DaemonLocation
    public private(set) var remotes: [RemoteDaemon] = []
    /// The selected remote's id; nil is This Mac.
    public private(set) var selected: String?

    @ObservationIgnored let store: any KeyValueStore
    @ObservationIgnored let keychain: any KeychainItems

    public convenience init(local: DaemonLocation, defaults: UserDefaults = .standard) {
        self.init(
            local: local, store: UserDefaultsStore(defaults: defaults), keychain: SystemKeychain())
    }

    init(local: DaemonLocation, store: any KeyValueStore, keychain: any KeychainItems) {
        self.local = local
        self.store = store
        self.keychain = keychain
        if let text = store.string(forKey: Self.key),
            let saved = try? JSONDecoder().decode(Saved.self, from: Data(text.utf8))
        {
            remotes = saved.remotes
            selected = saved.selected
        }
    }

    /// The selected daemon; a selection naming a remote that is gone means This Mac.
    public var selection: DaemonChoice {
        selected.flatMap(remote).map(DaemonChoice.remote) ?? .local
    }

    public func remote(_ id: String) -> RemoteDaemon? {
        remotes.first { $0.id == id }
    }

    /// Where the remote's device token is kept.
    public func tokens(for daemon: RemoteDaemon) -> KeychainTokenStore {
        KeychainTokenStore(baseURL: daemon.baseURL, items: keychain)
    }

    /// Selects a remote by id, or This Mac with nil.
    public func select(_ id: String?) {
        selected = id
        persist()
    }

    /// Adds the daemon, or replaces the one at the same address, keeping its id; answers
    /// the entry as kept.
    @discardableResult
    public func save(_ daemon: RemoteDaemon) -> RemoteDaemon {
        var entry = daemon
        if let index = remotes.firstIndex(where: { $0.baseURL == daemon.baseURL }) {
            entry.id = remotes[index].id
            remotes[index] = entry
        } else {
            remotes.append(entry)
        }
        persist()
        return entry
    }

    /// Forgets the remote, its tabs and panes, and its token; removing the selected one
    /// selects This Mac.
    public func remove(_ id: String) throws {
        guard let daemon = remote(id) else { return }
        remotes.removeAll { $0.id == id }
        if selected == id {
            selected = nil
        }
        persist()
        store.removeAll(prefixed: daemon.preferencesPrefix)
        try tokens(for: daemon).delete()
    }

    /// A connect to the remote: its machine name now, and when.
    public func seen(_ id: String, machine: String, at date: Date) {
        guard let index = remotes.firstIndex(where: { $0.id == id }) else { return }
        remotes[index].machine = machine
        remotes[index].lastConnected = date
        persist()
    }

    private func persist() {
        let data = try? JSONEncoder().encode(Saved(remotes: remotes, selected: selected))
        store.set(data.map { String(decoding: $0, as: UTF8.self) }, forKey: Self.key)
    }
}
