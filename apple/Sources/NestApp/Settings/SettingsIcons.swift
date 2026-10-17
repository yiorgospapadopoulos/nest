import NestKit
import SwiftUI

/// The Pixies page's winged pixie (B86): the sprites' 12 by 10 grid, its filled rows centred
/// in the icon box; each cell is a whole number of pixels so it stays crisp.
struct PixieGlyph: View {
    /// The icon box's side, in points.
    let side: Double
    @Environment(\.displayScale) private var scale

    var body: some View {
        let rows = SettingsPage.pixieGlyph
        let cell = max((side / 16 * scale).rounded(), 1) / scale
        let filled = rows.indices.filter { rows[$0].contains("#") }
        let first = Double(filled.first ?? 0)
        let height = Double((filled.last ?? 0) + 1) - first
        Canvas(rendersAsynchronously: false) { context, canvas in
            let top = ((canvas.height - height * cell) / 2 * scale).rounded() / scale - first * cell
            let path = SpritePixels.path(
                rows, cell: cell, scale: scale, origin: CGPoint(x: 0, y: top))
            context.fill(path, with: .color(Palette.t2), style: FillStyle(antialiased: false))
        }
        .frame(width: 12 * cell, height: side)
        .frame(width: side, height: side)
        .accessibilityHidden(true)
    }
}

/// The Agents page's robot head (B86), drawn on a 24 point grid like the other line icons.
struct RobotGlyph: View {
    let side: Double

    var body: some View {
        ZStack {
            RobotShape(part: .outline)
                .stroke(
                    Palette.t2,
                    style: StrokeStyle(
                        lineWidth: 1.6 * side / 24, lineCap: .round, lineJoin: .round)
                )
            RobotShape(part: .eyes).fill(Palette.t2)
        }
        .frame(width: side, height: side)
        .accessibilityHidden(true)
    }
}

private struct RobotShape: Shape {
    enum Part {
        case outline, eyes
    }

    let part: Part

    func path(in rect: CGRect) -> Path {
        let unit = min(rect.width, rect.height) / 24
        func point(_ x: Double, _ y: Double) -> CGPoint {
            CGPoint(x: rect.minX + x * unit, y: rect.minY + y * unit)
        }
        func circle(_ x: Double, _ y: Double, _ radius: Double) -> CGRect {
            CGRect(
                x: rect.minX + (x - radius) * unit, y: rect.minY + (y - radius) * unit,
                width: radius * 2 * unit, height: radius * 2 * unit)
        }
        var path = Path()
        switch part {
        case .outline:
            path.addRoundedRect(
                in: CGRect(
                    origin: point(4.5, 8), size: CGSize(width: 15 * unit, height: 11.5 * unit)),
                cornerSize: CGSize(width: 3 * unit, height: 3 * unit))
            for (from, to) in [
                ((12.0, 8.0), (12.0, 5.0)), ((2.5, 12.5), (2.5, 15.5)),
                ((21.5, 12.5), (21.5, 15.5)),
                ((10, 16), (14, 16)),
            ] {
                path.move(to: point(from.0, from.1))
                path.addLine(to: point(to.0, to.1))
            }
            path.addEllipse(in: circle(12, 3.8, 1.2))
        case .eyes:
            path.addEllipse(in: circle(9.3, 12.5, 1.1))
            path.addEllipse(in: circle(14.7, 12.5, 1.1))
        }
        return path
    }
}
