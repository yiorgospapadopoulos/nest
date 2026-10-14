import AppKit
import HarnessKit
import SwiftUI

/// The window's content for each startup phase.
struct RootView: View {
    @Environment(AppController.self) private var controller

    var body: some View {
        Group {
            switch controller.phase {
            case .ready:
                if let shell = controller.shell {
                    ShellView().environment(shell)
                }
            case .loading:
                StartupView(title: "Starting", message: nil, retry: nil)
            case .noToken:
                StartupView(
                    title: "harness is not set up on this Mac yet",
                    message:
                        "Start the harness daemon once; it stores this Mac's device token in the Keychain.",
                    retry: controller.start)
            case .failed(let message):
                StartupView(
                    title: "harness could not start", message: message, retry: controller.start)
            }
        }
        .frame(minWidth: 1000, minHeight: 640)
        // Under the title bar too, so the top band matches the rest of the window.
        .background { SeeThroughWindow(material: glass.window.material).ignoresSafeArea() }
        .environment(\.glass, glass)
    }

    /// The theme from Settings; the default until the shell is ready.
    private var glass: GlassPalette {
        GlassPalette.of(controller.shell?.settings.glass ?? DesignTokens.GlassTheme.default)
    }
}

/// The window shell: the theme's frost over the desktop, project tabs and the current
/// project.
struct ShellView: View {
    @Environment(Shell.self) private var shell
    @Environment(\.glass) private var glass
    @Environment(AppController.self) private var controller
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
    @Environment(\.flatGlass) private var snapshot
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @State private var fullScreen = false

    var body: some View {
        let settings = shell.settings
        let backdrop = WindowBackdrop.of(
            reduceTransparency: reduceTransparency, fullScreen: fullScreen)
        ZStack(alignment: .top) {
            WindowBackground(backdrop: backdrop)
            VStack(spacing: 0) {
                TabStrip()
                ProjectBody()
            }
            VStack(spacing: 8) {
                ConnectionBanner()
                if let toast = shell.toast {
                    ToastView(toast: toast)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
            }
            .padding(.top, glass.spacing.stripHeight + 12)
            OverlayLayer()
        }
        .ignoresSafeArea()
        .environment(\.accentColors, AccentColors(accent: settings.accent, bubble: settings.bubble))
        // Continuous animations stop while nobody can see the window (IMP-11).
        .environment(
            \.reducedMotion,
            systemReduceMotion || snapshot || !shell.model.visibility.isVisible
        )
        .environment(\.seeThrough, backdrop.isSeeThrough)
        .preferredColorScheme(colorScheme(settings.theme))
        .onReceive(
            NotificationCenter.default.publisher(for: NSWindow.didEnterFullScreenNotification)
        ) { _ in fullScreen = true }
        .onReceive(
            NotificationCenter.default.publisher(for: NSWindow.didExitFullScreenNotification)
        ) { _ in fullScreen = false }
        .onAppear {
            shell.startWatchingDrags()
            // A window restored in full screen sends no notification (I-N).
            fullScreen = NSApp.windows.contains {
                $0.canBecomeMain && $0.styleMask.contains(.fullScreen)
            }
        }
        .onDisappear { shell.stopWatchingDrags() }
        // A project removed from the daemon drops its state, ending its tool panes.
        .onChange(of: Set(shell.app.projects.keys)) { shell.syncTools() }
        .onChange(of: shell.app.connection) { _, connection in
            if connection == .connected {
                controller.service.reset()
            }
        }
        .onChange(of: shell.sessions.attention(), initial: true) { _, count in
            if !snapshot {
                NSApp.dockTile.badgeLabel = NotificationPolicy.badge(pending: count)
            }
        }
    }

    private func colorScheme(_ mode: ThemeMode) -> ColorScheme? {
        switch mode {
        case .auto: nil
        case .light: .light
        case .dark: .dark
        }
    }
}

/// The Pixies tab, or the current project's toolbar, sidebar, workspace or board, and
/// activity panel.
private struct ProjectBody: View {
    @Environment(Shell.self) private var shell
    @Environment(\.glass) private var glass

    var body: some View {
        Group {
            if shell.pixiesOpen {
                PixiesView()
            } else if shell.project == nil {
                NoProjectView()
            } else {
                VStack(spacing: 0) {
                    ProjectToolbar()
                    HStack(spacing: glass.spacing.gap) {
                        Sidebar()
                        Group {
                            if shell.projectState.view == .board {
                                BoardView()
                            } else {
                                WorkspaceView()
                            }
                        }
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        RightPanel()
                    }
                }
                .padding(
                    EdgeInsets(
                        top: 0, leading: glass.spacing.gap, bottom: glass.spacing.gap,
                        trailing: glass.spacing.gap))
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(glass.shell)
    }
}

private struct NoProjectView: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: Icon.folder).font(.system(size: 26)).foregroundStyle(Palette.t2)
            Text(shell.app.connection == .connected ? "No projects yet" : "Connecting to harness")
                .font(.ui(16, .semibold))
            Text("Open a git repository with the + next to the tabs.")
                .font(.ui(TypeSize.callout))
                .foregroundStyle(Palette.t3)
        }
    }
}

/// Shown while the daemon cannot be reached or refuses this Mac, with a Retry. While it
/// cannot be reached it also offers to start the harness service, and shows how to
/// install the service when it is missing.
private struct ConnectionBanner: View {
    @Environment(Shell.self) private var shell
    @Environment(AppController.self) private var controller

    var body: some View {
        if let message {
            let service = controller.service
            let starting = service.state == .starting
            VStack(spacing: 8) {
                HStack(spacing: 10) {
                    if starting {
                        ProgressView().controlSize(.small)
                    } else {
                        Image(systemName: Icon.warning)
                            .foregroundStyle(StatusTone.waiting.textColor)
                    }
                    Text(starting ? "Starting the harness service" : message)
                        .foregroundStyle(Palette.t1)
                    if !starting {
                        Button("Retry") { retry() }
                            .buttonStyle(.harness(height: 24))
                    }
                    if service.offersStart(when: shell.app.connection) {
                        Button("Start harness service") { controller.startService() }
                            .buttonStyle(.harness(.primary, height: 24))
                            .help("Start or restart the harness daemon's background service")
                    }
                }
                .font(.ui(TypeSize.callout, .semibold))
                .padding(.leading, 16)
                .padding(.trailing, 6)
                .frame(height: 36)
                .controlGlass()
                if unreachable {
                    ServiceNote(state: service.state)
                }
            }
            .transition(.move(edge: .top).combined(with: .opacity))
        }
    }

    private var unreachable: Bool {
        switch shell.app.connection {
        case .disconnected, .reconnecting: true
        default: false
        }
    }

    private var message: String? {
        switch shell.app.connection {
        case .connected:
            return shell.app.syncError.map { "Could not load from harness: \(Shell.describe($0))" }
        case .connecting:
            return nil
        case .disconnected:
            return "Not connected to the harness daemon"
        case .reconnecting(let attempt, let delay):
            let seconds = Int(delay.rounded(.up))
            return attempt > 1
                ? "Can't reach the harness daemon. Trying again in \(seconds)s"
                : "Reconnecting to the harness daemon"
        case .unauthorized:
            return "The daemon did not accept this Mac's device token"
        case .forbiddenOrigin:
            return "The daemon refused this connection"
        }
    }

    private func retry() {
        if shell.app.connection == .connected {
            Task { await shell.model.live.refresh() }
        } else {
            controller.connect()
        }
    }
}

/// Under the banner: the install command when the service is missing, or why starting it
/// failed.
private struct ServiceNote: View {
    let state: ServiceStartState
    @Environment(Shell.self) private var shell
    @Environment(\.glass) private var glass

    var body: some View {
        switch state {
        case .notInstalled(let command):
            note {
                Text("The harness service is not installed. Install it once in Terminal:")
                    .font(.ui(TypeSize.callout, .semibold))
                    .foregroundStyle(Palette.t1)
                HStack(spacing: 8) {
                    Text(command)
                        .font(.mono(11.5))
                        .foregroundStyle(Palette.t1)
                        .textSelection(.enabled)
                        .lineLimit(3)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 7)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(
                            Palette.fill, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                    Button {
                        shell.copyText(command)
                    } label: {
                        Label("Copy", systemImage: Icon.copy).labelStyle(TightLabelStyle())
                    }
                    .buttonStyle(.harness(height: 28))
                    .help("Copy the command")
                }
                Text("Then choose Start harness service again.")
                    .font(.ui(TypeSize.label))
                    .foregroundStyle(Palette.t3)
            }
        case .failed(let reason):
            note {
                Label {
                    Text(reason).textSelection(.enabled)
                } icon: {
                    Image(systemName: Icon.warning)
                }
                .labelStyle(TightLabelStyle())
                .font(.ui(TypeSize.callout))
                .foregroundStyle(StatusTone.failed.textColor)
            }
        case .idle, .starting, .started:
            EmptyView()
        }
    }

    private func note(@ViewBuilder _ content: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 8, content: content)
            .padding(14)
            .frame(width: 560, alignment: .leading)
            .sheetGlass(radius: glass.radius.card)
            .transition(.opacity)
    }
}

private struct ToastView: View {
    let toast: Toast

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon).foregroundStyle(color)
            Text(toast.text).lineLimit(2)
        }
        .font(.ui(TypeSize.callout, .semibold))
        .foregroundStyle(Palette.t1)
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .controlGlass()
        .allowsHitTesting(false)
    }

    private var icon: String {
        switch toast.kind {
        case .done: Icon.check
        case .failed: Icon.close
        case .info: Icon.bell
        }
    }

    private var color: Color {
        switch toast.kind {
        case .done: StatusTone.review.textColor
        case .failed: StatusTone.failed.textColor
        case .info: StatusTone.waiting.textColor
        }
    }
}

private struct StartupView: View {
    let title: String
    let message: String?
    let retry: (() -> Void)?
    @Environment(\.glass) private var glass
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    var body: some View {
        ZStack {
            WindowBackground(backdrop: .of(reduceTransparency: reduceTransparency))
            VStack(spacing: 10) {
                if retry == nil {
                    ProgressView().controlSize(.small)
                }
                Text(title).font(.ui(TypeSize.headline, .semibold))
                if let message {
                    Text(message)
                        .font(.ui(TypeSize.callout))
                        .foregroundStyle(Palette.t2)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 360)
                }
                if let retry {
                    Button("Try again", action: retry).buttonStyle(.harness(.primary))
                }
            }
            .padding(28)
            .panelGlass(radius: glass.sheetRadius)
        }
    }
}
