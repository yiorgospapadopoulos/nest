// Nest Computer: the helper app that reads and drives Mac apps for Nest's computer use
// (B150). The daemon starts it with `open -g -a "Nest Computer.app" --args --socket <path>
// --controller <pid>` so macOS gives it its own Accessibility and Screen Recording entries.
import AppKit
import NestComputerCore
import os

let log = Logger(subsystem: "local.nest.computer", category: "main")

let options: LaunchOptions
do {
    options = try LaunchOptions(arguments: Array(CommandLine.arguments.dropFirst()))
} catch {
    log.error("bad launch arguments: \(error.message, privacy: .public)")
    exit(64)
}
// One helper per socket: a second launch leaves the live one serving.
if Server.isLive(path: options.socket) {
    log.notice("another helper serves \(options.socket, privacy: .public)")
    exit(0)
}
umask(0o077)
signal(SIGPIPE, SIG_IGN)
AX.limitWaits(seconds: 3)

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let lifetime = Lifetime(options: options)
do {
    try lifetime.start()
} catch {
    log.error("could not start: \(error.message, privacy: .public)")
    exit(1)
}
app.run()
