import NestKit
import SwiftUI

/// A project's icon: its pixie sprite in the chosen colour when the project has one, or a
/// small badge with its initials otherwise. `mascot` and `color` come from the project's
/// settings (`#RRGGBB`; nil is the default pixie colour).
struct ProjectIcon: View {
    let name: String
    var mascot: Mascot?
    var color: String?
    /// Width and height in points.
    var size: Double = 14

    /// Muted badge colours, picked by the project's name so each keeps its own.
    static let badgeColors: [Color] = [
        Color(red: 0.549, green: 0.482, blue: 0.404),
        Color(red: 0.431, green: 0.541, blue: 0.420),
        Color(red: 0.365, green: 0.498, blue: 0.608),
        Color(red: 0.412, green: 0.451, blue: 0.498),
    ]

    var body: some View {
        Group {
            if let mascot, mascot != .unknown {
                SpriteView(mascot: mascot, color: color ?? PixieColor.standard, size: size)
            } else {
                badge
            }
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }

    private var badge: some View {
        let index = ProjectMark.colorIndex(for: name, count: Self.badgeColors.count)
        return Text(Initials.of(name))
            .font(.system(size: size * 0.5, weight: .bold))
            .minimumScaleFactor(0.5)
            .foregroundStyle(.white)
            .frame(width: size, height: size)
            .background(Self.badgeColors[index], in: .rounded(size * 0.27))
    }
}
