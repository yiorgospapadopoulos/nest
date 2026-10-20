import SwiftUI

/// OpenAI's blossom, the mark Codex shows beside its limits (B94), in the current
/// foreground style so it takes the surrounding ink in light and dark. Drawn from the
/// regular bounding box logo in OpenAI's ChatGPT extension for VS Code
/// (`openai_logo_regular_bounding_box.svg`): a 24 unit box with the mark inset about
/// 2.6 units, the same margin as `ClaudeMark`.
struct OpenAIMark: View {
    var size = 12.0

    var body: some View {
        OpenAIMarkShape()
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }
}

private struct OpenAIMarkShape: Shape {
    enum Segment {
        case move(Double, Double)
        case line(Double, Double)
        case curve(Double, Double, Double, Double, Double, Double)
        case close
    }

    /// The SVG path in its own units, rounded to hundredths: six inner outlines and the
    /// middle hexagon, then the outer outline. Filled by the nonzero rule, as the SVG is.
    static let segments: [Segment] = [
        .move(9.82, 9.47), .line(9.82, 7.71), .curve(9.82, 7.56, 9.87, 7.45, 10, 7.37),
        .line(13.55, 5.33), .curve(14.03, 5.05, 14.61, 4.92, 15.21, 4.92),
        .curve(17.44, 4.92, 18.85, 6.65, 18.85, 8.49),
        .curve(18.85, 8.62, 18.85, 8.77, 18.83, 8.92), .line(15.15, 6.76),
        .curve(14.93, 6.63, 14.7, 6.63, 14.48, 6.76), .line(9.82, 9.47), .close, .move(18.1, 16.35),
        .line(18.1, 12.13), .curve(18.1, 11.87, 17.99, 11.68, 17.77, 11.55), .line(13.11, 8.84),
        .line(14.63, 7.97), .curve(14.76, 7.89, 14.87, 7.89, 15, 7.97), .line(18.55, 10.01),
        .curve(19.57, 10.61, 20.26, 11.87, 20.26, 13.1),
        .curve(20.26, 14.51, 19.42, 15.81, 18.1, 16.35), .close, .move(8.72, 12.63),
        .line(7.2, 11.74), .curve(7.07, 11.67, 7.01, 11.55, 7.01, 11.41), .line(7.01, 7.32),
        .curve(7.01, 5.33, 8.53, 3.82, 10.6, 3.82), .curve(11.38, 3.82, 12.1, 4.08, 12.72, 4.55),
        .line(9.05, 6.67), .curve(8.83, 6.8, 8.72, 6.98, 8.72, 7.24), .line(8.72, 12.63), .close,
        .move(12, 14.53), .line(9.82, 13.3), .line(9.82, 10.7), .line(12, 9.47), .line(14.18, 10.7),
        .line(14.18, 13.3), .line(12, 14.53), .close, .move(13.4, 20.18),
        .curve(12.62, 20.18, 11.9, 19.92, 11.28, 19.45), .line(14.95, 17.33),
        .curve(15.17, 17.2, 15.28, 17.02, 15.28, 16.76), .line(15.28, 11.37), .line(16.82, 12.26),
        .curve(16.95, 12.33, 17.01, 12.45, 17.01, 12.59), .line(17.01, 16.68),
        .curve(17.01, 18.67, 15.47, 20.18, 13.4, 20.18), .close, .move(9, 16.03),
        .line(5.45, 13.99), .curve(4.43, 13.39, 3.74, 12.13, 3.74, 10.9),
        .curve(3.74, 9.47, 4.59, 8.19, 5.91, 7.65), .line(5.91, 11.89),
        .curve(5.91, 12.15, 6.03, 12.33, 6.25, 12.46), .line(10.89, 15.16), .line(9.37, 16.03),
        .curve(9.24, 16.11, 9.13, 16.11, 9, 16.03), .close, .move(8.79, 19.08),
        .curve(6.69, 19.08, 5.15, 17.5, 5.15, 15.55), .curve(5.15, 15.4, 5.17, 15.25, 5.19, 15.1),
        .line(8.85, 17.22), .curve(9.07, 17.35, 9.3, 17.35, 9.52, 17.22), .line(14.18, 14.53),
        .line(14.18, 16.29), .curve(14.18, 16.44, 14.13, 16.55, 14, 16.63), .line(10.45, 18.67),
        .curve(9.96, 18.95, 9.39, 19.08, 8.79, 19.08), .close, .move(13.4, 21.29),
        .curve(15.65, 21.29, 17.53, 19.69, 17.96, 17.57),
        .curve(20.04, 17.04, 21.38, 15.08, 21.38, 13.1),
        .curve(21.38, 11.8, 20.82, 10.53, 19.81, 9.62),
        .curve(19.91, 9.23, 19.96, 8.84, 19.96, 8.45),
        .curve(19.96, 5.79, 17.81, 3.81, 15.32, 3.81),
        .curve(14.82, 3.81, 14.33, 3.88, 13.85, 4.05), .curve(13.01, 3.23, 11.86, 2.71, 10.6, 2.71),
        .curve(8.35, 2.71, 6.47, 4.31, 6.04, 6.43), .curve(3.96, 6.96, 2.62, 8.92, 2.62, 10.9),
        .curve(2.62, 12.2, 3.18, 13.47, 4.19, 14.38), .curve(4.09, 14.77, 4.04, 15.16, 4.04, 15.55),
        .curve(4.04, 18.21, 6.19, 20.2, 8.68, 20.2), .curve(9.18, 20.2, 9.67, 20.12, 10.15, 19.95),
        .curve(10.99, 20.77, 12.14, 21.29, 13.4, 21.29), .close,
    ]
    static let box = 24.0

    func path(in rect: CGRect) -> Path {
        let scale = min(rect.width, rect.height) / Self.box
        func point(_ x: Double, _ y: Double) -> CGPoint {
            CGPoint(x: rect.minX + x * scale, y: rect.minY + y * scale)
        }
        var path = Path()
        for segment in Self.segments {
            switch segment {
            case .move(let x, let y): path.move(to: point(x, y))
            case .line(let x, let y): path.addLine(to: point(x, y))
            case .curve(let x1, let y1, let x2, let y2, let x, let y):
                path.addCurve(to: point(x, y), control1: point(x1, y1), control2: point(x2, y2))
            case .close: path.closeSubpath()
            }
        }
        return path
    }
}
