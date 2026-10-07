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
            Rectangle().fill(Palette.hair).frame(height: 1)
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

/// What every pane shares, whatever it shows: the glass, the focus ring, the drop
/// targets and highlights while something is dragged, and focus on click. The content
/// lays out to the pane's slot and is clipped to it, so nothing spills into a neighbour.
struct PaneChrome: ViewModifier {
    let pane: String
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @Environment(\.glass) private var glass
    @Environment(\.paneSize) private var size

    func body(content: Content) -> some View {
        let layout = shell.projectState.layout
        let focused = layout.focused == pane
        let shape = glass.rounded(glass.radius.pane)
        content
            .frame(width: size?.width, height: size?.height)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .clipShape(shape)
            .panelGlass(radius: glass.radius.pane, tint: .reading)
            .overlay {
                if focused && layout.leaves.count > 1 {
                    shape.strokeBorder(accent.line, lineWidth: 1.5).allowsHitTesting(false)
                }
            }
            .overlay {
                if shell.dragging != nil && shell.dragging?.chat != pane {
                    shape.inset(by: 6)
                        .strokeBorder(
                            accent.line, style: StrokeStyle(lineWidth: 1.5, dash: [5, 4])
                        )
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
            .simultaneousGesture(TapGesture().onEnded { shell.focusPane(pane) })
            .onDrop(of: [.plainText], delegate: PaneDropDelegate(pane: pane, shell: shell))
            .transition(.scale(scale: 0.97).combined(with: .opacity))
    }
}

/// Grip, status, title, branch, elapsed, maximize and close; drag it to swap panes.
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
        HStack(spacing: 7) {
            GripDots()
                .foregroundStyle(Palette.t3)
                .frame(width: 22, height: 26)
                .contentShape(Rectangle())
                .help("Drag to swap")
            if let session {
                StatusPill(
                    tone: tone, label: shell.statusLabel(of: session),
                    hollow: shell.isHollow(session), showsLabel: fit.showsStatusLabel
                )
                .allowsHitTesting(false)
                if let stuck = session.stuck {
                    StuckBadge(flag: stuck)
                }
            } else if shell.isClaudeChatPane(chat) {
                ClaudeCodeMarker()
                    .allowsHitTesting(false)
            }
            Text(title)
                .font(.ui(13.5, .semibold))
                .foregroundStyle(Palette.t1)
                .lineLimit(1)
                .truncationMode(.tail)
                .frame(minWidth: 24, alignment: .leading)
                .layoutPriority(0.5)
                .allowsHitTesting(false)
            Spacer(minLength: 0)
            if let branch = session?.branch ?? claudeChat?.worktree, fit.showsBranch,
                shell.repo?.git != false
            {
                Chip(icon: Icon.branch, text: branch, mono: true)
                    .frame(maxWidth: width * 0.4, alignment: .trailing)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(minWidth: min(110, width * 0.25))
            }
            if let lastActivity, fit.showsElapsed {
                TimelineView(.periodic(from: .now, by: 30)) { context in
                    Text(Elapsed.short(from: lastActivity, to: context.date))
                        .font(.ui(TypeSize.caption))
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
        .frame(height: 28)
        .padding(EdgeInsets(top: 8, leading: 6, bottom: 8, trailing: 8))
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
        let maximized = shell.projectState.layout.maximized == pane
        Button {
            shell.toggleMaximize(pane)
        } label: {
            Image(systemName: maximized ? Icon.restore : Icon.maximize)
                .font(.system(size: 11, weight: .medium))
        }
        .buttonStyle(.harness(.ghost, height: 24, iconOnly: true))
        .help(maximized ? "Restore" : "Maximize")
        .accessibilityLabel(maximized ? "Restore" : "Maximize")
        Button {
            shell.closePane(pane)
        } label: {
            Image(systemName: Icon.close).font(.system(size: 11, weight: .medium))
        }
        .buttonStyle(.harness(.ghost, height: 24, iconOnly: true))
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
                .font(.system(size: 11, weight: .bold))
                .frame(width: 24, height: 24)
                .contentShape(Rectangle())
        }
        .menuStyle(.button)
        .buttonStyle(.harness(.ghost, height: 24, iconOnly: true))
        .menuIndicator(.hidden)
        .fixedSize()
        .help("More")
        .accessibilityLabel("Pane actions")
    }
}

/// Six dots, two by three: the handle that drags a pane.
struct GripDots: View {
    var body: some View {
        Grid(horizontalSpacing: 3, verticalSpacing: 3) {
            ForEach(0..<3, id: \.self) { _ in
                GridRow {
                    Circle().frame(width: 3, height: 3)
                    Circle().frame(width: 3, height: 3)
                }
            }
        }
        .accessibilityHidden(true)
    }
}

/// The empty transcript of a chat that starts with its first message.
private struct NewChatPlaceholder: View {
    @Environment(\.accentColors) private var accent

    var body: some View {
        VStack(spacing: 6) {
            Image(systemName: Icon.spark)
                .font(.system(size: 24))
                .foregroundStyle(accent.accent)
            Text("New chat")
                .font(.ui(TypeSize.callout, .semibold))
                .foregroundStyle(Palette.t2)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// In place of the composer for a Claude Code chat: what it is, whether Claude Code has
/// it open, and Continue in harness.
private struct ContinueBar: View {
    let pane: String
    @Environment(Shell.self) private var shell
    @Environment(\.glass) private var glass

    var body: some View {
        let chat = shell.claudeChat(inPane: pane)
        let adopting = chat.map { shell.adopting.contains($0.id) } ?? false
        let shape = glass.rounded(glass.radius.card)
        VStack(alignment: .leading, spacing: 8) {
            if chat?.openInClaudeCode == true {
                Label {
                    Text("Open in Claude Code right now. Close it there before sending from here.")
                } icon: {
                    Image(systemName: Icon.warning)
                }
                .font(.ui(TypeSize.label))
                .foregroundStyle(StatusTone.waiting.textColor)
                .labelStyle(TightLabelStyle())
            }
            HStack(spacing: 10) {
                Text(
                    chat == nil
                        ? "This Claude Code chat is no longer listed."
                        : "Started in Claude Code. Read-only until you continue it here."
                )
                .font(.ui(TypeSize.small))
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
        .padding(EdgeInsets(top: 10, leading: 12, bottom: 10, trailing: 10))
        .background(shape.fill(glass.reading))
        .overlay(GlassEdges(shape: shape))
        .background(GlassDepth(shape: shape, shadow: glass.style.shadow.panel))
        .padding(.horizontal, 10)
        .padding(.bottom, 10)
    }
}
