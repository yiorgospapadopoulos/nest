import NestKit
import SwiftUI

// What a pixie's Nest tools leave in chats (B41): who started a chat, who sent a
// message, the report when its chats finish and the live cards in its own chat.

/// "Started by Scout" with Scout's mascot; with `compact`, only the mascot and the name.
struct StartedByLabel: View {
    let label: PixieLabel
    var compact = false

    var body: some View {
        HStack(spacing: 4) {
            if let pixie = label.pixie {
                SpriteView(mascot: pixie.mascot, color: pixie.color, size: 11)
            }
            Text(compact ? label.pixie?.name ?? label.text : label.text)
                .lineLimit(1)
                .truncationMode(.tail)
        }
        .font(.ui(TypeSize.meta))
        .foregroundStyle(Palette.t3)
        .help(label.text)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(label.text)
    }
}

/// A sidebar row's mark for a chat a pixie started: its mascot, with "Started by Scout"
/// as the tooltip and spoken label; the row's title keeps its room.
struct StartedByMark: View {
    let label: PixieLabel

    var body: some View {
        Group {
            if let pixie = label.pixie {
                SpriteView(mascot: pixie.mascot, color: pixie.color, size: 11)
            } else {
                Image(systemName: "sparkle")
                    .font(.system(size: 9))
                    .foregroundStyle(Palette.t3)
            }
        }
        .help(label.text)
        .accessibilityLabel(label.text)
    }
}
