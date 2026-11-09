import SwiftUI

/// The classic git branch: two commits on a line and a third that curves into it, drawn on
/// a 16 unit grid in the foreground style, as the web's `branch` glyph. `size` matches the
/// font size the SF Symbol it replaces was set at.
struct BranchIcon: View {
    var size = 10.0

    var body: some View {
        let side = size * 1.15
        BranchShape()
            .stroke(
                style: StrokeStyle(lineWidth: side / 16 * 1.4, lineCap: .round, lineJoin: .round)
            )
            .frame(width: side, height: side)
            .accessibilityHidden(true)
    }
}

private struct BranchShape: Shape {
    func path(in rect: CGRect) -> Path {
        let unit = min(rect.width, rect.height) / 16
        func point(_ x: Double, _ y: Double) -> CGPoint {
            CGPoint(x: rect.minX + x * unit, y: rect.minY + y * unit)
        }
        let radius = 1.75 * unit
        var path = Path()
        for (x, y) in [(4.5, 3.5), (4.5, 12.5), (11.5, 3.5)] {
            let center = point(x, y)
            path.addEllipse(
                in: CGRect(
                    x: center.x - radius, y: center.y - radius, width: 2 * radius,
                    height: 2 * radius))
        }
        path.move(to: point(4.5, 5.25))
        path.addLine(to: point(4.5, 10.75))
        path.move(to: point(11.5, 5.25))
        path.addLine(to: point(11.5, 6.25))
        path.addCurve(
            to: point(9.25, 8.5), control1: point(11.5, 7.49), control2: point(10.49, 8.5))
        path.addLine(to: point(6.75, 8.5))
        path.addCurve(
            to: point(4.5, 10.75), control1: point(5.51, 8.5), control2: point(4.5, 9.51))
        return path
    }
}
