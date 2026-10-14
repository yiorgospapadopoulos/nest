import HarnessKit
import SwiftUI

/// A Claude Code chat in the sidebar's Idle group: hollow dot and title over a small
/// "Claude Code" marker with its last activity. Click opens its read-only history; drag splits.
struct ClaudeChatRow: View {
    let chat: ClaudeChat
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @Environment(\.revealsHoverControls) private var revealsHoverControls
    @State private var hovering = false

    private var showsMenu: Bool { hovering || revealsHoverControls }

    var body: some View {
        let state = shell.projectState
        let pane = chat.paneID
        let isOpen = state.layout.contains(pane)
        let isSelected = state.selectedChat == pane
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            StatusDot(tone: .done, hollow: true)
            VStack(alignment: .leading, spacing: 1) {
                Text(chat.title)
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t1)
                    .lineLimit(1)
                TimelineView(.periodic(from: .now, by: 30)) { context in
                    HStack(spacing: 4) {
                        Image(systemName: Icon.terminal).font(.system(size: 8))
                        Text("Claude Code")
                        Text("·")
                        Text(Elapsed.short(from: chat.lastActivityAt, to: context.date))
                            .monospacedDigit()
                        if chat.openInClaudeCode {
                            Text("·")
                            Text("open there")
                        }
                    }
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                    .lineLimit(1)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            // Room for the "..." button, so the lines end before it rather than under it.
            .padding(.trailing, showsMenu ? 20 : 0)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(
            isSelected ? accent.selection : (isOpen || hovering) ? Palette.soft : .clear,
            in: .rounded(Radius.row)
        )
        .overlay(alignment: .trailing) {
            if showsMenu {
                RowActionsMenu(title: chat.title) { ClaudeChatActions(chat: chat) }
                    .padding(.trailing, 3)
            }
        }
        .contentShape(Rectangle())
        .pointerStyle(.link)
        .onHover { hovering = $0 }
        .onTapGesture { shell.openChat(pane) }
        .onDrag {
            shell.dragging = .chat(pane)
            return .chat(pane)
        } preview: {
            DragGhost(title: chat.title, tone: .done)
        }
        .contextMenu { ClaudeChatActions(chat: chat) }
        .opacity(shell.dragging == .chat(pane) ? 0.45 : 1)
        .help(chat.openInClaudeCode ? "Open in Claude Code right now" : "Started in Claude Code")
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(
            "\(chat.title), Claude Code chat\(chat.openInClaudeCode ? ", open in Claude Code" : "")\(isOpen ? ", open" : "")"
        )
        .accessibilityAddTraits(.isButton)
        .accessibilityAction { shell.openChat(pane) }
    }
}

/// Open, continue in harness, and archive or unarchive.
struct ClaudeChatActions: View {
    let chat: ClaudeChat
    @Environment(Shell.self) private var shell

    var body: some View {
        Button {
            shell.openChat(chat.paneID)
        } label: {
            Label("Open", systemImage: Icon.open)
        }
        Button {
            shell.continueInHarness(chat.paneID)
        } label: {
            Label("Continue in harness", systemImage: Icon.spark)
        }
        Divider()
        Button {
            shell.setArchived(chat, !chat.archived)
        } label: {
            Label(chat.archived ? "Unarchive" : "Archive", systemImage: Icon.archive)
        }
    }
}

/// The "Claude Code" tag in the header of a Claude Code chat's pane.
struct ClaudeCodeMarker: View {
    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: Icon.terminal).font(.system(size: 8))
            Text("Claude Code")
        }
        .font(.ui(TypeSize.meta))
        .foregroundStyle(Palette.t3)
        .fixedSize()
        .accessibilityLabel("Claude Code chat")
    }
}

/// The rail's corner mark for a Claude Code chat.
struct ClaudeCodeBadge: View {

    var body: some View {
        Image(systemName: Icon.terminal)
            .font(.system(size: 7, weight: .medium))
            .foregroundStyle(Palette.t3)
            .frame(width: 12, height: 12)
            .accessibilityHidden(true)
    }
}
