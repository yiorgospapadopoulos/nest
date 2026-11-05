import AppKit
import SwiftUI

// Any SwiftUI animation that runs every frame keeps the whole window's display list updating
// on the main thread (B124), so loops that run for as long as a chat does live here instead,
// as Core Animation in the render server.

/// A view holding a loop's layers, y down as in SwiftUI. It never takes clicks. Core
/// Animation drops a layer's animations when it leaves a window and its clock stops while
/// the Mac sleeps, so `startMotion` runs again on each return; loops follow the wall clock,
/// so that shows no jump.
class LayerMotionView: NSView {
    /// The window's pixels per point.
    var backingScale: Double { Double(window?.backingScaleFactor ?? 1) }

    required override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        layerContentsRedrawPolicy = .never
        NotificationCenter.default.addObserver(
            self, selector: #selector(restartMotion),
            name: NSApplication.didBecomeActiveNotification, object: nil)
        NSWorkspace.shared.notificationCenter.addObserver(
            self, selector: #selector(restartMotion),
            name: NSWorkspace.didWakeNotification, object: nil)
    }

    required init?(coder: NSCoder) {
        fatalError("not used from a nib")
    }

    override var isFlipped: Bool { true }

    override func hitTest(_ point: NSPoint) -> NSView? { nil }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        restartMotion()
    }

    override func viewDidChangeBackingProperties() {
        super.viewDidChangeBackingProperties()
        restartMotion()
    }

    @objc func restartMotion() {
        guard window != nil, let layer else { return }
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        startMotion(in: layer)
        CATransaction.commit()
    }

    /// Sets up the view's layers and their loops from nothing. Geometry cannot come from
    /// `bounds`, which SwiftUI may set only later.
    func startMotion(in layer: CALayer) {}
}

@MainActor
enum LayerLoop {
    /// CSS `ease-in-out`, as `RowGlow` and `FireflyMotion` define their motion.
    static let easeInOut = CAMediaTimingFunction(controlPoints: 0.42, 0, 0.58, 1)
    /// SwiftUI's `easeOut`.
    static let easeOut = CAMediaTimingFunction(controlPoints: 0, 0, 0.58, 1)

    /// Keyframes with an ease-in-out between each two.
    static func keyframes(
        _ keyPath: String, values: [Any], times: [Double]
    ) -> CAKeyframeAnimation {
        let animation = CAKeyframeAnimation(keyPath: keyPath)
        animation.values = values
        animation.keyTimes = times.map { NSNumber(value: $0) }
        animation.timingFunctions = Array(repeating: easeInOut, count: values.count - 1)
        return animation
    }

    /// Runs an animation forever on a layer already in place, `period` seconds a pass, as
    /// far through its loop as `clock` seconds are: marks on the same clock move in step.
    static func run(
        _ animation: CAPropertyAnimation, period: Double, on layer: CALayer,
        clock: Double = Date.timeIntervalSinceReferenceDate
    ) {
        animation.duration = period
        animation.repeatCount = .infinity
        animation.isRemovedOnCompletion = false
        let loop = animation.autoreverses ? 2 * period : period
        animation.beginTime =
            layer.convertTime(CACurrentMediaTime(), from: nil)
            - clock.truncatingRemainder(dividingBy: loop)
        layer.add(animation, forKey: animation.keyPath)
    }
}

enum LayerImage {
    /// A square sRGB bitmap of `pixels` a side, drawn by `draw`.
    static func bitmap(pixels: Int, draw: (CGContext) -> Void) -> CGImage? {
        guard let space = CGColorSpace(name: CGColorSpace.sRGB),
            let context = CGContext(
                data: nil, width: pixels, height: pixels, bitsPerComponent: 8, bytesPerRow: 0,
                space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
        else { return nil }
        draw(context)
        return context.makeImage()
    }
}

/// A loop that takes one colour, resolved as SwiftUI would here, so it follows the theme
/// through the environment.
class ColoredMotionView: LayerMotionView {
    var color: Color.Resolved? {
        didSet {
            if color != oldValue { restartMotion() }
        }
    }
}

struct ColoredLayerMark<Mark: ColoredMotionView>: NSViewRepresentable {
    let color: Color

    func makeNSView(context: Context) -> Mark { Mark(frame: .zero) }

    func updateNSView(_ view: Mark, context: Context) {
        view.color = color.resolve(in: context.environment)
    }
}

/// A band of light crossing the view from left to right, in fractions of its width, so a
/// resize changes nothing about the motion.
struct Sweep: Equatable {
    /// The band's centre at the start and the end of a pass.
    let from: Double
    let to: Double
    let halfWidth: Double
    let period: Double
    /// Ease-in-out across a pass, else linear.
    let eases: Bool
    var radius = 0.0
}

struct LightSweep: NSViewRepresentable {
    let color: Color
    let sweep: Sweep

    func makeNSView(context: Context) -> LightSweepView { LightSweepView(frame: .zero) }

    func updateNSView(_ view: LightSweepView, context: Context) {
        view.show(sweep, in: color.resolve(in: context.environment))
    }
}

final class LightSweepView: LayerMotionView {
    private var sweep: Sweep?
    private var color: Color.Resolved?

    override func makeBackingLayer() -> CALayer { CAGradientLayer() }

    func show(_ sweep: Sweep, in color: Color.Resolved) {
        guard sweep != self.sweep || color != self.color else { return }
        self.sweep = sweep
        self.color = color
        restartMotion()
    }

    override func startMotion(in layer: CALayer) {
        guard let sweep, let color, let gradient = layer as? CAGradientLayer else { return }
        let peak = color.cgColor
        // The colour itself fading out, not `clear`, which is black and would grey the band.
        let edge = peak.copy(alpha: 0) ?? peak
        gradient.colors = [edge, peak, edge]
        gradient.cornerRadius = sweep.radius
        gradient.cornerCurve = .continuous
        gradient.masksToBounds = true
        func point(_ x: Double) -> CGPoint { CGPoint(x: x, y: 0.5) }
        gradient.startPoint = point(sweep.from - sweep.halfWidth)
        gradient.endPoint = point(sweep.from + sweep.halfWidth)
        for (keyPath, offset) in [("startPoint", -sweep.halfWidth), ("endPoint", sweep.halfWidth)] {
            let pass = CABasicAnimation(keyPath: keyPath)
            pass.fromValue = NSValue(point: point(sweep.from + offset))
            pass.toValue = NSValue(point: point(sweep.to + offset))
            pass.timingFunction = sweep.eases ? LayerLoop.easeInOut : nil
            LayerLoop.run(pass, period: sweep.period, on: gradient)
        }
    }
}
