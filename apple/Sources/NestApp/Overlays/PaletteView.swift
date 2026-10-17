import NestKit
import SwiftUI

/// Cmd-K: search chats in every open project and the messages of every chat, or run a
/// command; arrows move, Return runs, Esc closes.
struct PaletteView: View {
    @Environment(Shell.self) private var shell
    @FocusState private var focused: Bool

    var body: some View {
        let query = Binding(get: { shell.palette.query }, set: { shell.searchPalette($0) })
        let visible = shell.palette.visible
        VStack(spacing: 0) {
            HStack(spacing: 9) {
                Image(systemName: Icon.search).font(.system(size: 13)).foregroundStyle(Palette.t3)
                TextField("Search chats and messages, or run a command", text: query)
                    .textFieldStyle(.plain)
                    .font(.ui(TypeSize.body))
                    .focused($focused)
                    .onKeyPress(.downArrow) { move(1) }
                    .onKeyPress(.upArrow) { move(-1) }
                    .onKeyPress(.return) {
                        if let item = shell.palette.selected {
                            shell.run(item.action)
                        }
                        return .handled
                    }
                    .onKeyPress(.escape) {
                        shell.close()
                        return .handled
                    }
                    .accessibilityLabel("Search chats, messages and commands")
            }
            .padding(.horizontal, 16)
            .frame(height: 44)
            .overlay(alignment: .bottom) { Separator() }
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        if visible.isEmpty && !shell.palette.indexing {
                            Text("No matches")
                                .font(.ui(TypeSize.ui))
                                .foregroundStyle(Palette.t3)
                                .frame(maxWidth: .infinity)
                                .padding(20)
                        }
                        ForEach(Array(visible.enumerated()), id: \.element.id) { index, item in
                            if index == 0 || visible[index - 1].group != item.group {
                                Text(item.group.rawValue)
                                    .font(.ui(TypeSize.meta))
                                    .foregroundStyle(Palette.t3)
                                    .padding(
                                        EdgeInsets(top: 8, leading: 10, bottom: 3, trailing: 10))
                            }
                            PaletteRow(item: item, selected: index == shell.palette.selection)
                                .id(item.id)
                        }
                    }
                    .padding(6)
                }
                .scrollIndicators(.never)
                .frame(maxHeight: 380)
                .fixedSize(horizontal: false, vertical: true)
                .onChange(of: shell.palette.selection) {
                    if let item = shell.palette.selected {
                        proxy.scrollTo(item.id)
                    }
                }
            }
            if shell.palette.indexing {
                // Hits from older history may be missing until the first pass is done.
                HStack(spacing: 7) {
                    Fireflies(height: 9)
                    Text("Indexing history…")
                }
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(EdgeInsets(top: 8, leading: 16, bottom: 9, trailing: 16))
                .overlay(alignment: .top) { Separator() }
            }
        }
        .frame(width: 620)
        .sheetSurface()
        .onAppear { focused = true }
    }

    private func move(_ step: Int) -> KeyPress.Result {
        shell.palette.move(by: step)
        return .handled
    }
}

private struct PaletteRow: View {
    let item: PaletteItem
    let selected: Bool
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent

    var body: some View {
        Button {
            shell.run(item.action)
        } label: {
            HStack(spacing: 9) {
                glyph
                    .foregroundStyle(Palette.t2)
                    .frame(width: 16, height: 16)
                if item.group == .messages {
                    VStack(alignment: .leading, spacing: 1) {
                        Text(snippet).lineLimit(2)
                        Text("\(item.title) · \(item.subtitle)")
                            .font(.ui(TypeSize.meta))
                            .foregroundStyle(Palette.t3)
                            .lineLimit(1)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    Text(item.title).lineLimit(1)
                    Spacer(minLength: 10)
                    Text(item.subtitle)
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                        .lineLimit(1)
                }
            }
            .font(.ui(TypeSize.ui))
            .foregroundStyle(Palette.t1)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .frame(minHeight: 30)
            .background(selected ? accent.selection : .clear, in: .rounded(Radius.row))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .onHover { inside in
            if inside {
                shell.palette.select(item)
            }
        }
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    /// The hit's text with the matched words bold.
    private var snippet: AttributedString {
        item.snippet.reduce(into: AttributedString()) { text, part in
            var piece = AttributedString(part.text)
            if part.matched {
                piece.font = .ui(TypeSize.ui, .semibold)
            }
            text += piece
        }
    }

    @ViewBuilder private var glyph: some View {
        switch item.glyph {
        case .status(let tone):
            StatusMark(tone: tone, slot: false)
        default:
            Image(systemName: symbol).font(.system(size: 11))
        }
    }

    private var symbol: String {
        switch item.glyph {
        case .newChat: Icon.plus
        case .terminal: Icon.terminal
        case .browser: Icon.globe
        case .board: Icon.board
        case .workspace: Icon.workspace
        case .artifacts: Icon.artifact
        case .sidebar: Icon.leftPanel
        case .activityPanel: Icon.rightPanel
        case .usage: "clock"
        case .code: Icon.code
        case .message(let kind): Self.symbol(of: kind)
        case .folder, .status: Icon.folder
        }
    }

    private static func symbol(of kind: SearchHitKind) -> String {
        switch kind {
        case .title: "text.bubble"
        case .user: "person"
        case .assistant: Icon.spark
        case .tool: "wrench.and.screwdriver"
        case .toolResult: "text.alignleft"
        case .claudeChat: Icon.terminal
        case .unknown: "text.quote"
        }
    }
}
