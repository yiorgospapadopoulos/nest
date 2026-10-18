import NestKit
import SwiftUI

/// A pixie's mascot: one square per drawn cell of its 14 by 14 pixel grid, in the tones of
/// the pixie's colour (B89), with no antialiasing so the pixels stay crisp. While `working`
/// it hops and blinks (B48), drawn one cell above its frame without moving anything; with
/// reduced motion it holds still.
struct SpriteView: View {
    let mascot: Mascot
    let color: String
    /// Width and height in points.
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
        let layers = mascot.layers(color: color, blinking: frame.blinking)
        let columns = Double(mascot.rows.first?.count ?? 14)
        Canvas(rendersAsynchronously: false) { context, canvas in
            for layer in layers {
                let path = Self.path(layer.cells, cell: canvas.width / columns, scale: scale)
                let fill = Color(hex: layer.ink.hex).opacity(layer.ink.opacity)
                context.fill(path, with: .color(fill), style: FillStyle(antialiased: false))
            }
        }
        .frame(width: size, height: size)
        .offset(y: frame.lifted ? -max(pixel(size / columns), 1 / scale) : 0)
        .accessibilityLabel(mascot.rawValue)
    }

    private func pixel(_ value: Double) -> Double {
        Self.pixel(value, scale)
    }

    /// One square per cell, its edges on whole pixels so neighbouring cells meet without
    /// seams.
    static func path(
        _ cells: [GridCell], cell: Double, scale: Double, origin: CGPoint = .zero
    ) -> Path {
        var path = Path()
        for square in cells {
            let left = pixel(origin.x + Double(square.x) * cell, scale)
            let top = pixel(origin.y + Double(square.y) * cell, scale)
            let right = pixel(origin.x + Double(square.x + 1) * cell, scale)
            let bottom = pixel(origin.y + Double(square.y + 1) * cell, scale)
            path.addRect(CGRect(x: left, y: top, width: right - left, height: bottom - top))
        }
        return path
    }

    private static func pixel(_ value: Double, _ scale: Double) -> Double {
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
/// while its call runs. At 7 points a sprite's cell is one pixel on a Retina display.
struct TeamIconView: View {
    let cells: [TeamIconCell]

    var body: some View {
        VStack(spacing: 2) {
            ForEach(0..<2, id: \.self) { row in
                HStack(spacing: 2) {
                    ForEach(0..<2, id: \.self) { column in
                        let cell = cells[(row * 2 + column) % cells.count]
                        SpriteView(
                            mascot: cell.pixie.mascot, color: cell.pixie.color, size: 7,
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
