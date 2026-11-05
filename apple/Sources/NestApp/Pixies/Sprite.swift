import AppKit
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
    @Environment(\.displayScale) private var scale

    var body: some View {
        if working && !reduceMotion {
            let lift = SpritePixels.lift(mascot, size: size, scale: scale)
            // Taller than the frame by the lift, so the hop stays inside the view's bounds.
            SpriteHopLayers(
                hop: SpriteHop(
                    mascot: mascot, color: color, size: size, lift: lift,
                    phase: SpriteMotion.phase(of: phaseKey))
            )
            .frame(width: size, height: size + lift)
            .frame(width: size, height: size, alignment: .bottom)
            .accessibilityLabel(mascot.rawValue)
        } else {
            SpritePixels(mascot: mascot, color: color, size: size, frame: .rest)
        }
    }
}

/// What a hopping sprite's layers show.
private struct SpriteHop: Equatable {
    let mascot: Mascot
    let color: String
    let size: Double
    let lift: Double
    /// In milliseconds, as `SpriteMotion.phase`.
    let phase: Double
}

private struct SpriteHopLayers: NSViewRepresentable {
    let hop: SpriteHop

    func makeNSView(context: Context) -> SpriteHopView { SpriteHopView(frame: .zero) }

    func updateNSView(_ view: SpriteHopView, context: Context) {
        view.hop = hop
    }
}

/// A sprite stepping through `SpriteMotion.loop` in the render server: two pre-drawn images
/// and a lift, one discrete keyframe per step.
private final class SpriteHopView: LayerMotionView {
    var hop: SpriteHop? {
        didSet {
            if hop != oldValue { restartMotion() }
        }
    }

    override func startMotion(in layer: CALayer) {
        guard let hop, let rest = image(of: hop, blinking: false),
            let blink = image(of: hop, blinking: true)
        else { return }
        let sprite = CALayer()
        sprite.frame = CGRect(x: 0, y: hop.lift, width: hop.size, height: hop.size)
        sprite.contents = rest
        sprite.contentsScale = backingScale
        sprite.magnificationFilter = .nearest
        layer.sublayers = [sprite]
        let frames = SpriteMotion.loop
        // A discrete animation takes one key time more than it has values.
        let times = (0...frames.count).map { Double($0) / Double(frames.count) }
        let looks = frames.map { $0.blinking ? blink : rest }
        let heights = frames.map { $0.lifted ? -hop.lift : 0.0 }
        let animations = [
            LayerLoop.keyframes("contents", values: looks, times: times),
            LayerLoop.keyframes("transform.translation.y", values: heights, times: times),
        ]
        // Half a millisecond in, so the clock on a boundary reads the step it starts.
        let clock = Date().timeIntervalSince1970 + (hop.phase + 0.5) / 1000
        for animation in animations {
            animation.calculationMode = .discrete
            animation.timingFunctions = nil
            LayerLoop.run(animation, period: SpriteMotion.loopDuration, on: sprite, clock: clock)
        }
    }

    private func image(of hop: SpriteHop, blinking: Bool) -> CGImage? {
        let scale = backingScale
        let pixels = Int((hop.size * scale).rounded())
        let columns = SpritePixels.columns(hop.mascot)
        return LayerImage.bitmap(pixels: pixels) { context in
            // Grid rows run down, a bitmap context's y up.
            context.translateBy(x: 0, y: Double(pixels))
            context.scaleBy(x: scale, y: -scale)
            context.setShouldAntialias(false)
            for layer in hop.mascot.layers(color: hop.color, blinking: blinking) {
                let rgba = PixieColor.rgba(layer.ink.hex) ?? PixieColor.rgba(PixieColor.standard)!
                context.setFillColor(
                    CGColor(
                        srgbRed: rgba.red, green: rgba.green, blue: rgba.blue,
                        alpha: layer.ink.opacity))
                context.addPath(
                    SpritePixels.path(layer.cells, cell: hop.size / columns, scale: scale).cgPath)
                context.fillPath()
            }
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
        let columns = Self.columns(mascot)
        Canvas(rendersAsynchronously: false) { context, canvas in
            for layer in layers {
                let path = Self.path(layer.cells, cell: canvas.width / columns, scale: scale)
                let fill = Color(hex: layer.ink.hex).opacity(layer.ink.opacity)
                context.fill(path, with: .color(fill), style: FillStyle(antialiased: false))
            }
        }
        .frame(width: size, height: size)
        .offset(y: frame.lifted ? -Self.lift(mascot, size: size, scale: scale) : 0)
        .accessibilityLabel(mascot.rawValue)
    }

    static func columns(_ mascot: Mascot) -> Double {
        Double(mascot.rows.first?.count ?? 14)
    }

    /// How far a hop lifts a sprite: one cell, on whole pixels.
    static func lift(_ mascot: Mascot, size: Double, scale: Double) -> Double {
        max(pixel(size / columns(mascot), scale), 1 / scale)
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
