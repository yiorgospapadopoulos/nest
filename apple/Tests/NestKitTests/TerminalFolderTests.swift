import Foundation
import Testing

@testable import NestKit

/// Where Run in terminal and Terminal here open a shell for a pane's chat.
@MainActor
@Suite struct TerminalFolderTests {
    let api = FakeAPI()
    let model: AppModel

    init() async throws {
        var worktree = Fixture.session("wt")
        worktree.worktreePath = "/w/wt"
        worktree.cwd = "/w/wt"
        var inPlace = Fixture.session("ip", repo: "map-viewer")
        inPlace.mode = .inPlace
        inPlace.worktreePath = nil
        inPlace.cwd = nil
        let starting = Fixture.session("new")
        api.set { $0.sessions = [worktree, inPlace, starting] }
        model = AppModel(api: api, events: ManualEventSource(), preferences: MemoryStore())
        try await model.app.loadRepos()
        try await model.sessions.load()
        try await model.claudeChats.load()
        model.sessions.apply(
            Fixture.event(
                EventType.sessionWorkspace, #"{"path": "/w/new", "branch": "b", "base_ref": "c"}"#,
                session: "new"))
    }

    @Test func aPanesFolderIsItsChatsFolder() throws {
        #expect(model.folder(ofPane: "wt") == "/w/wt")
        // A chat working in place uses its project's folder.
        #expect(model.folder(ofPane: "ip") == "/Users/example/projects/map-viewer")
        // A worktree learned while running (audit BUG-55).
        #expect(model.folder(ofPane: "new") == "/w/new")
        let chat = try #require(model.claudeChats.chats(in: "todo-ui").first)
        #expect(model.folder(ofPane: chat.paneID) == chat.cwd)
        #expect(model.folder(ofPane: "draft-1") == nil)
    }

    /// A merged or rejected chat's worktree is gone; nothing runs in a fallback folder
    /// such as the home folder (audit BUG-56).
    @Test func aFolderThatIsGoneIsSaidSo() {
        let existing: Set<String> = ["/w/wt", "/Users/example/projects/todo-ui"]
        func place(_ pane: String?, _ project: String?) -> TerminalFolder? {
            model.terminalFolder(forPane: pane, project: project) { existing.contains($0) }
        }
        #expect(place("wt", "todo-ui") == .ready("/w/wt"))
        #expect(place("new", "todo-ui") == .gone("/w/new"))
        // A new chat's command, or none, runs in the project folder.
        #expect(place("draft-1", "todo-ui") == .ready("/Users/example/projects/todo-ui"))
        #expect(place(nil, "todo-ui") == .ready("/Users/example/projects/todo-ui"))
        #expect(place(nil, nil) == nil)
        // By default the disk tells.
        #expect(
            model.terminalFolder(forPane: nil, project: "todo-ui")
                == .gone("/Users/example/projects/todo-ui"))
        #expect(
            TerminalFolder.goneMessage
                == "This chat's folder no longer exists, so nothing was run there.")
    }

    /// The bottom bar's Terminal button opens a shell where the focused chat works (B60);
    /// without a focused chat it opens the project's terminal as before.
    @Test func theTerminalButtonFollowsTheFocusedChat() throws {
        let chat = try #require(model.claudeChats.chats(in: "todo-ui").first)
        let existing: Set<String> = ["/w/wt", chat.cwd]
        func target(_ pane: String?, _ project: String?) -> TerminalButtonTarget? {
            model.terminalButtonTarget(focusedPane: pane, project: project) {
                existing.contains($0)
            }
        }
        let project = "/Users/example/projects/todo-ui"
        #expect(target("wt", "todo-ui") == .chat("/w/wt"))
        #expect(target(chat.paneID, "todo-ui") == .chat(chat.cwd))
        // A merged chat's worktree is gone: nothing opens there.
        #expect(target("new", "todo-ui") == .gone("/w/new"))
        // A new chat, a tool pane or no focus at all: the project's terminal, which
        // opens even before the disk is asked, as the button always did.
        #expect(target("draft-1", "todo-ui") == .project(project))
        #expect(target("terminal-1", "todo-ui") == .project(project))
        #expect(target(nil, "todo-ui") == .project(project))
        #expect(target("wt", nil) == .chat("/w/wt"))
        #expect(target(nil, nil) == nil)
        #expect(target(nil, "no-such-project") == nil)
        // By default the disk tells.
        #expect(
            model.terminalButtonTarget(focusedPane: "wt", project: "todo-ui") == .gone("/w/wt"))
    }

    @Test func onlyAnExistingFolderCounts() throws {
        let file = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        FileManager.default.createFile(atPath: file.path, contents: Data())
        defer { try? FileManager.default.removeItem(at: file) }
        #expect(TerminalFolder.exists(FileManager.default.temporaryDirectory.path))
        #expect(!TerminalFolder.exists(file.path))
        #expect(!TerminalFolder.exists("/no/such/folder"))
    }
}
