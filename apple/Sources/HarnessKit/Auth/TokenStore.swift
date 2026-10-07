import Foundation
import Security

/// Where the Mac's own device token comes from.
public protocol TokenStore: Sendable {
    /// The token, or nil when the daemon has not created one yet.
    func deviceToken() throws -> String?
}

public enum TokenStoreError: Error, Sendable, Equatable {
    case keychain(OSStatus)
    case notText
}

/// Reads the token the daemon stores in the login Keychain (generic password, service
/// `harness`, account `local-device-token`). It never writes to the Keychain.
public struct KeychainTokenStore: TokenStore {
    public static let service = "harness"
    public static let account = "local-device-token"

    typealias CopyMatching = @Sendable (CFDictionary, UnsafeMutablePointer<CFTypeRef?>?) -> OSStatus

    let service: String
    let account: String
    let copyMatching: CopyMatching

    public init() {
        self.init(service: Self.service, account: Self.account, copyMatching: SecItemCopyMatching)
    }

    init(service: String, account: String, copyMatching: @escaping CopyMatching) {
        self.service = service
        self.account = account
        self.copyMatching = copyMatching
    }

    public func deviceToken() throws -> String? {
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
            kSecMatchLimit: kSecMatchLimitOne,
            kSecReturnData: true,
        ]
        var result: CFTypeRef?
        let status = copyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound {
            return nil
        }
        guard status == errSecSuccess else {
            throw TokenStoreError.keychain(status)
        }
        guard let data = result as? Data, let token = String(data: data, encoding: .utf8) else {
            throw TokenStoreError.notText
        }
        return token
    }
}
