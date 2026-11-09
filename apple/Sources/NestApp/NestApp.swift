import NestKit
import SwiftUI

@main
struct NestApp: App {
    @State private var controller: AppController

    init() {
        // B43: the installed app's first launch takes over the settings and backgrounds of
        // the app from before the rename, before anything reads them. Builds run from the
        // checkout have another bundle id and leave them alone.
        if Bundle.main.bundleIdentifier == LegacyAppData.bundleID {
            LegacyAppData().run()
        }
        _controller = State(initialValue: AppController())
        #if DEBUG
            Snapshots.runIfRequested()
        #endif
    }

    /// The main window's scene id.
    static let mainWindowID = "main"

    var body: some Scene {
        Window("Nest", id: Self.mainWindowID) {
            RootView()
                .environment(controller)
                .containerBackground(.clear, for: .window)
                .onAppear { controller.start() }
                .onOpenURL { controller.open($0) }
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1440, height: 900)
        .commands { NestCommands(controller: controller) }
    }
}

/// Menu bar commands, with the keyboard shortcuts Settings > Keyboard shortcuts sets (B81).
struct NestCommands: Commands {
    let controller: AppController

    private var shell: Shell? { controller.shell }

    /// A command that shows something in the window leaves Settings for it.
    private func inWindow(_ action: (Shell) -> Void) {
        // The guide is the whole window: nothing acts behind it.
        guard let shell, shell.guide == nil else { return }
        shell.closeSettings()
        action(shell)
    }

    var body: some Commands {
        CommandGroup(replacing: .appSettings) {
            Button("Settings…") { shell?.openSettings() }
                .shortcut(.settings, shell)
        }
        CommandGroup(replacing: .newItem) {
            Button("New Chat") { inWindow { $0.newChat() } }
                .shortcut(.newChat, shell)
                .disabled(shell?.project == nil)
        }
        CommandGroup(replacing: .saveItem) {
            Button("Close Pane") { shell?.closeFocused() }
                .shortcut(.closePane, shell)
        }
        CommandGroup(after: .newItem) {
            Button("Search Chats and Commands") { inWindow { $0.toggle(.palette) } }
                .shortcut(.palette, shell)
            Button("New Terminal") { inWindow { $0.newTerminal() } }
                .shortcut(.newTerminal, shell)
                .disabled(shell?.project == nil || shell?.isRemote == true)
            Button("New Browser") { inWindow { $0.newBrowser() } }
                .shortcut(.newBrowser, shell)
                .disabled(shell?.project == nil)
            let editor = shell?.app.editors.defaultEditor
            Button("Open Project in \(editor?.name ?? "Editor")") {
                shell?.openProject(in: .defaultEditor)
            }
            .shortcut(.openInEditor, shell)
            .disabled(shell?.project == nil || shell?.isRemote == true || editor == nil)
            Divider()
            Button("Send Message") { shell?.sendFocused() }
                .shortcut(.sendMessage, shell)
            Button("Show Usage") { shell?.toggle(.usage) }
            Button("Connectors") { shell?.openConnectors() }
        }
        CommandGroup(before: .sidebar) {
            Button("Toggle Sidebar") { shell?.update { $0.leftCollapsed.toggle() } }
                .shortcut(.toggleSidebar, shell)
            Button("Toggle Activity Panel") { shell?.update { $0.rightCollapsed.toggle() } }
                .shortcut(.toggleActivity, shell)
            Button("Workspace") { inWindow { $0.showView(.workspace) } }
                .shortcut(.workspace, shell)
            Button("Board") { inWindow { $0.showView(.board) } }
                .shortcut(.board, shell)
            Button("Artifacts") { inWindow { $0.showView(.artifacts) } }
                .shortcut(.artifacts, shell)
            Divider()
            Button("Focus Sidebar") { inWindow { $0.focusSidebar() } }
                .shortcut(.focusSidebar, shell)
            Button("Next Pane") { inWindow { $0.focusPane(by: 1) } }
                .shortcut(.nextPane, shell)
            Button("Previous Pane") { inWindow { $0.focusPane(by: -1) } }
                .shortcut(.previousPane, shell)
            Divider()
        }
        CommandMenu("Projects") {
            Button("Previous Project") { inWindow { $0.selectProject(offset: -1) } }
                .shortcut(.previousProject, shell)
            Button("Next Project") { inWindow { $0.selectProject(offset: 1) } }
                .shortcut(.nextProject, shell)
            Divider()
            Button("Pixies") { inWindow { $0.openPixies() } }
                .shortcut(.pixies, shell)
            ForEach(1..<10) { number in
                Button(projectTitle(number)) { inWindow { $0.selectProject(at: number - 1) } }
                    .shortcut(.project, shell, digit: number)
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

extension View {
    /// The command's shortcut as the user set it, else its default; Project 1 to 9 takes
    /// its digit.
    func shortcut(_ action: ShortcutAction, _ shell: Shell?, digit: Int? = nil) -> some View {
        let shortcut = shell?.shortcuts.shortcut(for: action) ?? action.defaultShortcut
        return keyboardShortcut(shortcut.keyboardShortcut(digit: digit))
    }
}

extension Shortcut {
    /// SwiftUI's form of the shortcut.
    func keyboardShortcut(digit: Int? = nil) -> KeyboardShortcut {
        let equivalent: KeyEquivalent =
            switch key {
            case "return": .return
            case "escape": .escape
            case "tab": .tab
            case "delete": .delete
            case "space": .space
            case "up": .upArrow
            case "down": .downArrow
            case "left": .leftArrow
            case "right": .rightArrow
            case Shortcut.digits: KeyEquivalent(Character("\(digit ?? 1)"))
            default: KeyEquivalent(key.first ?? " ")
            }
        var flags: EventModifiers = []
        if modifiers.contains(.command) { flags.insert(.command) }
        if modifiers.contains(.shift) { flags.insert(.shift) }
        if modifiers.contains(.option) { flags.insert(.option) }
        if modifiers.contains(.control) { flags.insert(.control) }
        return KeyboardShortcut(equivalent, modifiers: flags)
    }
}
