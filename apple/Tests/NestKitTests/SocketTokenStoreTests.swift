import Darwin
import Foundation
import Synchronization
import Testing

@testable import NestKit

@Suite struct SocketTokenStoreTests {
    @Test func asksTheSocketInTheDaemonsDataFolder() throws {
        let asked = Mutex<[String]>([])
        let store = SocketTokenStore(path: "/data/token.sock") { path in
            asked.withLock { $0.append(path) }
            return Data("tok-abc_123\n".utf8)
        }

        #expect(try store.deviceToken() == "tok-abc_123")
        #expect(asked.withLock { $0 } == ["/data/token.sock"])
    }

    @Test func noSocketMeansTheDaemonIsNotRunning() throws {
        let store = SocketTokenStore(path: "p") { _ in nil }
        #expect(try store.deviceToken() == nil)
    }

    @Test func aClosedConnectionWithoutATokenIsAnError() {
        let store = SocketTokenStore(path: "p") { _ in Data() }
        #expect(throws: TokenStoreError.noAnswer) { try store.deviceToken() }
        let blank = SocketTokenStore(path: "p") { _ in Data("\n".utf8) }
        #expect(throws: TokenStoreError.noAnswer) { try blank.deviceToken() }
    }

    /// Only a URL-safe token is used: anything else could change the Authorization header.
    @Test func anAnswerThatIsNotAURLSafeTokenIsAnError() {
        for answer in [Data([0xFF, 0xFE]), Data("tok\r\nX-Other: 1\n".utf8), Data("a b\n".utf8)] {
            let store = SocketTokenStore(path: "p") { _ in answer }
            #expect(throws: TokenStoreError.malformed) { try store.deviceToken() }
        }
    }

    @Test func socketErrorsAreReported() {
        let store = SocketTokenStore(path: "p") { _ in throw TokenStoreError.socket(EACCES) }
        #expect(throws: TokenStoreError.socket(EACCES)) { try store.deviceToken() }
    }

    @Test func defaultsToTheDaemonsDataFolder() {
        let home = URL(fileURLWithPath: "/Users/someone")
        #expect(
            SocketTokenStore.path(home: home)
                == "/Users/someone/Library/Application Support/nest/token.sock")
        #expect(
            SocketTokenStore().path
                == SocketTokenStore.path(home: FileManager.default.homeDirectoryForCurrentUser))
    }

    @Test func errorsReadAsSentences() {
        #expect(
            TokenStoreError.socket(EACCES).message
                == "could not ask the Nest daemon for this Mac's device token"
                + " (Permission denied)")
        #expect(
            TokenStoreError.noAnswer.message
                == "the Nest daemon did not give this Mac's device token")
        #expect(
            TokenStoreError.malformed.message
                == "the Nest daemon's answer was not a device token")
        #expect(TokenStoreError.noAnswer.localizedDescription == TokenStoreError.noAnswer.message)
    }

    /// The real socket read, for a home where no daemon runs; never the user's own daemon.
    @Test func aHomeWithoutARunningDaemonGivesNoToken() throws {
        let home = URL(fileURLWithPath: TestSocketServer.makeFolder())
        defer { rmdir(home.path) }
        #expect(try SocketTokenStore(home: home).deviceToken() == nil)
    }
}

/// The real socket reads, against a socket served in the test.
@Suite struct UnixSocketTests {
    @Test func readsWhatTheServerWritesUntilItCloses() throws {
        let server = try TestSocketServer(reply: Array("tok-1\n".utf8))
        defer { server.remove() }
        #expect(try UnixSocket.read(path: server.path) == Data("tok-1\n".utf8))
    }

    @Test func aMissingSocketReadsAsNothing() throws {
        let folder = TestSocketServer.makeFolder()
        defer { rmdir(folder) }
        #expect(try UnixSocket.read(path: folder + "/token.sock") == nil)
    }

    /// A daemon that was killed leaves its socket file with nobody listening.
    @Test func aSocketNobodyListensOnReadsAsNothing() throws {
        let server = try TestSocketServer(listening: false)
        defer { server.remove() }
        #expect(try UnixSocket.read(path: server.path) == nil)
    }

    @Test func otherConnectFailuresThrow() {
        // A path through something that is not a folder.
        #expect(throws: TokenStoreError.socket(ENOTDIR)) {
            try UnixSocket.read(path: "/dev/null/token.sock")
        }
    }

    @Test func aPathTooLongForASocketThrows() {
        let path = "/tmp/" + String(repeating: "x", count: 200)
        #expect(throws: TokenStoreError.socket(ENAMETOOLONG)) {
            try UnixSocket.read(path: path)
        }
    }

    @Test func aServerThatNeverAnswersTimesOut() throws {
        let server = try TestSocketServer(reply: [], hold: 0.5)
        defer { server.remove() }
        #expect(throws: TokenStoreError.socket(EAGAIN)) {
            try UnixSocket.read(path: server.path, timeout: 0.05)
        }
    }

    @Test func anAnswerLongerThanATokenIsRefused() throws {
        let server = try TestSocketServer(reply: Array(repeating: UInt8(ascii: "a"), count: 5000))
        defer { server.remove() }
        #expect(throws: TokenStoreError.malformed) { try UnixSocket.read(path: server.path) }
    }
}

/// A Unix socket in a short temporary folder (socket paths are limited to 104 bytes) that
/// answers its first connection with `reply`, then closes it.
struct TestSocketServer: Sendable {
    let folder: String
    let path: String
    private let descriptor: Int32

    /// `hold` keeps the connection open that long after the reply; a server that is not
    /// `listening` leaves only the socket file, as a killed daemon does.
    init(reply: [UInt8] = [], hold: TimeInterval = 0, listening: Bool = true) throws {
        folder = Self.makeFolder()
        path = folder + "/token.sock"
        var address = try UnixSocket.address(path)
        let server = socket(AF_UNIX, SOCK_STREAM, 0)
        let bound = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(server, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        try #require(bound == 0)
        guard listening else {
            close(server)
            descriptor = -1
            return
        }
        try #require(listen(server, 1) == 0)
        descriptor = server
        DispatchQueue.global().async {
            let client = accept(server, nil, nil)
            guard client >= 0 else { return }
            reply.withUnsafeBytes { _ = write(client, $0.baseAddress, $0.count) }
            Thread.sleep(forTimeInterval: hold)
            close(client)
        }
    }

    static func makeFolder() -> String {
        var template = Array("/tmp/hx-XXXXXX".utf8CString)
        return template.withUnsafeMutableBufferPointer { String(cString: mkdtemp($0.baseAddress!)) }
    }

    func remove() {
        if descriptor >= 0 {
            close(descriptor)
        }
        unlink(path)
        rmdir(folder)
    }
}
