import NestKit
import SwiftUI

/// A pixie's mascot: one square per filled cell of its 12 by 10 pixel grid, in the pixie's
/// colour, with no antialiasing so the pixels stay crisp.
struct SpriteView: View {
    let mascot: Mascot
    let color: String
    /// Width in points; the height keeps the grid's 12 to 10 shape.
    let size: Double

    var body: some View {
        let rows = mascot.rows
        let fill = Color(hex: color)
        Canvas(rendersAsynchronously: false) { context, canvas in
            let columns = Double(rows.first?.count ?? 12)
            let cell = canvas.width / columns
            var path = Path()
            for (y, row) in rows.enumerated() {
                for (x, character) in row.enumerated() where character == "#" {
                    // Whole points, so neighbouring cells meet without seams.
                    let left = (Double(x) * cell).rounded()
                    let top = (Double(y) * cell).rounded()
                    let right = (Double(x + 1) * cell).rounded()
                    let bottom = (Double(y + 1) * cell).rounded()
                    path.addRect(CGRect(x: left, y: top, width: right - left, height: bottom - top))
                }
            }
            context.fill(path, with: .color(fill), style: FillStyle(antialiased: false))
        }
        .frame(width: size, height: size * 10 / 12)
        .accessibilityLabel(mascot.rawValue)
    }
}

extension Color {
    /// A pixie's `#RRGGBB`; the default violet for anything else.
    init(hex: String) {
        self.init(PixieColor.rgba(hex) ?? PixieColor.rgba(PixieColor.standard)!)
    }
}

/// The tinted backdrop of a pixie's chat, as on the iPhone: a soft vertical blend of two
/// status colours, or nothing for Plain.
struct PixieBackdrop: View {
    let background: PixieBackground

    var body: some View {
        if let stops {
            LinearGradient(colors: stops, startPoint: .top, endPoint: .bottom)
                .allowsHitTesting(false)
                .accessibilityHidden(true)
        }
    }

    private var stops: [Color]? {
        switch background {
        case .meadow:
            [StatusTone.review.color.opacity(0.16), StatusTone.waiting.color.opacity(0.06)]
        case .dusk:
            [StatusTone.waiting.color.opacity(0.16), StatusTone.failed.color.opacity(0.08)]
        case .night:
            [StatusTone.running.color.opacity(0.18), Palette.t1.opacity(0.08)]
        case .dawn:
            [StatusTone.failed.color.opacity(0.10), StatusTone.waiting.color.opacity(0.12)]
        case .plain, .unknown:
            nil
        }
    }
}
