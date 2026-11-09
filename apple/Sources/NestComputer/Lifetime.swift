import Darwin
import Foundation
import NestComputerCore

/// The helper lives while its controller does: it serves the socket, quits when the
/// controller's process ends or on SIGTERM, and removes the socket on the way out.
@MainActor
final class Lifetime {
    private let server: Server
    private let controller: pid_t
    private var sources: [any DispatchSourceProtocol] = []

    init(options: LaunchOptions) {
        server = Server(path: options.socket, controller: options.controller)
        controller = options.controller
    }

    func start() throws(HelperError) {
        try server.start()
        let exit = DispatchSource.makeProcessSource(
            identifier: controller, eventMask: .exit, queue: .main)
        exit.setEventHandler { [weak self] in MainActor.assumeIsolated { self?.quit() } }
        exit.resume()
        signal(SIGTERM, SIG_IGN)
        let term = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
        term.setEventHandler { [weak self] in MainActor.assumeIsolated { self?.quit() } }
        term.resume()
        sources = [exit, term]
        // The controller may have ended before the watch began.
        if kill(controller, 0) != 0, errno == ESRCH { quit() }
    }

    func quit() -> Never {
        server.stop()
        exit(0)
    }
}
