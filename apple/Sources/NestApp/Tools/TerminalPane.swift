import AppKit
import NestKit
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
    @ObservationIgnored let view = NestTerminalView(
        frame: CGRect(x: 0, y: 0, width: 640, height: 400))
    /// The shell exited; the pane offers to start a new one.
    private(set) var exited = false
    /// The shell started in its folder, not in the home folder in its place.
    private(set) var inFolder = false
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
        inFolder = TerminalFolder.exists(folder)
        guard Self.startsShells else { return }
        view.startProcess(
            executable: Self.loginShell, args: ["-l"], environment: Self.environment,
            currentDirectory: inFolder ? folder : NSHomeDirectory())
    }

    /// Types a line from `TerminalInput.line(for:)`, Return included; the shell reads it
    /// once its prompt is ready. Nothing is typed into a shell that started elsewhere
    /// because the folder was gone; whether it was typed.
    func run(line: String) -> Bool {
        if exited {
            view.feed(text: "\r\n")
            start()
        }
        guard inFolder else { return false }
        view.send(txt: line)
        return true
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
        variables.append("TERM_PROGRAM=Nest")
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
final class NestTerminalView: LocalProcessTerminalView {
    /// Another pane has the focus: the cells paint the unfocused pane's fill (B93).
    var dimmed = false {
        didSet {
            if dimmed != oldValue {
                applyTheme()
            }
        }
    }

    override init(frame: CGRect) {
        super.init(frame: frame)
        font = NSFont.monospacedSystemFont(ofSize: 11.5, weight: .regular)
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
        let mac = DesignTokens.Colors.Mac.self
        nativeForegroundColor = .resolved(mac.textPrimary, dark: dark)
        // SwiftTerm paints cells opaquely, so the panel's fill is laid over the window's.
        nativeBackgroundColor = PaneColors.opaqueFill(dark: dark, dimmed: dimmed)
        caretColor = .resolved(mac.textSecondary, dark: dark)
        selectedTextBackgroundColor = .resolved(mac.selection, over: mac.windowOpaque, dark: dark)
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
        container.follow(context.environment)
        session.view.dimmed = context.environment.paneDimmed
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
                    .font(.system(size: 10))
                    .foregroundStyle(Palette.t3)
                Text(pane.title)
                    .font(.ui(TypeSize.ui, .medium))
                    .modifier(PaneTitleColor())
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .help(pane.folder ?? "")
                Spacer(minLength: 0)
            }
            Rectangle().fill(Palette.divider).frame(height: 1)
            TerminalHost(session: session) { shell.focusPane(pane.id) }
                .padding(EdgeInsets(top: 8, leading: 14, bottom: 6, trailing: 4))
                .overlay(alignment: .bottom) {
                    if session.exited {
                        ExitedBar { session.start() }.modifier(PaneBodyDim())
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
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t2)
            Button("Start a new shell", action: restart)
                .buttonStyle(.nest(.primary))
        }
        .padding(.horizontal, 12)
        .frame(height: 36)
        .sheetSurface(radius: Radius.card)
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
        HStack(spacing: 8) {
            GripDots()
                .foregroundStyle(Palette.t3)
                .frame(width: 14, height: 24)
                .contentShape(Rectangle())
                .help("Drag to swap")
            content()
            PaneButtons(pane: pane)
        }
        .padding(.leading, 10)
        .padding(.trailing, 8)
        .frame(height: Metrics.headerHeight)
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
