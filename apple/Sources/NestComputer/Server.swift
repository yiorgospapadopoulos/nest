import Darwin
import Foundation
import NestComputerCore
import os

/// The Unix socket the daemon talks to. Only the controller (the daemon's pid, from the
/// launch arguments) may connect: every other peer is closed at once. Requests are JSON
/// lines, answered one at a time in arrival order.
@MainActor
final class Server {
    /// A line longer than this without a newline closes the connection.
    private static let maxLineBytes = 4 << 20

    private let path: String
    private let controller: pid_t
    private let dispatcher = Dispatcher()
    private let log = Logger(subsystem: "local.nest.computer", category: "server")
    private var listener: Int32 = -1
    private var acceptSource: (any DispatchSourceRead)?
    private var connections: [Int: Connection] = [:]
    private var nextConnection = 1
    private let requests: AsyncStream<(connection: Int, line: Data)>.Continuation

    init(path: String, controller: pid_t) {
        self.path = path
        self.controller = controller
        let (stream, continuation) = AsyncStream<(connection: Int, line: Data)>.makeStream()
        requests = continuation
        Task { [weak self] in
            for await (connection, line) in stream {
                guard let self else { return }
                let reply = await dispatcher.reply(to: line)
                connections[connection]?.send(reply.line())
            }
        }
    }

    /// Whether another helper is serving the path now.
    static func isLive(path: String) -> Bool {
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { return false }
        defer { close(fd) }
        return withAddress(path) { connect(fd, $0, $1) } == 0
    }

    func start() throws(HelperError) {
        var status = stat()
        if lstat(path, &status) == 0 {
            guard status.st_mode & S_IFMT == S_IFSOCK else {
                throw HelperError(.failed, "\(path) exists and is not a socket")
            }
            unlink(path)
        }
        listener = socket(AF_UNIX, SOCK_STREAM, 0)
        guard listener >= 0 else { throw HelperError(.failed, "socket: \(errnoText())") }
        guard withAddress(path, { bind(listener, $0, $1) }) == 0 else {
            throw HelperError(.failed, "bind \(path): \(errnoText())")
        }
        chmod(path, 0o600)
        guard listen(listener, 4) == 0 else { throw HelperError(.failed, "listen: \(errnoText())") }
        let source = DispatchSource.makeReadSource(fileDescriptor: listener, queue: .main)
        source.setEventHandler { [weak self] in
            MainActor.assumeIsolated { self?.accept() }
        }
        source.resume()
        acceptSource = source
    }

    func stop() {
        acceptSource?.cancel()
        for connection in connections.values { connection.close() }
        connections.removeAll()
        if listener >= 0 {
            close(listener)
            unlink(path)
            listener = -1
        }
    }

    private func accept() {
        let fd = Darwin.accept(listener, nil, nil)
        guard fd >= 0 else { return }
        var peer: pid_t = 0
        var length = socklen_t(MemoryLayout<pid_t>.size)
        guard getsockopt(fd, SOL_LOCAL, LOCAL_PEERPID, &peer, &length) == 0, peer == controller
        else {
            log.notice("refused a connection from pid \(peer)")
            close(fd)
            return
        }
        var on: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &on, socklen_t(MemoryLayout<Int32>.size))
        let id = nextConnection
        nextConnection += 1
        connections[id] = Connection(fd: fd, maxLineBytes: Self.maxLineBytes) {
            [weak self] event in
            switch event {
            case .line(let line): self?.requests.yield((id, line))
            case .tooLong:
                let error = HelperError(.badRequest, "the request line is too long")
                self?.connections[id]?.send(Reply.failure(id: nil, error: error).line())
                self?.drop(id)
            case .closed: self?.drop(id)
            }
        }
    }

    private func drop(_ id: Int) {
        connections.removeValue(forKey: id)?.close()
    }
}

/// One accepted connection: reads lines as they come and writes replies.
@MainActor
private final class Connection {
    enum Event {
        case line(Data)
        case tooLong
        case closed
    }

    let fd: Int32
    private let maxLineBytes: Int
    private let onEvent: @MainActor (Event) -> Void
    private let source: any DispatchSourceRead
    private var buffer = Data()

    init(fd: Int32, maxLineBytes: Int, onEvent: @escaping @MainActor (Event) -> Void) {
        self.fd = fd
        self.maxLineBytes = maxLineBytes
        self.onEvent = onEvent
        source = DispatchSource.makeReadSource(fileDescriptor: fd, queue: .main)
        source.setEventHandler { [weak self] in
            MainActor.assumeIsolated { self?.readable() }
        }
        source.setCancelHandler { Darwin.close(fd) }
        source.resume()
    }

    private func readable() {
        var chunk = [UInt8](repeating: 0, count: 65_536)
        let count = read(fd, &chunk, chunk.count)
        if count < 0, errno == EINTR || errno == EAGAIN { return }
        guard count > 0 else { return onEvent(.closed) }
        buffer.append(contentsOf: chunk[0..<count])
        while let end = buffer.firstIndex(of: 0x0A) {
            let line = buffer[buffer.startIndex..<end]
            buffer.removeSubrange(buffer.startIndex...end)
            if !line.allSatisfy({ $0 == 0x20 || $0 == 0x0D }) { onEvent(.line(Data(line))) }
        }
        if buffer.count > maxLineBytes { onEvent(.tooLong) }
    }

    /// Writes all of `data`; the socket blocks while the daemon is behind.
    func send(_ data: Data) {
        data.withUnsafeBytes { raw in
            guard let base = raw.baseAddress else { return }
            var offset = 0
            while offset < raw.count {
                let written = write(fd, base + offset, raw.count - offset)
                if written < 0 {
                    if errno == EINTR { continue }
                    return
                }
                offset += written
            }
        }
    }

    /// Closes the socket once the read source has stopped.
    func close() {
        source.cancel()
    }
}

/// Calls `body` with `path` as a socket address.
private func withAddress(_ path: String, _ body: (UnsafePointer<sockaddr>, socklen_t) -> Int32)
    -> Int32
{
    var address = sockaddr_un()
    address.sun_family = sa_family_t(AF_UNIX)
    let size = MemoryLayout<sockaddr_un>.size
    address.sun_len = UInt8(size)
    let bytes = Array(path.utf8.prefix(LaunchOptions.maxSocketPathBytes))
    withUnsafeMutableBytes(of: &address.sun_path) { $0.copyBytes(from: bytes) }
    return withUnsafePointer(to: &address) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { body($0, socklen_t(size)) }
    }
}

private func errnoText() -> String {
    String(cString: strerror(errno))
}
