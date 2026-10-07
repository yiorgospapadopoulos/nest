import HarnessKit
import SwiftUI

/// A Claude Code chat in the sidebar's Idle group: hollow dot and title over a small
/// "Claude Code" marker with its last activity. Click opens its read-only history; drag splits.
struct ClaudeChatRow: View {
    let chat: ClaudeChat
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @State private var hovering = false

    var body: some View {
        let state = shell.projectState
        let pane = chat.paneID
        let isOpen = state.layout.contains(pane)
        let isSelected = state.selectedChat == pane
        HStack(alignment: .firstTextBaseline, spacing: 9) {
            StatusDot(tone: .done, hollow: true)
                .frame(width: 10)
            VStack(alignment: .leading, spacing: 2) {
                Text(chat.title)
                    .font(.ui(TypeSize.callout, isOpen ? .semibold : .regular))
                    .foregroundStyle(Palette.t1)
                    .lineLimit(1)
                TimelineView(.periodic(from: .now, by: 30)) { context in
                    HStack(spacing: 4) {
                        Image(systemName: Icon.terminal).font(.system(size: 8, weight: .semibold))
                        Text("Claude Code").fontWeight(.semibold)
                        Text("·")
                        Text(Elapsed.short(from: chat.lastActivityAt, to: context.date))
                            .monospacedDigit()
                        if chat.openInClaudeCode {
                            Text("·")
                            Text("open there")
                        }
                    }
                    .font(.ui(TypeSize.caption))
                    .foregroundStyle(Palette.t3)
                    .lineLimit(1)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, 9)
        .padding(.vertical, 7)
        .background(
            isSelected ? accent.soft : (isOpen || hovering) ? Palette.fill : .clear,
            in: RoundedRectangle(cornerRadius: 10, style: .continuous)
        )
        .contentShape(Rectangle())
        .onHover { hovering = $0 }
        .onTapGesture { shell.openChat(pane) }
        .onDrag {
            shell.dragging = .chat(pane)
            return NSItemProvider(object: pane as NSString)
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

/// Open and continue in harness.
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
    }
}

/// The "Claude Code" tag in the header of a Claude Code chat's pane.
struct ClaudeCodeMarker: View {
    var body: some View {
        HStack(spacing: 3) {
            Image(systemName: Icon.terminal).font(.system(size: 8, weight: .semibold))
            Text("Claude Code")
        }
        .font(.ui(TypeSize.caption, .semibold))
        .foregroundStyle(Palette.t2)
        .padding(.horizontal, 7)
        .frame(height: 20)
        .background(Palette.fill2, in: Capsule())
        .fixedSize()
        .accessibilityLabel("Claude Code chat")
    }
}

/// The rail's corner mark for a Claude Code chat.
struct ClaudeCodeBadge: View {
    var body: some View {
        Image(systemName: Icon.terminal)
            .font(.system(size: 7, weight: .bold))
            .foregroundStyle(Palette.t2)
            .frame(width: 14, height: 14)
            .background(Palette.glassStrong, in: Circle())
            .overlay(Circle().strokeBorder(Palette.hair))
            .accessibilityHidden(true)
    }
}
