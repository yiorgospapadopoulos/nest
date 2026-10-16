import AppKit
import NestKit
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
            case .failed(let message):
                StartupView(
                    title: "Nest could not start", message: message, retry: controller.start)
            }
        }
        .frame(minWidth: 1000, minHeight: 640)
        // Under the title bar too, so the top band matches the rest of the window.
        .background { SeeThroughWindow().ignoresSafeArea() }
    }
}

/// The window shell: one frosted slab over the desktop holding the project tabs and the
/// current project, its areas meeting edge to edge at 1 point separators.
struct ShellView: View {
    @Environment(Shell.self) private var shell
    @Environment(AppController.self) private var controller
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
    @Environment(\.offscreen) private var snapshot
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @State private var fullScreen = false
    @State private var windowSize = CGSize.zero

    var body: some View {
        let settings = shell.settings
        // Offscreen there is no desktop to show through: the window draws opaque.
        let backdrop = WindowBackdrop.of(
            reduceTransparency: reduceTransparency || snapshot, fullScreen: fullScreen)
        ZStack(alignment: .top) {
            WindowBackground(backdrop: backdrop, image: shell.chatBackground?.image)
            VStack(spacing: 0) {
                // No line under the tabs: the project bar it divided off is gone (B73).
                TabStrip(fullScreen: fullScreen)
                ProjectBody()
            }
            VStack(spacing: 8) {
                ConnectionBanner()
                if let toast = shell.toast {
                    ToastView(toast: toast)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
            }
            .padding(.top, Metrics.stripHeight + 12)
            OverlayLayer()
        }
        // Measured and named inside the safe area's edge, so the window space starts at the
        // window's top, under the title bar, and the chat background lines up there too.
        .onGeometryChange(for: CGSize.self) {
            $0.size
        } action: {
            windowSize = $0
        }
        .windowSpace(size: windowSize)
        .ignoresSafeArea()
        .environment(\.accentColors, AccentColors(accent: settings.accent))
        // Continuous animations stop while nobody can see the window (IMP-11).
        .environment(
            \.reducedMotion,
            systemReduceMotion || snapshot || !shell.model.visibility.isVisible
        )
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
        // What needs the user, and the pixies' unread reports that need action (B42).
        .onChange(
            of: [shell.sessions.attention(), shell.reports.unreadActions()], initial: true
        ) { _, counts in
            if !snapshot {
                NSApp.dockTile.badgeLabel = NotificationPolicy.badge(
                    pending: counts[0], unreadActions: counts[1])
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

/// The Pixies tab, or the current project's sidebar, workspace or board and activity
/// panel; both over the bottom bar.
private struct ProjectBody: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        Group {
            if shell.pixiesOpen {
                VStack(spacing: 0) {
                    PixiesView()
                    StatusBar()
                }
            } else if shell.project == nil {
                NoProjectView()
            } else {
                VStack(spacing: 0) {
                    HStack(spacing: 0) {
                        Sidebar()
                        Separator(axis: .vertical)
                        // The board sits on the pane surface; the workspace's panels float
                        // on the bare window, which shows in the gaps between them.
                        Group {
                            if shell.projectState.view == .board {
                                BoardView()
                                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                                    .paneSurface()
                            } else {
                                WorkspaceView()
                                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                                    .chatBackdrop()
                            }
                        }
                        Separator(axis: .vertical)
                        RightPanel()
                    }
                    StatusBar()
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct NoProjectView: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: Icon.folder).font(.system(size: 26)).foregroundStyle(Palette.t2)
            Text(shell.app.connection == .connected ? "No projects yet" : "Connecting to Nest")
                .font(.ui(TypeSize.reading, .semibold))
            Text("Open a git repository with the + next to the tabs.")
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t3)
        }
    }
}

/// Shown while the daemon cannot be reached or refuses this Mac, with a Retry. While it
/// cannot be reached it also offers to start the Nest service, and shows how to
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
                            .foregroundStyle(StatusTone.waiting.color)
                    }
                    Text(starting ? "Starting the Nest service" : message)
                        .foregroundStyle(Palette.t1)
                    if !starting {
                        Button("Retry") { retry() }
                            .buttonStyle(.nest(height: 24))
                    }
                    if service.offersStart(when: shell.app.connection) {
                        Button("Start Nest service") { controller.startService() }
                            .buttonStyle(.nest(.primary, height: 24))
                            .help("Start or restart the Nest daemon's background service")
                    }
                }
                .font(.ui(TypeSize.ui, .medium))
                .padding(.leading, 16)
                .padding(.trailing, 6)
                .frame(height: 36)
                .sheetSurface(radius: Radius.card)
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
            return shell.app.syncError.map { "Could not load from Nest: \(Shell.describe($0))" }
        case .connecting:
            return nil
        case .disconnected:
            return "Not connected to the Nest daemon"
        case .reconnecting(let attempt, let delay):
            let seconds = Int(delay.rounded(.up))
            return attempt > 1
                ? "Can't reach the Nest daemon. Trying again in \(seconds)s"
                : "Reconnecting to the Nest daemon"
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

    var body: some View {
        switch state {
        case .notInstalled(let command):
            note {
                Text("The Nest service is not installed. Install it once in Terminal:")
                    .font(.ui(TypeSize.ui, .medium))
                    .foregroundStyle(Palette.t1)
                HStack(spacing: 8) {
                    Text(command)
                        .font(.mono(TypeSize.meta))
                        .foregroundStyle(Palette.t1)
                        .textSelection(.enabled)
                        .lineLimit(3)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 7)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(
                            Palette.soft, in: .rounded(Radius.card))
                    Button {
                        shell.copyText(command)
                    } label: {
                        Label("Copy", systemImage: Icon.copy).labelStyle(TightLabelStyle())
                    }
                    .buttonStyle(.nest(height: 28))
                    .help("Copy the command")
                }
                Text("Then choose Start Nest service again.")
                    .font(.ui(TypeSize.meta))
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
                .font(.ui(TypeSize.ui))
                .foregroundStyle(StatusTone.failed.color)
            }
        case .idle, .starting, .started:
            EmptyView()
        }
    }

    private func note(@ViewBuilder _ content: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 8, content: content)
            .padding(14)
            .frame(width: 560, alignment: .leading)
            .sheetSurface(radius: Radius.card)
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
        .font(.ui(TypeSize.ui, .medium))
        .foregroundStyle(Palette.t1)
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .sheetSurface(radius: Radius.card)
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
        case .done: StatusTone.review.color
        case .failed: StatusTone.failed.color
        case .info: StatusTone.waiting.color
        }
    }
}

private struct StartupView: View {
    let title: String
    let message: String?
    let retry: (() -> Void)?
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.offscreen) private var offscreen

    var body: some View {
        ZStack {
            WindowBackground(backdrop: .of(reduceTransparency: reduceTransparency || offscreen))
            VStack(spacing: 10) {
                if retry == nil {
                    ProgressView().controlSize(.small)
                }
                Text(title).font(.ui(TypeSize.headline, .semibold))
                if let message {
                    Text(message)
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(Palette.t2)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 360)
                }
                if let retry {
                    Button("Try again", action: retry).buttonStyle(.nest(.primary))
                }
            }
            .padding(28)
            .sheetSurface()
        }
    }
}
