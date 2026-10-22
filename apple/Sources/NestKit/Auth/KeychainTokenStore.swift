import Foundation
import LocalAuthentication
import Security

/// A Keychain call that failed with this status.
public struct KeychainError: LocalizedError, Sendable, Equatable {
    public let status: OSStatus

    public init(status: OSStatus) {
        self.status = status
    }

    public var message: String { "the Keychain refused: " + reason }

    /// The system's words for the status.
    private var reason: String {
        guard let text = SecCopyErrorMessageString(status, nil) else { return "error \(status)" }
        return text as String
    }

    public var errorDescription: String? { message }
}

/// Generic-password items by service and account; tests keep them in memory.
protocol KeychainItems: Sendable {
    func read(service: String, account: String) throws -> Data?
    func write(_ data: Data, service: String, account: String) throws
    func delete(service: String, account: String) throws
}

/// The login Keychain (the data-protection one needs a team ID, which this app has none
/// of). An item this app made stays readable by its later builds signed the same way, and
/// a read never asks the user.
struct SystemKeychain: KeychainItems {
    private func query(_ service: String, _ account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    func read(service: String, account: String) throws -> Data? {
        var search = query(service, account)
        search[kSecReturnData as String] = true
        search[kSecMatchLimit as String] = kSecMatchLimitOne
        // Never a prompt: an item another app made fails instead.
        let context = LAContext()
        context.interactionNotAllowed = true
        search[kSecUseAuthenticationContext as String] = context
        var result: CFTypeRef?
        let status = SecItemCopyMatching(search as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        try Self.check(status)
        return result as? Data
    }

    func write(_ data: Data, service: String, account: String) throws {
        let item = query(service, account)
        let status = SecItemUpdate(
            item as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        guard status == errSecItemNotFound else { return try Self.check(status) }
        var added = item
        added[kSecValueData as String] = data
        added[kSecAttrLabel as String] = "Nest remote device token"
        try Self.check(SecItemAdd(added as CFDictionary, nil))
    }

    func delete(service: String, account: String) throws {
        let status = SecItemDelete(query(service, account) as CFDictionary)
        if status == errSecItemNotFound { return }
        try Self.check(status)
    }

    static func check(_ status: OSStatus) throws {
        if status != errSecSuccess { throw KeychainError(status: status) }
    }
}

/// This Mac's device token on a daemon on another machine, which it got by pairing: one
/// Keychain item per daemon, service `nest`, account `remote-device-token <base URL>`.
public struct KeychainTokenStore: TokenStore {
    public static let service = "nest"

    let service: String
    let baseURL: URL
    let items: any KeychainItems

    public init(baseURL: URL) {
        self.init(baseURL: baseURL, items: SystemKeychain())
    }

    init(service: String = Self.service, baseURL: URL, items: any KeychainItems) {
        self.service = service
        self.baseURL = baseURL
        self.items = items
    }

    var account: String { "remote-device-token \(baseURL.absoluteString)" }

    public func deviceToken() throws -> String? {
        guard let data = try items.read(service: service, account: account) else { return nil }
        guard let text = String(data: data, encoding: .utf8) else {
            throw TokenStoreError.malformed
        }
        let token = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return token.isEmpty ? nil : token
    }

    public func save(_ token: String) throws {
        try items.write(Data(token.utf8), service: service, account: account)
    }

    public func delete() throws {
        try items.delete(service: service, account: account)
    }
}
