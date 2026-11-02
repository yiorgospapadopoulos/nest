import NestKit
import SwiftUI

/// What the island's list shows and where its clicks go.
@MainActor @Observable
final class IslandListModel {
    var entries: [IslandEntry] = []
    @ObservationIgnored var click: (IslandTarget) -> Void = { _ in }
}

/// The list the island grows into on hover: a row per pixie, five showing and the rest
/// scrolling; Nightshade's row when nothing runs.
struct IslandListView: View {
    let model: IslandListModel

    var body: some View {
        let count = min(IslandScene.visibleRows, max(1, model.entries.count))
        ScrollView(.vertical) {
            VStack(spacing: 0) {
                if model.entries.isEmpty {
                    IslandRow(
                        art: .pixie(.nightshade, color: IslandArt.nightshade),
                        title: "Nothing running", detail: "Click to open Nest", status: nil
                    ) { model.click(.strip) }
                } else {
                    ForEach(model.entries) { entry in
                        IslandRow(
                            art: IslandScene.item(entry).art, title: entry.label,
                            detail: entry.activity, status: entry.status
                        ) { model.click(.entry(entry)) }
                    }
                }
            }
        }
        .scrollIndicators(.automatic)
        .frame(height: Double(count) * IslandScene.rowHeight)
        .padding(.top, IslandScene.listTop)
        .padding(.horizontal, 10)
        .padding(.bottom, IslandScene.listBottom)
        .environment(\.colorScheme, .dark)
    }
}

private struct IslandRow: View {
    let art: IslandScene.Art
    let title: String
    let detail: String
    let status: IslandStatus?
    let open: () -> Void
    @State private var hovered = false

    var body: some View {
        HStack(spacing: 10) {
            IslandIcon(art: art)
            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(.ui(13, .semibold))
                    .foregroundStyle(Color(hex: "#f4f4f7"))
                Text(detail)
                    .font(.ui(12))
                    .foregroundStyle(Color(hex: "#8f8f99"))
            }
            .lineLimit(1)
            .truncationMode(.tail)
            .frame(maxWidth: .infinity, alignment: .leading)
            if let status {
                Text(status.word)
                    .font(.ui(12))
                    .foregroundStyle(Self.color(of: status))
                    .lineLimit(1)
                    .fixedSize()
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .frame(height: IslandScene.rowHeight)
        .background(
            Color.white.opacity(hovered ? 0.07 : 0),
            in: RoundedRectangle(cornerRadius: 12, style: .continuous)
        )
        .contentShape(Rectangle())
        .onHover { hovered = $0 }
        .onTapGesture(perform: open)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
        .accessibilityAction { open() }
    }

    static func color(of status: IslandStatus) -> Color {
        switch status {
        case .working: Color(hex: "#9a9aa6")
        case .done: Color(hex: "#46a758")
        case .needsYou, .seen, .failed, .interrupted: Color(hex: "#f5a524")
        }
    }
}

/// A row's sprite at rest, or a team's two by two icon.
private struct IslandIcon: View {
    let art: IslandScene.Art

    var body: some View {
        let size = IslandScene.sprite
        Group {
            switch art {
            case .pixie(let mascot, let color):
                still(mascot, color: color, size: size)
            case .team(let members):
                VStack(spacing: 0) {
                    ForEach(0..<2, id: \.self) { row in
                        HStack(spacing: 0) {
                            ForEach(0..<2, id: \.self) { column in
                                let index = row * 2 + column
                                if members.indices.contains(index) {
                                    still(
                                        members[index].mascot, color: members[index].color,
                                        size: size / 2)
                                } else {
                                    Color.clear.frame(width: size / 2, height: size / 2)
                                }
                            }
                        }
                    }
                }
            }
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }

    private func still(_ mascot: Mascot, color: String, size: Double) -> some View {
        Group {
            if let image = IslandArt.image(mascot, color: color, frame: .rest) {
                Image(decorative: image, scale: 1)
                    .interpolation(.none)
                    .resizable()
            } else {
                Color.clear
            }
        }
        .frame(width: size, height: size)
    }
}
