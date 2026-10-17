import NestKit
import SwiftUI

/// A pixie's mascot: one square per filled cell of its 12 by 10 pixel grid, in the pixie's
/// colour, with no antialiasing so the pixels stay crisp. While `working` it hops and
/// blinks (B48), drawn one cell above its frame without moving anything; with reduced
/// motion it holds still.
struct SpriteView: View {
    let mascot: Mascot
    let color: String
    /// Width in points; the height keeps the grid's 12 to 10 shape.
    let size: Double
    var working = false
    /// Sets its hop apart from other sprites': the pixie's id.
    var phaseKey = ""
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        if working && !reduceMotion {
            let phase = SpriteMotion.phase(of: phaseKey)
            // Ticks fall on this sprite's step boundaries, and only while it works.
            TimelineView(
                .periodic(from: Date(timeIntervalSince1970: -phase / 1000), by: SpriteMotion.step)
            ) { context in
                // Half a millisecond in, so a tick on a boundary reads the step it starts.
                let time = context.date.timeIntervalSince1970 * 1000 + phase + 0.5
                SpritePixels(
                    mascot: mascot, color: color, size: size, frame: SpriteMotion.frame(at: time))
            }
        } else {
            SpritePixels(mascot: mascot, color: color, size: size, frame: .rest)
        }
    }
}

/// A sprite at one frame of its hop.
struct SpritePixels: View {
    let mascot: Mascot
    let color: String
    let size: Double
    let frame: SpriteFrame
    @Environment(\.displayScale) private var scale

    var body: some View {
        let rows = mascot.rows(blinking: frame.blinking)
        let fill = Color(hex: color)
        let columns = Double(rows.first?.count ?? 12)
        Canvas(rendersAsynchronously: false) { context, canvas in
            let cell = canvas.width / columns
            var path = Path()
            for (y, row) in rows.enumerated() {
                for (x, character) in row.enumerated() where character == "#" {
                    // Whole pixels, so neighbouring cells meet without seams.
                    let left = pixel(Double(x) * cell)
                    let top = pixel(Double(y) * cell)
                    let right = pixel(Double(x + 1) * cell)
                    let bottom = pixel(Double(y + 1) * cell)
                    path.addRect(CGRect(x: left, y: top, width: right - left, height: bottom - top))
                }
            }
            context.fill(path, with: .color(fill), style: FillStyle(antialiased: false))
        }
        .frame(width: size, height: size * 10 / 12)
        .offset(y: frame.lifted ? -max(pixel(size / columns), 1 / scale) : 0)
        .accessibilityLabel(mascot.rawValue)
    }

    private func pixel(_ value: Double) -> Double {
        (value * scale).rounded() / scale
    }
}

/// A working pixie's mark where motion is reduced, so its sprite holds still, and nothing
/// else in that place says it works.
struct StillWorkingDot: View {
    let working: Bool
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        if working && reduceMotion {
            StatusDot(tone: .running)
                .help("Working")
        }
    }
}

/// A team's icon (B48): its members' sprites two by two, the leader first, each hopping
/// while its call runs. At 6 points a sprite's cell is one pixel on a Retina display.
struct TeamIconView: View {
    let cells: [TeamIconCell]

    var body: some View {
        VStack(spacing: 2) {
            ForEach(0..<2, id: \.self) { row in
                HStack(spacing: 2) {
                    ForEach(0..<2, id: \.self) { column in
                        let cell = cells[(row * 2 + column) % cells.count]
                        SpriteView(
                            mascot: cell.pixie.mascot, color: cell.pixie.color, size: 6,
                            working: cell.working, phaseKey: cell.phaseKey)
                    }
                }
            }
        }
        .frame(width: 16)
        .accessibilityHidden(true)
    }
}

extension Color {
    /// A pixie's `#RRGGBB`; the default violet for anything else.
    init(hex: String) {
        self.init(PixieColor.rgba(hex) ?? PixieColor.rgba(PixieColor.standard)!)
    }
}
