import AppKit
import HarnessKit
import SwiftUI

/// One chat in the workspace: header, transcript and composer. A Claude Code chat shows
/// its read-only history with Continue in harness in place of the composer.
struct PaneView: View {
    let chat: String
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(spacing: 0) {
            PaneHeader(chat: chat)
            Rectangle().fill(Palette.divider).frame(height: 1)
            if shell.isDraft(chat) {
                NewChatPlaceholder()
            } else {
                // An inset rather than a row: the transcript keeps its size, and the open
                // lists cover it instead of pushing it.
                TranscriptView(chat: chat)
                    .safeAreaInset(edge: .bottom, spacing: 0) {
                        if !shell.isClaudeChatPane(chat) {
                            BackgroundBar(chat: chat)
                        }
                    }
            }
            if shell.isClaudeChatPane(chat) {
                ContinueBar(pane: chat)
            } else {
                Composer(chat: chat)
            }
        }
        .modifier(PaneChrome(pane: chat))
    }
}

/// What every pane shares, whatever it shows: its rounded panel with the scanlines inside,
/// the ring that marks focus or a chat that needs the user, the drop targets and
/// highlights while something is dragged. A click anywhere in it focuses it
/// (`Shell.watch`, which sees the click before any view inside takes it). The content lays out to
/// the pane's slot and is clipped to the panel, so nothing spills into a neighbour.
struct PaneChrome: ViewModifier {
    let pane: String
    /// The chat whose state rings the pane: the pane's own, or a pixie's ongoing chat
    /// (none before its first message).
    let chat: String?
    /// A pixie's backdrop, tinting the panel under its scanlines.
    let backdrop: PixieBackground?
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @Environment(\.paneSize) private var size

    init(pane: String) {
        self.init(pane: pane, chat: pane, backdrop: nil)
    }

    init(pane: String, chat: String?, backdrop: PixieBackground?) {
        self.pane = pane
        self.chat = chat
        self.backdrop = backdrop
    }

    func body(content: Content) -> some View {
        let layout = shell.workspaceState.layout
        let waiting =
            chat.flatMap(shell.sessions.session).map { shell.tone(of: $0) == .waiting } ?? false
        let focused = layout.focused == pane && layout.leaves.count > 1
        let shape = RoundedRectangle.rounded(PaneColors.radius)
        content
            .frame(width: size?.width, height: size?.height)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background {
                ZStack {
                    PaneColors.fill
                    if let backdrop {
                        PixieBackdrop(background: backdrop).opacity(0.5)
                    }
                    Scanlines()
                }
            }
            .clipShape(shape)
            .overlay {
                // A chat that needs the user rings amber; the focused pane rings in the
                // accent's focus color; the rest keep a faint ring.
                shape.strokeBorder(
                    waiting ? PaneColors.waitingRing : focused ? accent.focus : PaneColors.ring,
                    lineWidth: 1
                )
                .allowsHitTesting(false)
            }
            .overlay {
                if shell.dragging != nil && shell.dragging?.chat != pane {
                    RoundedRectangle.rounded(PaneColors.radius - 6).inset(by: 6)
                        .strokeBorder(accent.focus, style: StrokeStyle(lineWidth: 1, dash: [4, 4]))
                        .allowsHitTesting(false)
                }
            }
            .overlay {
                if let highlight = shell.dropHighlight, highlight.pane == pane {
                    DropHighlightView(zone: highlight.zone, size: nil)
                }
            }
            .opacity(shell.dragging == .pane(pane) ? 0.5 : 1)
            .onGeometryChange(for: CGSize.self) {
                $0.size
            } action: { size in
                shell.paneSizes[pane] = size
            }
            .onDrop(of: [.harnessChat], delegate: PaneDropDelegate(pane: pane, shell: shell))
            .transition(.scale(scale: 0.97).combined(with: .opacity))
    }
}

/// The separated pane panel's colors (B36 "separated chat panes"): the fill and ring from
/// the tokens (B39), and the amber ring of a chat that needs the user.
enum PaneColors {
    static let radius = 16.0
    static let fill = Palette.chatPane
    static let ring = Palette.divider
    static let waitingRing = themed(
        light: (176 / 255, 109 / 255, 6 / 255, 0.40), dark: (231 / 255, 162 / 255, 62 / 255, 0.45))
    /// The fill as AppKit sees it laid over the opaque window, for views that paint
    /// opaquely such as the terminal.
    static func opaqueFill(dark: Bool) -> NSColor {
        let mac = DesignTokens.Colors.Mac.self
        let fill = dark ? mac.chatPane.dark : mac.chatPane.light
        let base = dark ? mac.windowOpaque.dark : mac.windowOpaque.light
        func mix(_ x: Double, _ y: Double) -> Double { x * fill.alpha + y * (1 - fill.alpha) }
        return NSColor(
            srgbRed: mix(fill.red, base.red), green: mix(fill.green, base.green),
            blue: mix(fill.blue, base.blue), alpha: 1)
    }

    private typealias Components = (Double, Double, Double, Double)

    private static func themed(light: Components, dark: Components) -> Color {
        Color(
            nsColor: NSColor(name: nil) { @Sendable appearance in
                let c = appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? dark : light
                return NSColor(srgbRed: c.0, green: c.1, blue: c.2, alpha: c.3)
            })
    }
}

/// Grip, title, status, branch, elapsed, menu, maximize and close; drag it to swap panes.
private struct PaneHeader: View {
    let chat: String
    @Environment(Shell.self) private var shell
    @Environment(\.paneFit) private var fit
    @Environment(\.paneSize) private var size

    var body: some View {
        let session = shell.sessions.session(chat)
        let claudeChat = shell.claudeChat(inPane: chat)
        let title =
            session?.title ?? claudeChat?.title
            ?? (shell.isClaudeChatPane(chat) ? "Claude Code chat" : "New chat")
        let tone = session.map(shell.tone(of:)) ?? .done
        let lastActivity = session?.updatedAt ?? claudeChat?.lastActivityAt
        let width = size?.width ?? 600
        HStack(spacing: 8) {
            GripDots()
                .foregroundStyle(Palette.t3)
                .frame(width: 14, height: 24)
                .contentShape(Rectangle())
                .help("Drag to swap")
            if shell.isClaudeChatPane(chat) && session == nil {
                ClaudeCodeMarker()
                    .allowsHitTesting(false)
            }
            Text(title)
                .font(.ui(TypeSize.ui, .medium))
                .foregroundStyle(Palette.t1)
                .lineLimit(1)
                .truncationMode(.tail)
                .frame(minWidth: 24, alignment: .leading)
                .layoutPriority(0.5)
                .allowsHitTesting(false)
            Spacer(minLength: 0)
            if let session {
                StatusLabel(
                    tone: tone, label: shell.statusLabel(of: session),
                    hollow: shell.isHollow(session), showsLabel: fit.showsStatusLabel
                )
                .allowsHitTesting(false)
                if let stuck = session.stuck {
                    StuckBadge(flag: stuck)
                }
            }
            if let branch = session?.branch ?? claudeChat?.worktree, fit.showsBranch,
                shell.repo?.git != false
            {
                Chip(icon: Icon.branch, text: branch, mono: true)
                    .foregroundStyle(Palette.t3)
                    .frame(maxWidth: width * 0.4, alignment: .trailing)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(minWidth: min(110, width * 0.25))
            }
            if let lastActivity, fit.showsElapsed {
                TimelineView(.periodic(from: .now, by: 30)) { context in
                    Text(Elapsed.short(from: lastActivity, to: context.date))
                        .font(.ui(TypeSize.meta))
                        .monospacedDigit()
                        .foregroundStyle(Palette.t3)
                }
                .fixedSize()
                .layoutPriority(1)
            }
            if let pr = session?.pr, fit.showsPullRequest {
                PRChip(session: chat, pr: pr)
            }
            if let folder = shell.folder(ofPane: chat) {
                PaneMenu {
                    Button {
                        shell.openTerminal(in: folder)
                    } label: {
                        Label("Terminal here", systemImage: Icon.terminal)
                    }
                    if let pr = session?.pr {
                        Button {
                            shell.openOnGitHub(pr.url)
                        } label: {
                            Label("Open pull request on GitHub", systemImage: Icon.pullRequest)
                        }
                    }
                }
            }
            PaneButtons(pane: chat)
        }
        .padding(.leading, 10)
        .padding(.trailing, 8)
        .frame(height: Metrics.headerHeight)
        // The double click lives behind the header's content, so the maximize and close
        // buttons never wait to see whether a second click follows.
        .background {
            Color.clear
                .contentShape(Rectangle())
                .onTapGesture(count: 2) { shell.toggleMaximize(chat) }
        }
        .modifier(PaneDragHandle(pane: chat, title: title, tone: tone))
        .accessibilityElement(children: .contain)
        .accessibilityLabel(title)
    }
}

/// Makes a pane's header drag the pane to swap it with another. The drag stays inside
/// the window: it starts only past a few points of movement, so clicks, the double click
/// that maximizes and the header's buttons keep working, and its release always ends it.
struct PaneDragHandle: ViewModifier {
    let pane: String
    let title: String
    let tone: StatusTone
    @Environment(Shell.self) private var shell

    func body(content: Content) -> some View {
        content
            .gesture(
                DragGesture(minimumDistance: 6, coordinateSpace: .named(WorkspaceView.space))
                    .onChanged { value in
                        NSCursor.closedHand.set()
                        shell.movePaneDrag(pane, title: title, tone: tone, to: value.location)
                    }
                    .onEnded { value in shell.endPaneDrag(pane, at: value.location) }
            )
            .pointerStyle(shell.dragging == .pane(pane) ? .grabActive : .grabIdle)
    }
}

/// Maximize (or restore) and close, at the end of every pane's header.
struct PaneButtons: View {
    let pane: String
    @Environment(Shell.self) private var shell

    var body: some View {
        let maximized = shell.workspaceState.layout.maximized == pane
        Button {
            shell.toggleMaximize(pane)
        } label: {
            Image(systemName: maximized ? Icon.restore : Icon.maximize)
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(Palette.t3)
        }
        .buttonStyle(.harness(.plain, iconOnly: true))
        .help(maximized ? "Restore" : "Maximize")
        .accessibilityLabel(maximized ? "Restore" : "Maximize")
        Button {
            shell.closePane(pane)
        } label: {
            Image(systemName: Icon.close)
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(Palette.t3)
        }
        .buttonStyle(.harness(.plain, iconOnly: true))
        .help("Close")
        .accessibilityLabel("Close pane")
    }
}

/// A pane's "..." menu.
struct PaneMenu<Items: View>: View {
    @ViewBuilder let items: () -> Items

    var body: some View {
        Menu(content: items) {
            Image(systemName: Icon.more)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(Palette.t3)
                .frame(width: Metrics.buttonHeight, height: Metrics.buttonHeight)
                .contentShape(Rectangle())
        }
        .menuStyle(.button)
        .buttonStyle(.harness(.plain, iconOnly: true))
        .menuIndicator(.hidden)
        .fixedSize()
        .help("More")
        .accessibilityLabel("Pane actions")
    }
}

/// Six dots, two by three: the handle that drags a pane.
struct GripDots: View {
    var body: some View {
        Grid(horizontalSpacing: 2.5, verticalSpacing: 2.5) {
            ForEach(0..<3, id: \.self) { _ in
                GridRow {
                    Circle().frame(width: 2.5, height: 2.5)
                    Circle().frame(width: 2.5, height: 2.5)
                }
            }
        }
        .accessibilityHidden(true)
    }
}

/// The empty transcript of a chat that starts with its first message.
private struct NewChatPlaceholder: View {
    var body: some View {
        Text("New chat")
            .font(.ui(TypeSize.ui))
            .foregroundStyle(Palette.t3)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// In place of the composer for a Claude Code chat: what it is, whether Claude Code has
/// it open, and Continue in harness.
private struct ContinueBar: View {
    let pane: String
    @Environment(Shell.self) private var shell

    var body: some View {
        let chat = shell.claudeChat(inPane: pane)
        let adopting = chat.map { shell.adopting.contains($0.id) } ?? false
        let shape = RoundedRectangle.rounded(Radius.card)
        VStack(alignment: .leading, spacing: 8) {
            if chat?.openInClaudeCode == true {
                Label {
                    Text("Open in Claude Code right now. Close it there before sending from here.")
                } icon: {
                    Image(systemName: Icon.warning)
                }
                .font(.ui(TypeSize.meta))
                .foregroundStyle(StatusTone.waiting.color)
                .labelStyle(TightLabelStyle())
            }
            HStack(spacing: 10) {
                Text(
                    chat == nil
                        ? "This Claude Code chat is no longer listed."
                        : "Started in Claude Code. Read-only until you continue it here."
                )
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t2)
                .frame(maxWidth: .infinity, alignment: .leading)
                Button {
                    shell.continueInHarness(pane)
                } label: {
                    HStack(spacing: 6) {
                        if adopting {
                            ProgressView().controlSize(.small)
                        } else {
                            Image(systemName: Icon.spark)
                        }
                        Text("Continue in harness")
                    }
                }
                .buttonStyle(.harness(.primary))
                .disabled(chat == nil || adopting)
                .help("Turn it into a harness chat in its own folder; the next message resumes it")
            }
        }
        .padding(EdgeInsets(top: 10, leading: 13, bottom: 10, trailing: 10))
        .background(shape.fill(Palette.soft))
        .padding(.horizontal, 12)
        .padding(.bottom, 6)
    }
}
