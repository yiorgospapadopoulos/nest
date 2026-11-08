/// Gives things short ids ("w3", "e12") that stay the same for the helper's life: the same
/// handle always gets the same id. A retired id stays known, so asking for it says the thing
/// is gone (`stale`) rather than never seen (`not_found`).
public struct IDRegistry<Handle: Hashable> {
    public enum Lookup: Equatable {
        case found(Handle, owner: String)
        case stale
        case unknown
    }

    private struct Entry {
        let handle: Handle
        let owner: String
    }

    public let prefix: String
    private var next = 1
    private var entries: [String: Entry] = [:]
    private var ids: [Handle: String] = [:]
    private var order: [String] = []
    private var retired: Set<String> = []

    public init(prefix: String) {
        self.prefix = prefix
    }

    /// The id of `handle`, made the first time. `owner` groups ids, such as the elements of
    /// one window, so they can be retired together.
    public mutating func id(for handle: Handle, owner: String) -> String {
        if let id = ids[handle] { return id }
        let id = "\(prefix)\(next)"
        next += 1
        entries[id] = Entry(handle: handle, owner: owner)
        ids[handle] = id
        order.append(id)
        return id
    }

    public func lookup(_ id: String) -> Lookup {
        if let entry = entries[id] { return .found(entry.handle, owner: entry.owner) }
        return retired.contains(id) ? .stale : .unknown
    }

    /// The live ids of one owner, oldest first.
    public func ids(owner: String) -> [String] {
        order.filter { entries[$0]?.owner == owner }
    }

    public mutating func retire(_ id: String) {
        guard let entry = entries.removeValue(forKey: id) else { return }
        ids.removeValue(forKey: entry.handle)
        order.removeAll { $0 == id }
        retired.insert(id)
    }

    /// Retires every id of `owner` and returns them.
    @discardableResult
    public mutating func retire(owner: String) -> [String] {
        let gone = ids(owner: owner)
        for id in gone { retire(id) }
        return gone
    }
}
