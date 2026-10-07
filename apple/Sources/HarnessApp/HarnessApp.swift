import HarnessKit
import SwiftUI

@main
struct HarnessApp: App {
    @State private var controller = AppController()

    init() {
        #if DEBUG
            Snapshots.runIfRequested()
        #endif
    }

    var body: some Scene {
        Window("harness", id: "main") {
            RootView()
                .environment(controller)
                .containerBackground(.clear, for: .window)
                .onAppear { controller.start() }
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1440, height: 900)
        .commands { HarnessCommands(controller: controller) }
    }
}

/// Menu bar commands and their keyboard shortcuts.
struct HarnessCommands: Commands {
    let controller: AppController

    private var shell: Shell? { controller.shell }

    var body: some Commands {
        CommandGroup(replacing: .appSettings) {
            Button("Settings…") { shell?.show(.settings) }
                .keyboardShortcut(",")
        }
        CommandGroup(replacing: .newItem) {
            Button("New Chat") { shell?.newChat() }
                .keyboardShortcut("n")
                .disabled(shell?.project == nil)
        }
        CommandGroup(replacing: .saveItem) {
            Button("Close Pane") { shell?.closeFocused() }
                .keyboardShortcut("w")
        }
        CommandGroup(after: .newItem) {
            Button("Search Chats and Commands") { shell?.toggle(.palette) }
                .keyboardShortcut("k")
            Button("New Terminal") { shell?.newTerminal() }
                .keyboardShortcut("t", modifiers: [.command, .shift])
                .disabled(shell?.project == nil)
            Button("New Browser") { shell?.newBrowser() }
                .keyboardShortcut("b", modifiers: [.command, .shift])
                .disabled(shell?.project == nil)
            Button("Open Project in VS Code") { shell?.openProject(in: .vscode) }
                .keyboardShortcut("o", modifiers: [.command, .shift])
                .disabled(shell?.project == nil)
            Divider()
            Button("Send Message") { shell?.sendFocused() }
                .keyboardShortcut(.return)
            Button("Show Usage") { shell?.toggle(.usage) }
            Button("Connectors") { shell?.show(.connectors) }
        }
        CommandGroup(before: .sidebar) {
            Button("Toggle Sidebar") { shell?.update { $0.leftCollapsed.toggle() } }
                .keyboardShortcut("s", modifiers: [.command, .control])
            Button("Toggle Activity Panel") { shell?.update { $0.rightCollapsed.toggle() } }
                .keyboardShortcut("a", modifiers: [.command, .control])
            Button("Workspace") { shell?.update { $0.view = .workspace } }
                .keyboardShortcut("1", modifiers: [.command, .option])
            Button("Board") { shell?.update { $0.view = .board } }
                .keyboardShortcut("2", modifiers: [.command, .option])
            Divider()
        }
        CommandMenu("Projects") {
            Button("Previous Project") { shell?.app.selectProject(offset: -1) }
                .keyboardShortcut("[", modifiers: [.command, .shift])
            Button("Next Project") { shell?.app.selectProject(offset: 1) }
                .keyboardShortcut("]", modifiers: [.command, .shift])
            Divider()
            ForEach(1..<10) { number in
                Button(projectTitle(number)) { shell?.app.selectProject(at: number - 1) }
                    .keyboardShortcut(KeyEquivalent(Character("\(number)")))
            }
        }
    }

    private func projectTitle(_ number: Int) -> String {
        let open = shell?.app.openProjects ?? []
        if number == 9, let last = open.last, open.count > 9 {
            return last
        }
        return open.indices.contains(number - 1) ? open[number - 1] : "Project \(number)"
    }
}
