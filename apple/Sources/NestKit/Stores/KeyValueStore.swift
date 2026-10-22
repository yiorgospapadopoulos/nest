import Foundation

/// Small persisted preferences; tests use an in-memory fake.
public protocol KeyValueStore: AnyObject {
    func string(forKey key: String) -> String?
    func set(_ value: String?, forKey key: String)
    /// Forgets every value whose key starts with the prefix.
    func removeAll(prefixed prefix: String)
}

public final class UserDefaultsStore: KeyValueStore {
    let defaults: UserDefaults

    public init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    public func string(forKey key: String) -> String? {
        defaults.string(forKey: key)
    }

    public func set(_ value: String?, forKey key: String) {
        defaults.set(value, forKey: key)
    }

    public func removeAll(prefixed prefix: String) {
        for key in defaults.dictionaryRepresentation().keys where key.hasPrefix(prefix) {
            defaults.removeObject(forKey: key)
        }
    }
}

/// Another store's values under a key prefix, so one daemon's tabs and panes stay apart
/// from another's.
public final class PrefixedStore: KeyValueStore {
    let base: any KeyValueStore
    let prefix: String

    public init(_ base: any KeyValueStore, prefix: String) {
        self.base = base
        self.prefix = prefix
    }

    public func string(forKey key: String) -> String? {
        base.string(forKey: prefix + key)
    }

    public func set(_ value: String?, forKey key: String) {
        base.set(value, forKey: prefix + key)
    }

    public func removeAll(prefixed prefix: String) {
        base.removeAll(prefixed: self.prefix + prefix)
    }
}
