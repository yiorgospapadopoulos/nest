/// The helper's launch arguments: `--socket <path> --controller <pid>`.
public struct LaunchOptions: Sendable, Equatable {
    /// A Unix socket path must fit `sockaddr_un.sun_path` (104 bytes) with its final NUL.
    public static let maxSocketPathBytes = 103

    public let socket: String
    public let controller: Int32

    /// Reads the arguments after the executable's own path. Unknown arguments are ignored,
    /// as macOS may add its own (`-psn_...`).
    public init(arguments: [String]) throws(HelperError) {
        var socket: String?
        var controller: Int32?
        var index = 0
        while index < arguments.count {
            let next = index + 1 < arguments.count ? arguments[index + 1] : nil
            switch arguments[index] {
            case "--socket":
                socket = next
                index += 1
            case "--controller":
                controller = next.flatMap { Int32($0) }
                index += 1
            default:
                break
            }
            index += 1
        }
        guard let socket, socket.hasPrefix("/") else {
            throw HelperError(.badRequest, "--socket needs an absolute path")
        }
        guard socket.utf8.count <= Self.maxSocketPathBytes else {
            throw HelperError(
                .badRequest, "the socket path is longer than \(Self.maxSocketPathBytes) bytes")
        }
        guard let controller, controller > 1 else {
            throw HelperError(.badRequest, "--controller needs the controller's process id")
        }
        self.socket = socket
        self.controller = controller
    }
}
