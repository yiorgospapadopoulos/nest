import NestKit
import SwiftUI

/// A Claude Code chat in the sidebar's Idle group: status dot and title over where it
/// works (its worktree, or the project folder's current branch) and whether Claude Code has
/// it open. Click opens its read-only history; drag splits.
struct ClaudeChatRow: View {
    let chat: ClaudeChat
    @Environment(Shell.self) private var shell
    @Environment(\.revealsHoverControls) private var revealsHoverControls
    @State private var hovering = false

    private var showsMenu: Bool { hovering || revealsHoverControls }

    var body: some View {
        let state = shell.projectState
        let pane = chat.paneID
        let isOpen = state.layout.contains(pane)
        let rowState = state.layout.rowState(of: pane)
        let place = ChatPlace.of(chat, repo: shell.repo)
        return HStack(alignment: .firstTextBaseline, spacing: 8) {
            // A plain dot in the same slot as the chat rows' marks, so the titles line up.
            StatusMark(tone: .done, animates: false)
            VStack(alignment: .leading, spacing: 1) {
                Text(chat.title)
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(rowState.titleColor)
                    .lineLimit(1)
                if place != nil || chat.openInClaudeCode {
                    HStack(spacing: 4) {
                        if let place {
                            PlaceMark(place: place, project: chat.repo)
                        }
                        if chat.openInClaudeCode {
                            if place != nil {
                                Text("·")
                            }
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
        .padding(.horizontal, SidebarRowMetrics.inset)
        .padding(.vertical, 5)
        .frame(minHeight: SidebarRowMetrics.height)
        .sidebarRow(rowState, hovering: hovering)
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
            "\(chat.title), Claude Code chat\(place.map { ", \($0.accessibilityLabel)" } ?? "")\(chat.openInClaudeCode ? ", open in Claude Code" : "")\(isOpen ? ", open" : "")"
        )
        .accessibilityAddTraits(.isButton)
        .accessibilityAction { shell.openChat(pane) }
    }
}

/// Open, continue in Nest, and archive or unarchive.
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
            shell.continueInNest(chat.paneID)
        } label: {
            Label("Continue in Nest", systemImage: Icon.spark)
        }
        Divider()
        Button {
            shell.setArchived(chat, !chat.archived)
        } label: {
            Label(chat.archived ? "Unarchive" : "Archive", systemImage: Icon.archive)
        }
    }
}
