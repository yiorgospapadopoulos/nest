import Foundation

/// Where a terminal for a chat opens: its folder, or a folder that is gone (a merged or
/// rejected chat's removed worktree), where no shell may start.
public enum TerminalFolder: Sendable, Equatable {
    case ready(String)
    case gone(String)

    public static let goneMessage = "This chat's folder no longer exists, so nothing was run there."

    /// The path exists and is a folder.
    public static func exists(_ path: String) -> Bool {
        var isFolder: ObjCBool = false
        return FileManager.default.fileExists(atPath: path, isDirectory: &isFolder)
            && isFolder.boolValue
    }
}

/// Where the bottom bar's Terminal button opens a shell (B60).
public enum TerminalButtonTarget: Sendable, Equatable {
    /// The focused chat's folder: the terminal pane there, or a new one.
    case chat(String)
    /// No chat is focused: the project's terminal pane, or a new one in the project folder.
    case project(String)
    /// The focused chat's folder is gone (`TerminalFolder.goneMessage`).
    case gone(String)
}

extension AppModel {
    /// The folder a pane's chat works in: its worktree, its folder in place (else its
    /// project's), or a Claude Code chat's folder. Nil for a new chat and tool panes.
    public func folder(ofPane pane: String) -> String? {
        if let chat = ClaudeChat.chatID(ofPane: pane).flatMap(claudeChats.chat) {
            return chat.cwd
        }
        guard let session = sessions.session(pane) else { return nil }
        return session.folder ?? app.repo(session.repo)?.path
    }

    /// Where Run in terminal runs a command from a pane: the chat's folder, else the
    /// project's. Nil without either.
    public func terminalFolder(
        forPane pane: String?, project: String?,
        exists: (String) -> Bool = TerminalFolder.exists
    ) -> TerminalFolder? {
        guard let path = pane.flatMap(folder(ofPane:)) ?? project.flatMap(app.repo)?.path
        else { return nil }
        return exists(path) ? .ready(path) : .gone(path)
    }

    /// Where the Terminal button opens a shell: the folder of the focused chat pane (its
    /// worktree when it has one), else the project's folder. Nil without either.
    public func terminalButtonTarget(
        focusedPane pane: String?, project: String?,
        exists: (String) -> Bool = TerminalFolder.exists
    ) -> TerminalButtonTarget? {
        if let folder = pane.flatMap(folder(ofPane:)) {
            return exists(folder) ? .chat(folder) : .gone(folder)
        }
        return project.flatMap(app.repo).map { .project($0.path) }
    }
}
