import HarnessKit
import SwiftUI

/// Slash commands or files for the token at the caret, above the composer; the arrows
/// move the highlight, Tab or Return insert it, Esc closes the list.
struct SuggestionList: View {
    static let visibleRows = 7
    static let rowHeight: CGFloat = 30

    let list: CompletionList
    let active: Int
    let pick: (Completion) -> Void
    @Environment(\.accentColors) private var accent

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: DesignTokens.Radius.card, style: .continuous)
        VStack(alignment: .leading, spacing: 2) {
            Text(list.title)
                .font(.ui(TypeSize.micro, .bold))
                .textCase(.uppercase)
                .foregroundStyle(Palette.t3)
                .padding(.horizontal, 8)
                .padding(.top, 2)
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(spacing: 0) {
                        ForEach(Array(list.items.enumerated()), id: \.element.id) { index, item in
                            row(item, on: index == active)
                                .id(item.id)
                        }
                    }
                }
                .scrollIndicators(.never)
                .frame(
                    height: Self.rowHeight
                        * CGFloat(min(list.items.count, Self.visibleRows))
                )
                .onChange(of: active) { _, index in
                    proxy.scrollTo(list.items[index].id)
                }
            }
        }
        .padding(6)
        .background(shape.fill(Palette.glassRegular))
        .overlay(shape.stroke(Palette.glassBorder))
        .shadow(color: Palette.glassShadow.opacity(0.4), radius: 10, y: 6)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(list.title)
    }

    private func row(_ item: Completion, on: Bool) -> some View {
        Button {
            pick(item)
        } label: {
            HStack(spacing: 8) {
                if list.trigger.kind == .file {
                    Image(systemName: Icon.file)
                        .font(.system(size: 10))
                        .foregroundStyle(Palette.t3)
                }
                Text(item.label)
                    .font(
                        list.trigger.kind == .file
                            ? .mono(TypeSize.small) : .ui(TypeSize.small, .semibold)
                    )
                    .foregroundStyle(Palette.t1)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .layoutPriority(1)
                if let hint = item.hint {
                    Text(hint)
                        .font(.mono(TypeSize.caption))
                        .foregroundStyle(Palette.t3)
                        .lineLimit(1)
                }
                if let detail = item.detail {
                    Text(detail)
                        .font(.ui(TypeSize.caption))
                        .foregroundStyle(Palette.t2)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 8)
            .frame(height: Self.rowHeight)
            .background(
                on ? accent.soft : .clear,
                in: RoundedRectangle(cornerRadius: 8, style: .continuous)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}
