import AppKit
import NestKit
import SwiftUI

/// One chat in the workspace: header, transcript and composer. A Claude Code chat shows
/// its read-only history with Continue in Nest in place of the composer.
struct PaneView: View {
    let chat: String
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(spacing: 0) {
            PaneHeader(chat: chat)
            Rectangle().fill(Palette.divider).frame(height: 1)
            VStack(spacing: 0) {
                if shell.isDraft(chat) {
                    NewChatPlaceholder()
                } else {
                    // An inset rather than a row: the transcript keeps its size, and the open
                    // lists cover it instead of pushing it.
                    TranscriptView(chat: chat)
                        .safeAreaInset(edge: .bottom, spacing: 0) {
                            if !shell.isClaudeChatPane(chat) {
                                VStack(spacing: 0) {
                                    BackgroundBar(chat: chat)
                                    PendingReviewBar(chat: chat)
                                    LimitPauseBar(chat: chat)
                                }
                            }
                        }
                }
                if shell.isClaudeChatPane(chat) {
                    ContinueBar(pane: chat)
                } else {
                    Composer(chat: chat)
                }
            }
            .modifier(PaneBodyDim())
        }
        .modifier(PaneChrome(pane: chat))
    }
}

/// What every pane shares, whatever it shows: its square panel with the scanlines inside,
/// filled darker while another pane has the focus (B93 focus dim), the drop targets and
/// highlights while something is dragged. A click anywhere in it focuses it
/// (`Shell.watch`, which sees the click before any view inside takes it). The content lays out to
/// the pane's slot and is clipped to it, so nothing spills into a neighbour.
struct PaneChrome: ViewModifier {
    let pane: String
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @Environment(\.paneSize) private var size
    @Environment(\.paneDimmed) private var dimmed

    func body(content: Content) -> some View {
        content
            .frame(width: size?.width, height: size?.height)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background {
                ZStack {
                    dimmed ? Palette.unfocusedPane : Palette.chatPane
                    Scanlines()
                }
            }
            .clipShape(Rectangle())
            .overlay {
                if shell.dragging != nil && shell.dragging?.chat != pane {
                    RoundedRectangle.rounded(Radius.chip).inset(by: 6)
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
            .onDrop(of: [.nestChat], delegate: PaneDropDelegate(pane: pane, shell: shell))
            .transition(.scale(scale: 0.97).combined(with: .opacity))
    }
}

/// Fades a pane's content below its header while another pane has the focus (B93). The
/// header, its status dot and its buttons stay as they are, so a chat that needs the user
/// still shows it.
struct PaneBodyDim: ViewModifier {
    @Environment(\.paneDimmed) private var dimmed
    @Environment(\.colorScheme) private var scheme

    func body(content: Content) -> some View {
        content.opacity(dimmed ? PaneColors.contentOpacity(dark: scheme == .dark) : 1)
    }
}

/// A pane header's title: primary, or grey while another pane has the focus (B93).
struct PaneTitleColor: ViewModifier {
    @Environment(\.paneDimmed) private var dimmed

    func body(content: Content) -> some View {
        content.foregroundStyle(dimmed ? Palette.t2 : Palette.t1)
    }
}

/// A pane's fill from the tokens (B39), and the focus dim's values (B93) for views that
/// need them as numbers.
enum PaneColors {
    /// The opacity of an unfocused pane's content: the token mask's alpha.
    static func contentOpacity(dark: Bool) -> Double {
        let mask = DesignTokens.Colors.Mac.unfocusedContentMask
        return dark ? mask.dark.alpha : mask.light.alpha
    }

    /// The pane's fill, focused or dimmed, as AppKit sees it laid over the opaque window,
    /// for views that paint opaquely such as the terminal.
    static func opaqueFill(dark: Bool, dimmed: Bool) -> NSColor {
        let mac = DesignTokens.Colors.Mac.self
        return .resolved(
            dimmed ? mac.unfocusedPane : mac.chatPane, over: mac.windowOpaque, dark: dark)
    }
}

/// On the left the grip, the chat's name, its status dot and who started it; on the
/// right, at the trailing edge whatever the pane's width, the pull request chip, Stuck,
/// maximize and close (B60). Where it works shows in the composer (B71). Drag it to swap
/// panes.
private struct PaneHeader: View {
    let chat: String
    @Environment(Shell.self) private var shell
    @Environment(\.paneFit) private var fit

    var body: some View {
        let session = shell.sessions.session(chat)
        let claudeChat = shell.claudeChat(inPane: chat)
        let title =
            session?.title ?? claudeChat?.title
            ?? (shell.isClaudeChatPane(chat) ? "Claude Code chat" : "New chat")
        let tone = session.map(shell.tone(of:)) ?? .done
        HStack(spacing: 8) {
            GripDots()
                .foregroundStyle(Palette.t3)
                .frame(width: 14, height: 24)
                .contentShape(Rectangle())
                .help("Drag to swap")
            Text(title)
                .font(.ui(TypeSize.ui, .medium))
                .modifier(PaneTitleColor())
                .lineLimit(1)
                .truncationMode(.tail)
                .frame(minWidth: 24, alignment: .leading)
                .layoutPriority(1)
                .allowsHitTesting(false)
            if let session {
                // The word is gone; its tooltip and VoiceOver still say it.
                let status = shell.statusLabel(of: session)
                StatusLabel(tone: tone, label: status, showsLabel: false)
                    .help(status)
            }
            if let session, let local = shell.providers.localModel(in: session) {
                // A local chat names its model and engine (B106).
                LocalChatLabel(model: local, engine: session.provider)
            } else if let engine = shell.providers.label(for: session) {
                // Only for a chat off Claude, the default (B91).
                Text(engine)
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                    .lineLimit(1)
                    .fixedSize()
                    .help("Runs on \(engine)")
            }
            if let session,
                let startedBy = PixieLabels.startedBy(
                    session, pixies: shell.pixies.pixies)
            {
                StartedByLabel(label: startedBy, compact: !fit.showsHeaderDetails)
                    .frame(maxWidth: 160, alignment: .leading)
                    .fixedSize(horizontal: false, vertical: true)
                    .layoutPriority(0.2)
            }
            Spacer(minLength: 0)
            if let issue = session?.issue, fit.showsPullRequest {
                IssueChip(issue: issue)
            }
            if let pr = session?.pr, fit.showsPullRequest {
                PRChip(session: chat, pr: pr)
            }
            if let stuck = session?.stuck {
                StuckBadge(flag: stuck)
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
        // No visible tag says so any more; VoiceOver still hears whose history this is.
        .accessibilityLabel(
            shell.isClaudeChatPane(chat) && session == nil ? "\(title), Claude Code chat" : title)
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
        .buttonStyle(.nest(.plain, iconOnly: true))
        .help(maximized ? "Restore" : "Maximize")
        .accessibilityLabel(maximized ? "Restore" : "Maximize")
        Button {
            shell.closePane(pane)
        } label: {
            Image(systemName: Icon.close)
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(Palette.t3)
        }
        .buttonStyle(.nest(.plain, iconOnly: true))
        .help("Close")
        .accessibilityLabel("Close pane")
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
/// it open, and Continue in Nest.
private struct ContinueBar: View {
    let pane: String
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent

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
                    shell.continueInNest(pane)
                } label: {
                    HStack(spacing: 6) {
                        if adopting {
                            Fireflies(height: 10, color: accent.onAccent)
                        } else {
                            Image(systemName: Icon.spark)
                        }
                        Text("Continue in Nest")
                    }
                }
                .buttonStyle(.nest(.primary))
                .disabled(chat == nil || adopting)
                .help("Turn it into a Nest chat in its own folder; the next message resumes it")
            }
        }
        .padding(EdgeInsets(top: 10, leading: 13, bottom: 10, trailing: 10))
        .background(shape.fill(Palette.soft))
        .padding(.horizontal, 12)
        .padding(.bottom, 6)
    }
}
