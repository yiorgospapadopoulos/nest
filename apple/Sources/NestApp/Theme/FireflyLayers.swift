import AppKit
import CoreImage
import CoreImage.CIFilterBuiltins
import NestKit
import SwiftUI

/// The working animation's moving marks, `FireflyMotion.tracks` as Core Animation. The box
/// of `Fireflies` sits `margin` in from this view's edges.
struct FireflyLayers: NSViewRepresentable {
    let unit: Double
    let margin: Double
    let color: Color

    func makeNSView(context: Context) -> FireflyLayerView { FireflyLayerView(frame: .zero) }

    func updateNSView(_ view: FireflyLayerView, context: Context) {
        view.style = FireflyLayerView.Style(
            unit: unit, margin: margin, color: color.resolve(in: context.environment))
    }
}

final class FireflyLayerView: LayerMotionView {
    struct Style: Equatable {
        let unit: Double
        let margin: Double
        let color: Color.Resolved
    }

    var style: Style? {
        didSet {
            if style != oldValue { restartMotion() }
        }
    }

    override func startMotion(in layer: CALayer) {
        guard let style else { return }
        layer.sublayers = nil
        let glowImage = FireflyGlow.image(
            color: style.color, unit: style.unit, scale: backingScale)
        let glowSide = glowImage.map { Double($0.width) / backingScale } ?? 0
        let dotSide = FireflyMotion.diameter * style.unit
        for track in FireflyMotion.tracks {
            let glow = CALayer()
            glow.bounds = CGRect(x: 0, y: 0, width: glowSide, height: glowSide)
            glow.contents = glowImage
            let dot = CALayer()
            dot.bounds = CGRect(x: 0, y: 0, width: dotSide, height: dotSide)
            dot.cornerRadius = dotSide / 2
            dot.backgroundColor = style.color.cgColor
            let positions = track.poses.map { pose in
                NSValue(
                    point: CGPoint(
                        x: style.margin + pose.x * style.unit,
                        y: style.margin + pose.y * style.unit))
            }
            let scales = track.poses.map { $0.scale }
            let opacities = track.poses.map { $0.opacity }
            let animations = [
                LayerLoop.keyframes("position", values: positions, times: track.times),
                LayerLoop.keyframes("transform.scale", values: scales, times: track.times),
                LayerLoop.keyframes("opacity", values: opacities, times: track.times),
            ]
            // Fading each on its own, as `Fireflies` draws them, not as a group.
            for mark in [glow, dot] {
                layer.addSublayer(mark)
                for animation in animations {
                    LayerLoop.run(animation, period: track.period, on: mark)
                }
            }
        }
    }
}

/// A dot's glow as an image, so the render server moves a bitmap instead of blurring: the
/// CSS box-shadow 0 0 4px 1.5px of `Fireflies`. A scale on its layer scales the disc and the
/// blur together, as there.
@MainActor
private enum FireflyGlow {
    private struct Key: Hashable {
        let color: Color.Resolved
        let unit: Double
        let scale: Double
    }

    private static var images: [Key: CGImage] = [:]
    // Without colour management, so the blur leaves the colour as it is.
    private static let context = CIContext(options: [.workingColorSpace: NSNull()])

    static func image(color: Color.Resolved, unit: Double, scale: Double) -> CGImage? {
        let key = Key(color: color, unit: unit, scale: scale)
        if let image = images[key] { return image }
        let blur = 2 * unit * scale
        // Three deviations of room all round: the blur has faded out by there.
        let room = 3 * blur
        let disc = (FireflyMotion.diameter + 3) * unit * scale
        let pixels = Int((disc + 2 * room).rounded(.up))
        let drawn = LayerImage.bitmap(pixels: pixels) { bitmap in
            bitmap.setFillColor(color.cgColor)
            bitmap.fillEllipse(
                in: CGRect(x: 0, y: 0, width: pixels, height: pixels)
                    .insetBy(dx: room, dy: room))
        }
        guard let sharp = drawn else { return nil }
        let input = CIImage(cgImage: sharp)
        let filter = CIFilter.gaussianBlur()
        filter.inputImage = input
        filter.radius = Float(blur)
        guard let output = filter.outputImage,
            let image = context.createCGImage(
                output, from: input.extent, format: .RGBA8, colorSpace: sharp.colorSpace)
        else { return nil }
        images[key] = image
        return image
    }
}
