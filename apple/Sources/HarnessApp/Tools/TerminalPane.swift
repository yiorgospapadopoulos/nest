import AppKit
import HarnessKit
import Observation
import SwiftTerm
import SwiftUI

/// One terminal pane's shell: the user's login shell in a pseudo-terminal, started in the
/// pane's folder. Commands from a chat are typed into it.
@MainActor @Observable
final class TerminalSession {
    /// Snapshots draw sample output instead of starting shells.
    static var startsShells = true

    let folder: String
    @ObservationIgnored let view = HarnessTerminalView(
        frame: CGRect(x: 0, y: 0, width: 640, height: 400))
    /// The shell exited; the pane offers to start a new one.
    private(set) var exited = false
    @ObservationIgnored private var relay: ProcessRelay?

    init(folder: String) {
        self.folder = folder
        let relay = ProcessRelay { [weak self] in self?.exited = true }
        self.relay = relay
        view.processDelegate = relay
        start()
    }

    /// Starts the login shell in the folder, or the home folder when it is gone (such as
    /// a merged chat's worktree).
    func start() {
        exited = false
        guard Self.startsShells else { return }
        var isFolder: ObjCBool = false
        let exists = FileManager.default.fileExists(atPath: folder, isDirectory: &isFolder)
        view.startProcess(
            executable: Self.loginShell, args: ["-l"], environment: Self.environment,
            currentDirectory: exists && isFolder.boolValue ? folder : NSHomeDirectory())
    }

    /// Types the command and Return; the shell reads it once its prompt is ready.
    func run(_ command: String) {
        if exited {
            view.feed(text: "\r\n")
            start()
        }
        view.send(txt: TerminalInput.line(for: command))
    }

    func end() {
        if view.process?.running == true {
            view.terminate()
        }
    }

    /// `$SHELL`, else the account's shell, else zsh.
    static var loginShell: String {
        if let shell = ProcessInfo.processInfo.environment["SHELL"], !shell.isEmpty {
            return shell
        }
        if let entry = getpwuid(getuid()), let shell = entry.pointee.pw_shell {
            return String(cString: shell)
        }
        return "/bin/zsh"
    }

    /// SwiftTerm's terminal variables plus the app's PATH and SHELL; the login shell's
    /// profile does the rest.
    static var environment: [String] {
        let current = ProcessInfo.processInfo.environment
        var variables = Terminal.getEnvironmentVariables(termName: "xterm-256color")
        variables.append("SHELL=\(loginShell)")
        variables.append("TERM_PROGRAM=harness")
        if let path = current["PATH"] {
            variables.append("PATH=\(path)")
        }
        return variables
    }
}

/// Hears the shell exit; the terminal view's delegate is held weakly. SwiftTerm calls it
/// on the main queue.
@MainActor
private final class ProcessRelay: @preconcurrency LocalProcessTerminalViewDelegate {
    let exited: () -> Void

    init(exited: @escaping () -> Void) {
        self.exited = exited
    }

    func sizeChanged(source: LocalProcessTerminalView, newCols: Int, newRows: Int) {}
    func setTerminalTitle(source: LocalProcessTerminalView, title: String) {}
    func hostCurrentDirectoryUpdate(source: TerminalView, directory: String?) {}

    func processTerminated(source: TerminalView, exitCode: Int32?) {
        exited()
    }
}

/// The terminal in the theme's colors and the app's mono font, following light and dark.
final class HarnessTerminalView: LocalProcessTerminalView {
    override init(frame: CGRect) {
        super.init(frame: frame)
        font = NSFont.monospacedSystemFont(ofSize: 12, weight: .regular)
        optionAsMetaKey = false
        applyTheme()
    }

    required init?(coder: NSCoder) {
        fatalError("not used from a nib")
    }

    override func viewDidChangeEffectiveAppearance() {
        super.viewDidChangeEffectiveAppearance()
        applyTheme()
    }

    private func applyTheme() {
        let dark = effectiveAppearance.isDark
        let colors = DesignTokens.Colors.self
        nativeForegroundColor = .resolved(colors.Text.primary, dark: dark)
        // SwiftTerm paints cells opaquely, so the code surface is laid over the page color.
        nativeBackgroundColor = .resolved(colors.Surface.code, over: colors.Page.base, dark: dark)
        caretColor = .resolved(colors.Text.secondary, dark: dark)
        selectedTextBackgroundColor = .resolved(colors.Fill.strong, dark: dark)
            .withAlphaComponent(dark ? 0.35 : 0.2)
    }
}

/// The terminal view inside SwiftUI; the session keeps the view across rebuilds.
private struct TerminalHost: NSViewRepresentable {
    let session: TerminalSession
    let focus: () -> Void

    func makeNSView(context: Context) -> PaneContentView {
        let container = PaneContentView()
        container.onClick = focus
        container.show(session.view)
        return container
    }

    func updateNSView(_ container: PaneContentView, context: Context) {
        container.onClick = focus
        container.show(session.view)
        container.isHidden = context.environment.paneHidden
    }

    func sizeThatFits(
        _ proposal: ProposedViewSize, nsView: PaneContentView, context: Context
    ) -> CGSize? {
        PaneContentView.fill(proposal)
    }
}

/// A terminal pane: a header with the folder name, then the shell.
struct TerminalPaneView: View {
    let pane: ToolPane
    @Environment(Shell.self) private var shell

    var body: some View {
        let session = shell.tools.terminal(for: pane)
        VStack(spacing: 0) {
            ToolPaneHeader(pane: pane.id, title: pane.title) {
                Image(systemName: Icon.terminal)
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Palette.t2)
                Text(pane.title)
                    .font(.ui(13.5, .semibold))
                    .foregroundStyle(Palette.t1)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .help(pane.folder ?? "")
                Spacer(minLength: 0)
            }
            Rectangle().fill(Palette.hair).frame(height: 1)
            TerminalHost(session: session) { shell.focusPane(pane.id) }
                .padding(EdgeInsets(top: 6, leading: 8, bottom: 6, trailing: 2))
                .overlay(alignment: .bottom) {
                    if session.exited {
                        ExitedBar { session.start() }
                    }
                }
        }
        .modifier(PaneChrome(pane: pane.id))
    }
}

/// Shown when the shell exited: start a new one in the same folder.
private struct ExitedBar: View {
    let restart: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Text("The shell exited.")
                .font(.ui(TypeSize.small))
                .foregroundStyle(Palette.t2)
            Button("Start a new shell", action: restart)
                .buttonStyle(.harness(.primary, height: 24))
        }
        .padding(.horizontal, 12)
        .frame(height: 38)
        .controlGlass()
        .padding(.bottom, 12)
    }
}

/// A tool pane's header: the drag grip, the pane's own content, then maximize and close.
/// Drag it to swap panes; double click maximizes. `title` names the dragged pane.
struct ToolPaneHeader<Content: View>: View {
    let pane: String
    let title: String
    @ViewBuilder let content: () -> Content
    @Environment(Shell.self) private var shell

    var body: some View {
        HStack(spacing: 7) {
            GripDots()
                .foregroundStyle(Palette.t3)
                .frame(width: 22, height: 26)
                .contentShape(Rectangle())
                .help("Drag to swap")
            content()
            PaneButtons(pane: pane)
        }
        .frame(height: 28)
        .padding(EdgeInsets(top: 8, leading: 6, bottom: 8, trailing: 8))
        .background {
            Color.clear
                .contentShape(Rectangle())
                .onTapGesture(count: 2) { shell.toggleMaximize(pane) }
        }
        .modifier(PaneDragHandle(pane: pane, title: title, tone: .done))
        .accessibilityElement(children: .contain)
        .accessibilityLabel(title)
    }
}
