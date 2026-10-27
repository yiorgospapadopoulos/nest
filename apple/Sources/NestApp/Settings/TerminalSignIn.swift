import AppKit
import Foundation

/// Opens Terminal on this Mac running an engine's own login command (B107), through a
/// `.command` file in the app's temporary folder, which removes itself when it runs. This
/// needs no permission to control Terminal.
enum TerminalSignIn {
    enum Failure: LocalizedError {
        case noTerminal

        var errorDescription: String? { "Terminal was not found" }
    }

    @MainActor
    static func run(_ command: String) async throws {
        let file = FileManager.default.temporaryDirectory
            .appending(path: "nest-sign-in-\(UUID().uuidString).command")
        // A login shell, so the command finds what the user's PATH has.
        let script = "#!/bin/zsh -l\nrm -f \"$0\"\n\(command)\n"
        try Data(script.utf8).write(to: file, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: file.path)
        guard
            let terminal = NSWorkspace.shared.urlForApplication(
                withBundleIdentifier: "com.apple.Terminal")
        else { throw Failure.noTerminal }
        try await NSWorkspace.shared.open(
            [file], withApplicationAt: terminal, configuration: NSWorkspace.OpenConfiguration())
    }
}
