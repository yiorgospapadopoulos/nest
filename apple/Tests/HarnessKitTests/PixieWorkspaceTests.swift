import CoreGraphics
import Foundation
import Testing

@testable import HarnessKit

private let workspace = CGSize(width: 1000, height: 600)

/// A pixie with this id whose ongoing chat is `chat`.
private func pixie(_ id: String, chat: String?) -> Pixie {
    var pixie = Fixture.decode(Pixie.self, "pixie")
    pixie.id = id
    pixie.chatSessionID = chat
    return pixie
}

/// The Pixies tab's workspace (B37): pixies open as panes like chats.
@MainActor
@Suite struct PixieWorkspaceTests {
    let api = FakeAPI()
    let memory = MemoryStore()

    func app() -> AppStore {
        AppStore(api: api, store: memory)
    }

    @Test func pixiePanesOpenSplitAndCloseLikeChats() {
        let app = app()
        #expect(app.pixieState.layout.root == nil)
        app.updatePixies { $0.openChat("reviewer", in: workspace) }
        app.updatePixies { $0.dropChat("watcher", onto: "reviewer", side: .bottom) }
        let layout = app.pixieState.layout
        #expect(layout.leaves == ["reviewer", "watcher"])
        #expect(layout.focused == "watcher")
        #expect(app.pixieState.selectedChat == "watcher")
        guard case .split(_, let direction, _, _, _) = layout.root else {
            Issue.record("expected a split")
            return
        }
        #expect(direction == .column)
        app.updatePixies { $0.openChat("reviewer", in: workspace) }
        #expect(app.pixieState.layout.leaves == ["reviewer", "watcher"])
        #expect(app.pixieState.selectedChat == "reviewer")
        app.updatePixies { $0.closePane("reviewer") }
        #expect(app.pixieState.layout.leaves == ["watcher"])
        #expect(app.pixieState.selectedChat == "watcher")
    }

    @Test func thePixieWorkspaceIsKeptApartFromTheProjects() async throws {
        let app = app()
        try await app.loadRepos()
        app.update("todo-ui") { $0.openChat("s1", in: workspace) }
        app.updatePixies { $0.openChat("reviewer", in: workspace) }
        #expect(app.openPanes == ["s1"])
        #expect(app.state(of: "todo-ui").layout.leaves == ["s1"])
        app.forgetChat("reviewer")
        try await app.loadRepos()
        #expect(app.pixieState.layout.leaves == ["reviewer"])
        #expect(app.projects["pixies"] == nil)
    }

    @Test func openPixiesAreSavedInReadingOrderAndReopen() {
        let app = app()
        app.updatePixies { $0.openChat("reviewer", in: workspace) }
        app.updatePixies { $0.dropChat("watcher", onto: "reviewer", side: .left) }
        #expect(memory.values["pixies.panes"] == "watcher\nreviewer")
        // Resizing and focusing keep the same pixies: nothing new is saved.
        memory.values["pixies.panes"] = "unchanged"
        app.updatePixies { $0.focusPane("reviewer") }
        #expect(memory.values["pixies.panes"] == "unchanged")
        memory.values["pixies.panes"] = "watcher\nreviewer"

        let reopened = AppStore(api: api, store: memory)
        #expect(reopened.pixieState.layout.leaves == ["watcher", "reviewer"])
        #expect(reopened.pixieState.layout.focused == "reviewer")

        app.updatePixies { $0.closePane("watcher") }
        app.updatePixies { $0.closePane("reviewer") }
        #expect(memory.values["pixies.panes"] == nil)
        #expect(AppStore(api: api, store: memory).pixieState.layout.root == nil)
    }

    @Test func panesOfPixiesThatAreGoneClose() {
        let app = app()
        app.updatePixies { $0.openChat("a", in: workspace) }
        app.updatePixies { $0.openChat("b", in: workspace) }
        app.keepPixies(["a", "b", "c"])
        #expect(app.pixieState.layout.leaves == ["a", "b"])
        app.keepPixies(["b"])
        #expect(app.pixieState.layout.leaves == ["b"])
        #expect(app.pixieState.layout.focused == "b")
        #expect(memory.values["pixies.panes"] == "b")
    }

    @Test func openPixieChatsAreTheChatsOfOpenPanes() {
        let app = app()
        let pixies = [
            pixie("a", chat: "chat-a"), pixie("b", chat: nil), pixie("c", chat: "chat-c"),
        ]
        #expect(app.openPixieChats(pixies).isEmpty)
        app.updatePixies { $0.openChat("a", in: workspace) }
        app.updatePixies { $0.openChat("b", in: workspace) }
        app.updatePixies { $0.openChat("gone", in: workspace) }
        #expect(app.openPixieChats(pixies) == ["chat-a"])
    }

    @Test func visiblePixieChatsFollowTheShownPanes() {
        let app = app()
        let pixies = [pixie("a", chat: "chat-a"), pixie("b", chat: "chat-b")]
        app.updatePixies { $0.openChat("a", in: workspace) }
        app.updatePixies { $0.openChat("b", in: workspace) }
        #expect(
            NotificationPolicy.visiblePixieChats(app: app, pixies: pixies, windowFocused: true)
                == ["chat-a", "chat-b"])
        #expect(
            NotificationPolicy.visiblePixieChats(app: app, pixies: pixies, windowFocused: false)
                .isEmpty)
        app.updatePixies { $0.layout.toggleMaximize("a") }
        #expect(
            NotificationPolicy.visiblePixieChats(app: app, pixies: pixies, windowFocused: true)
                == ["chat-a"])
    }
}
