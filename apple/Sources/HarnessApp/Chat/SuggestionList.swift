import HarnessKit
import SwiftUI

/// Slash commands, or pixies, teams and files for the token at the caret, above the
/// composer; the arrows move the highlight, Tab or Return insert it, Esc closes the list.
struct SuggestionList: View {
    static let visibleRows = 7
    static let rowHeight: CGFloat = Metrics.rowHeight

    let list: CompletionList
    let active: Int
    let pick: (Completion) -> Void
    @Environment(\.accentColors) private var accent

    var body: some View {
        let sections = list.sections
        VStack(alignment: .leading, spacing: 2) {
            if sections.isEmpty {
                title(list.title)
            }
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        if sections.isEmpty {
                            ForEach(Array(list.items.enumerated()), id: \.element.id) {
                                index, item in
                                row(item, on: index == active)
                                    .id(item.id)
                            }
                        } else {
                            ForEach(sections) { section in
                                title(section.title)
                                    .frame(height: Self.rowHeight, alignment: .bottom)
                                ForEach(section.rows, id: \.item.id) { row in
                                    self.row(row.item, on: row.index == active)
                                        .id(row.item.id)
                                }
                            }
                        }
                    }
                }
                .scrollIndicators(.never)
                .frame(
                    height: Self.rowHeight
                        * CGFloat(min(list.items.count + sections.count, Self.visibleRows))
                )
                .onChange(of: active) { _, index in
                    proxy.scrollTo(list.items[index].id)
                }
            }
        }
        .padding(6)
        .sheetSurface(radius: Radius.card)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(list.title)
    }

    private func title(_ text: String) -> some View {
        Text(text)
            .font(.ui(TypeSize.meta))
            .foregroundStyle(Palette.t3)
            .padding(.horizontal, 8)
            .padding(.top, 2)
    }

    private func row(_ item: Completion, on: Bool) -> some View {
        Button {
            pick(item)
        } label: {
            HStack(spacing: 8) {
                if let mention = item.mention {
                    MentionIcon(mention: mention)
                } else if list.trigger.kind == .file {
                    Image(systemName: Icon.file)
                        .font(.system(size: 10))
                        .foregroundStyle(Palette.t3)
                }
                Text(item.label)
                    .font(
                        list.trigger.kind == .file && item.mention == nil
                            ? .mono(TypeSize.meta) : .ui(TypeSize.ui, .medium)
                    )
                    .foregroundStyle(Palette.t1)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .layoutPriority(1)
                if let hint = item.hint {
                    Text(hint)
                        .font(.mono(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                        .lineLimit(1)
                }
                if let detail = item.detail {
                    Text(detail)
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(Palette.t3)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 8)
            .frame(height: Self.rowHeight)
            .background(
                on ? accent.selection : .clear, in: .rounded(Radius.row)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}

/// A pixie's sprite, or a team's member sprites side by side (up to four).
private struct MentionIcon: View {
    static let shownMembers = 4

    let mention: PixieMention

    var body: some View {
        switch mention {
        case .pixie(let pixie, _):
            SpriteView(mascot: pixie.mascot, color: pixie.color, size: 13)
                .frame(width: 16)
        case .team(_, let members):
            HStack(spacing: 1) {
                ForEach(members.prefix(Self.shownMembers)) { member in
                    SpriteView(mascot: member.mascot, color: member.color, size: 11)
                }
            }
            .frame(minWidth: 16)
        }
    }
}
