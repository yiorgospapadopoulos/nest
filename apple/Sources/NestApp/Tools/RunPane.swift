import AppKit
import NestKit
import SwiftTerm
import SwiftUI

// The dev server of a chat's folder (B108): the Run control in a chat's header and the run
// output pane.

extension Shell {
    var runs: RunStore { model.runs }

    /// Run: opens the output pane beside the chat, leaving the focus in the chat, and
    /// starts the folder's run command.
    func startRun(from chat: String) {
        openRunOutput(from: chat)
        Task {
            do {
                try await runs.start(chat)
            } catch {
                show(error, doing: "Could not run it")
            }
        }
    }

    func stopRun(_ session: String) {
        Task {
            do {
                try await runs.stop(session)
            } catch {
                show(error, doing: "Could not stop it")
            }
        }
    }

    func restartRun(_ session: String) {
        Task {
            do {
                try await runs.restart(session)
            } catch {
                show(error, doing: "Could not restart it")
            }
        }
    }

    /// The folder's output pane: an open one stays as it is, else a new one beside the chat.
    func openRunOutput(from chat: String) {
        guard let folder = runs.status(of: chat)?.folder else { return }
        let size = workspaceSize
        update { $0.runOutput(folder: folder, session: chat, beside: chat, in: size) }
    }

    /// A port chip: the page in a new browser pane.
    func openPort(_ port: RunPort) {
        guard let url = port.url else { return }
        newBrowser(url: url)
    }
}

/// The Run control at the right of a chat's header, only when its project has a run
/// command: Run, Starting, the port chips and stop, or Exited N.
struct RunControlView: View {
    let chat: String
    @Environment(Shell.self) private var shell
    @Environment(\.paneFit) private var fit

    var body: some View {
        let control = RunControl(
            status: shell.runs.status(of: chat), compact: !fit.showsAllPorts,
            machine: shell.model.remoteMachine)
        switch control {
        case .run(let help):
            Button {
                shell.startRun(from: chat)
            } label: {
                RunLabel(icon: Icon.play, title: "Run")
            }
            .buttonStyle(.nest(.plain, height: 20))
            .help(help)
        case .starting(let help):
            Button {
                shell.stopRun(chat)
            } label: {
                HStack(spacing: 5) {
                    RunSpinner()
                    Text("Starting")
                }
            }
            .buttonStyle(.nest(.plain, height: 20))
            .help(help)
        case .running(let ports, let more, let moreHelp, let stopHelp):
            HStack(spacing: 4) {
                PortChips(ports: ports, more: more, moreHelp: moreHelp)
                StopRunButton(help: stopHelp) { shell.stopRun(chat) }
            }
            .fixedSize()
        case .exited(let label, let help):
            Button {
                shell.startRun(from: chat)
            } label: {
                RunLabel(icon: Icon.play, title: label)
                    .foregroundStyle(StatusTone.failed.color)
            }
            .buttonStyle(.nest(.plain, height: 20))
            .help(help)
        case nil:
            EmptyView()
        }
    }
}

/// A play triangle and a word, small.
private struct RunLabel: View {
    let icon: String
    let title: String

    var body: some View {
        HStack(spacing: 5) {
            Image(systemName: icon)
                .font(.system(size: 8, weight: .medium))
            Text(title)
                .lineLimit(1)
        }
        .fixedSize()
    }
}

/// The run's ports, the first with its green dot, and "+N" for the rest.
private struct PortChips: View {
    let ports: [RunPort]
    let more: Int
    let moreHelp: String?

    var body: some View {
        ForEach(ports) { port in
            PortChip(port: port)
        }
        if more > 0 {
            Text("+\(more)")
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .monospacedDigit()
                .help(moreHelp ?? "")
        }
    }
}

/// One port: opens localhost in a browser pane, or, for a daemon on another machine, only
/// says where it runs.
private struct PortChip: View {
    let port: RunPort
    @Environment(Shell.self) private var shell

    var body: some View {
        if port.url != nil {
            Button {
                shell.openPort(port)
            } label: {
                chip
            }
            .buttonStyle(.plain)
            .pointerStyle(.link)
            .help(port.help)
        } else {
            chip.help(port.help)
        }
    }

    private var chip: some View {
        HStack(spacing: 5) {
            if port.live {
                Circle()
                    .fill(StatusTone.review.color)
                    .frame(width: 6, height: 6)
                    .background(Circle().fill(StatusTone.review.color.opacity(0.15)).padding(-3))
                    .accessibilityHidden(true)
            }
            Text(port.label)
                .font(.mono(11))
                .monospacedDigit()
        }
        .foregroundStyle(Palette.t1)
        .padding(.horizontal, 7)
        .frame(height: 20)
        .background(Palette.soft, in: .rounded(Radius.chip))
        .contentShape(.rounded(Radius.chip))
        .fixedSize()
        .accessibilityLabel("Port \(port.label)")
    }
}

/// The stop square.
private struct StopRunButton: View {
    let help: String
    let stop: () -> Void

    var body: some View {
        Button(action: stop) {
            Image(systemName: Icon.stop)
                .font(.system(size: 8, weight: .medium))
        }
        .buttonStyle(.nest(.plain, height: 20, iconOnly: true))
        .help(help)
        .accessibilityLabel("Stop")
    }
}

/// A small turning ring; still when motion is reduced.
private struct RunSpinner: View {
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        Group {
            if reduceMotion {
                Circle()
                    .trim(from: 0, to: 0.75)
                    .stroke(Palette.t3, lineWidth: 1.5)
                    .frame(width: 9, height: 9)
            } else {
                // Wider than the ring by its stroke, half of which falls outside it.
                ColoredLayerMark<RunSpinnerRing>(color: Palette.t3)
                    .frame(width: RunSpinnerRing.side, height: RunSpinnerRing.side)
                    .frame(width: 9, height: 9)
            }
        }
        .accessibilityHidden(true)
    }
}

private final class RunSpinnerRing: ColoredMotionView {
    static let side = 12.0

    override func startMotion(in layer: CALayer) {
        guard let color else { return }
        let ring = CAShapeLayer()
        ring.bounds = CGRect(x: 0, y: 0, width: 9, height: 9)
        ring.position = CGPoint(x: Self.side / 2, y: Self.side / 2)
        ring.path = CGPath(ellipseIn: ring.bounds, transform: nil)
        ring.fillColor = nil
        ring.strokeColor = color.cgColor
        ring.lineWidth = 1.5
        ring.strokeEnd = 0.75
        ring.contentsScale = backingScale
        layer.sublayers = [ring]
        let turn = CABasicAnimation(keyPath: "transform.rotation.z")
        turn.fromValue = 0
        turn.toValue = 2 * Double.pi
        LayerLoop.run(turn, period: 0.9, on: ring)
    }
}

// MARK: Output pane

/// One output pane's read-only terminal, fed from its folder's output buffer.
@MainActor
final class RunOutputSession {
    let view = RunTerminalView(frame: CGRect(x: 0, y: 0, width: 640, height: 400))
    private var feed = RunOutputFeed()

    /// Writes what the buffer gained since, or all of it after it started over.
    func show(_ buffer: RunOutputBuffer?) {
        guard let buffer else { return }
        let next = feed.next(buffer)
        if next.reset {
            // RIS: a clean screen and scrollback.
            view.feed(text: "\u{1B}c")
        }
        if !next.text.isEmpty {
            view.feed(text: next.text)
        }
    }
}

/// A terminal nothing can be typed into: the daemon owns the process. Text can still be
/// selected and copied.
final class RunTerminalView: TerminalView, @preconcurrency TerminalViewDelegate {
    var dimmed = false {
        didSet {
            if dimmed != oldValue {
                applyNestTheme(dimmed: dimmed)
            }
        }
    }

    override init(frame: CGRect) {
        super.init(frame: frame)
        font = NSFont.monospacedSystemFont(ofSize: 11.5, weight: .regular)
        terminalDelegate = self
        applyNestTheme(dimmed: dimmed)
    }

    required init?(coder: NSCoder) {
        fatalError("not used from a nib")
    }

    override func viewDidChangeEffectiveAppearance() {
        super.viewDidChangeEffectiveAppearance()
        applyNestTheme(dimmed: dimmed)
    }

    func send(source: TerminalView, data: ArraySlice<UInt8>) {}
    func sizeChanged(source: TerminalView, newCols: Int, newRows: Int) {}
    func setTerminalTitle(source: TerminalView, title: String) {}
    func hostCurrentDirectoryUpdate(source: TerminalView, directory: String?) {}
    func scrolled(source: TerminalView, position: Double) {}
    func bell(source: TerminalView) {}
    func iTermContent(source: TerminalView, content: ArraySlice<UInt8>) {}
    func rangeChanged(source: TerminalView, startY: Int, endY: Int) {}

    func requestOpenLink(source: TerminalView, link: String, params: [String: String]) {
        if let url = URL(string: link), url.scheme == "http" || url.scheme == "https" {
            NSWorkspace.shared.open(url)
        }
    }

    /// A dev server's output never sets the clipboard (OSC 52): the program running it
    /// is not the user. Selecting and copying text works without this.
    func clipboardCopy(source: TerminalView, content: Data) {}
}

/// The read-only terminal inside SwiftUI; the session keeps the view across rebuilds.
private struct RunTerminalHost: NSViewRepresentable {
    let session: RunOutputSession
    let buffer: RunOutputBuffer?
    let focus: () -> Void

    func makeNSView(context: Context) -> PaneContentView {
        let container = PaneContentView()
        container.onClick = focus
        container.show(session.view)
        session.show(buffer)
        return container
    }

    func updateNSView(_ container: PaneContentView, context: Context) {
        container.onClick = focus
        container.show(session.view)
        container.follow(context.environment)
        session.view.dimmed = context.environment.paneDimmed
        session.show(buffer)
    }

    func sizeThatFits(
        _ proposal: ProposedViewSize, nsView: PaneContentView, context: Context
    ) -> CGSize? {
        PaneContentView.fill(proposal)
    }
}

/// A folder's run output: the command, the branch, the ports, restart and stop, then the
/// output. Closing it leaves the run going.
struct RunOutputPaneView: View {
    let pane: ToolPane
    @Environment(Shell.self) private var shell
    @Environment(\.paneFit) private var fit

    var body: some View {
        let folder = pane.folder ?? ""
        let chat = pane.session ?? ""
        let status = shell.runs.status(ofFolder: folder)
        let title = RunPaneText.title(status)
        VStack(spacing: 0) {
            ToolPaneHeader(pane: pane.id, title: title) {
                Text(title)
                    .font(.ui(TypeSize.ui, .medium))
                    .modifier(PaneTitleColor())
                    .lineLimit(1)
                    .truncationMode(.tail)
                    .frame(minWidth: 24, alignment: .leading)
                    .layoutPriority(1)
                    .help(folder)
                if let place = RunPaneText.place(shell.sessions.session(chat)) {
                    Text(place)
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
                Spacer(minLength: 0)
                if case .running(let ports, let more, let moreHelp, _) = RunControl(
                    status: status, compact: !fit.showsAllPorts,
                    machine: shell.model.remoteMachine)
                {
                    PortChips(ports: ports, more: more, moreHelp: moreHelp)
                }
                Button {
                    shell.restartRun(chat)
                } label: {
                    Image(systemName: Icon.refresh)
                        .font(.system(size: 10, weight: .medium))
                }
                .buttonStyle(.nest(.plain, height: 20, iconOnly: true))
                .disabled(status?.available != true)
                .help("Restart")
                .accessibilityLabel("Restart")
                StopRunButton(help: "Stop") { shell.stopRun(chat) }
                    .disabled(status?.isAlive != true)
            }
            Rectangle().fill(Palette.divider).frame(height: 1)
            RunTerminalHost(
                session: shell.tools.runOutput(for: pane), buffer: shell.runs.output(of: folder)
            ) { shell.focusPane(pane.id) }
            .padding(EdgeInsets(top: 8, leading: 14, bottom: 6, trailing: 4))
        }
        .modifier(PaneChrome(pane: pane.id))
        .task(id: pane.id) {
            await shell.runs.load(chat)
            await shell.runs.loadOutput(folder: folder, session: chat)
        }
    }
}
