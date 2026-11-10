import Foundation
import NestComputerCore

/// Asks launchd about Nest's daemon service and throws unless `controller` is its running
/// process (B159 R04).
func checkController(_ controller: Int32) throws(HelperError) {
    try DaemonJob.check(controller: controller, launchctlPrint: launchctlPrint())
}

/// What `launchctl print` says about the service, or nil when launchctl fails.
private func launchctlPrint() -> String? {
    let process = Process()
    process.executableURL = URL(filePath: DaemonJob.launchctl)
    process.arguments = DaemonJob.printArguments(uid: getuid())
    let output = Pipe()
    process.standardOutput = output
    process.standardError = FileHandle.nullDevice
    do { try process.run() } catch { return nil }
    let data = output.fileHandleForReading.readDataToEndOfFile()
    process.waitUntilExit()
    guard process.terminationStatus == 0 else { return nil }
    return String(decoding: data, as: UTF8.self)
}
