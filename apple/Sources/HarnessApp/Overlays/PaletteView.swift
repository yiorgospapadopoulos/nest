import HarnessKit
import SwiftUI

/// Cmd-K: search chats in every open project and the messages of every chat, or run a
/// command; arrows move, Return runs, Esc closes.
struct PaletteView: View {
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @FocusState private var focused: Bool

    var body: some View {
        let query = Binding(get: { shell.palette.query }, set: { shell.searchPalette($0) })
        let visible = shell.palette.visible
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Image(systemName: Icon.search).font(.system(size: 17)).foregroundStyle(Palette.t3)
                TextField("Search chats and messages, or run a command", text: query)
                    .textFieldStyle(.plain)
                    .font(.ui(TypeSize.headline))
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
            .frame(height: 54)
            .overlay(alignment: .bottom) {
                Rectangle().fill(focused ? accent.accent : Palette.hair).frame(
                    height: focused ? 2 : 1)
            }
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        if visible.isEmpty && !shell.palette.indexing {
                            Text("No matches")
                                .font(.ui(TypeSize.body))
                                .foregroundStyle(Palette.t3)
                                .frame(maxWidth: .infinity)
                                .padding(20)
                        }
                        ForEach(Array(visible.enumerated()), id: \.element.id) { index, item in
                            if index == 0 || visible[index - 1].group != item.group {
                                Text(item.group.rawValue)
                                    .font(.ui(TypeSize.caption, .bold))
                                    .foregroundStyle(Palette.t3)
                                    .padding(
                                        EdgeInsets(top: 8, leading: 10, bottom: 4, trailing: 10))
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
                    ProgressView().controlSize(.mini)
                    Text("Indexing history…")
                }
                .font(.ui(TypeSize.small))
                .foregroundStyle(Palette.t3)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(EdgeInsets(top: 8, leading: 16, bottom: 10, trailing: 16))
                .overlay(alignment: .top) { Rectangle().fill(Palette.hair).frame(height: 1) }
            }
        }
        .frame(width: 620)
        .sheetGlass(radius: 22)
        .shadow(color: Palette.glassShadow, radius: 30, y: 18)
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
            HStack(spacing: 10) {
                glyph
                    .frame(width: 26, height: 26)
                    .background(
                        selected ? .clear : Palette.fill, in: RoundedRectangle(cornerRadius: 8))
                if item.group == .messages {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(snippet).lineLimit(2)
                        Text("\(item.title) · \(item.subtitle)")
                            .font(.ui(TypeSize.caption))
                            .foregroundStyle(secondary)
                            .lineLimit(1)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    Text(item.title).lineLimit(1)
                    Spacer(minLength: 10)
                    Text(item.subtitle)
                        .font(.ui(TypeSize.small))
                        .foregroundStyle(secondary)
                        .lineLimit(1)
                }
            }
            .font(.ui(TypeSize.body))
            .foregroundStyle(selected ? accent.onAccent : Palette.t1)
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(
                selected ? accent.accent : .clear, in: RoundedRectangle(cornerRadius: 12)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { inside in
            if inside {
                shell.palette.select(item)
            }
        }
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private var secondary: Color {
        selected ? accent.onAccent.opacity(0.75) : Palette.t3
    }

    /// The hit's text with the matched words bold.
    private var snippet: AttributedString {
        item.snippet.reduce(into: AttributedString()) { text, part in
            var piece = AttributedString(part.text)
            if part.matched {
                piece.font = .ui(TypeSize.body, .bold)
            }
            text += piece
        }
    }

    @ViewBuilder private var glyph: some View {
        switch item.glyph {
        case .status(let tone, let hollow):
            StatusDot(tone: tone, hollow: hollow, pulses: false)
        default:
            Image(systemName: symbol).font(.system(size: 13))
        }
    }

    private var symbol: String {
        switch item.glyph {
        case .newChat: Icon.plus
        case .terminal: Icon.terminal
        case .browser: Icon.globe
        case .board: Icon.board
        case .workspace: Icon.workspace
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
