import Darwin
import Foundation
import Synchronization

/// The device token the API client and the event stream send. It is shared, so a token
/// asked for again (the daemon may have made a new one) reaches both.
public final class DeviceToken: Sendable {
    private let value: Mutex<String>

    public init(_ value: String) {
        self.value = Mutex(value)
    }

    public var current: String { value.withLock { $0 } }

    func replace(with token: String) {
        value.withLock { $0 = token }
    }
}

/// Where the Mac's own device token comes from.
public protocol TokenStore: Sendable {
    /// The token, or nil when the daemon is not running to give one.
    func deviceToken() throws -> String?
}

public enum TokenStoreError: LocalizedError, Sendable, Equatable {
    /// A socket call failed with this `errno`.
    case socket(Int32)
    /// The daemon closed the connection without a token: it refused this process.
    case noAnswer
    /// The answer was not a URL-safe token.
    case malformed

    public var message: String {
        switch self {
        case .socket(let code):
            "could not ask the Nest daemon for this Mac's device token"
                + " (\(String(cString: strerror(code))))"
        case .noAnswer: "the Nest daemon did not give this Mac's device token"
        case .malformed: "the Nest daemon's answer was not a device token"
        }
    }

    public var errorDescription: String? { message }
}

/// Asks the running daemon for this Mac's device token over its private Unix socket
/// (D075): `~/Library/Application Support/nest/token.sock`, in a folder only this user
/// can open. The daemon checks that the caller runs as the same user, writes the token and
/// a newline, and closes. The token itself stays in the daemon's Keychain item, which the
/// app never reads.
public struct SocketTokenStore: TokenStore {
    /// Reads everything the socket at a path answers; nil when no daemon listens there.
    typealias Exchange = @Sendable (String) throws -> Data?

    let path: String
    let exchange: Exchange

    public init(home: URL = FileManager.default.homeDirectoryForCurrentUser) {
        self.init(path: Self.path(home: home)) { try UnixSocket.read(path: $0) }
    }

    init(path: String, exchange: @escaping Exchange) {
        self.path = path
        self.exchange = exchange
    }

    /// The daemon's default data folder; a daemon run with `NEST_DATA_DIR` elsewhere is
    /// not found.
    public static func path(home: URL) -> String {
        home.appending(path: "Library/Application Support/nest/token.sock").path
    }

    public func deviceToken() throws -> String? {
        guard let data = try exchange(path) else { return nil }
        guard let text = String(data: data, encoding: .utf8) else {
            throw TokenStoreError.malformed
        }
        let token = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !token.isEmpty else { throw TokenStoreError.noAnswer }
        // `token_urlsafe`: letters, digits, `-` and `_`.
        guard token.unicodeScalars.allSatisfy(Self.tokenCharacters.contains) else {
            throw TokenStoreError.malformed
        }
        return token
    }

    private static let tokenCharacters = CharacterSet(
        charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
}

/// One blocking request to a local Unix socket: connect, read until the other end closes.
enum UnixSocket {
    /// More than any token; a longer answer is not one.
    static let maxAnswer = 4096

    /// Everything the socket at `path` sends before closing, or nil when there is no socket
    /// file or nobody listens on it (a daemon that is not running, or was killed).
    static func read(path: String, timeout: TimeInterval = 5) throws -> Data? {
        var address = try address(path)
        let descriptor = socket(AF_UNIX, SOCK_STREAM, 0)
        guard descriptor >= 0 else { throw TokenStoreError.socket(errno) }
        defer { close(descriptor) }
        let connected = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                connect(descriptor, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        if connected != 0 {
            let code = errno
            if code == ENOENT || code == ECONNREFUSED { return nil }
            throw TokenStoreError.socket(code)
        }
        // A daemon that accepts but never answers cannot hang the caller.
        var limit = timeval(
            tv_sec: Int(timeout), tv_usec: Int32(timeout.truncatingRemainder(dividingBy: 1) * 1e6))
        setsockopt(
            descriptor, SOL_SOCKET, SO_RCVTIMEO, &limit, socklen_t(MemoryLayout<timeval>.size))
        var answer = Data()
        var buffer = [UInt8](repeating: 0, count: 512)
        var count = 0
        repeat {
            count = Darwin.read(descriptor, &buffer, buffer.count)
            guard count >= 0 else { throw TokenStoreError.socket(errno) }
            answer.append(contentsOf: buffer[0..<count])
            guard answer.count <= maxAnswer else { throw TokenStoreError.malformed }
        } while count > 0
        return answer
    }

    /// The socket address of a path; a path that does not fit is `ENAMETOOLONG`.
    static func address(_ path: String) throws -> sockaddr_un {
        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        let bytes = Array(path.utf8)
        // Room for the terminating zero.
        guard bytes.count < MemoryLayout.size(ofValue: address.sun_path) else {
            throw TokenStoreError.socket(ENAMETOOLONG)
        }
        withUnsafeMutableBytes(of: &address.sun_path) { $0.copyBytes(from: bytes) }
        address.sun_len = UInt8(MemoryLayout<sockaddr_un>.size)
        return address
    }
}
