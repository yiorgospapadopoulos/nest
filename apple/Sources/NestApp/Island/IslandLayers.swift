import AppKit
import QuartzCore

/// The island's Core Animation part: the black strip under the sprites with the
/// needs-you glows on it, or the rings over them. The render server pulses the glows and
/// grows the rings, so a waiting pixie costs the app no frames.
final class IslandLayers: NSView {
    enum Place {
        /// The strip, its divider and the glows: under the sprites.
        case under
        /// The badges' rings: over them.
        case over
    }

    private let place: Place
    private let root = CALayer()
    /// Holds the rest, flipped as needed so it lays out top down like the island's view.
    private let content = CALayer()
    private let shape = CAShapeLayer()
    private let divider = CALayer()
    private let ringClip = CALayer()
    private var glows: [String: (clip: CALayer, gradient: CAGradientLayer)] = [:]
    private var rings: [String: CAShapeLayer] = [:]
    private var animated = true

    init(_ place: Place) {
        self.place = place
        super.init(frame: .zero)
        layer = root
        wantsLayer = true
        root.addSublayer(content)
        switch place {
        case .under:
            shape.fillColor = .black
            shape.lineWidth = 1
            divider.backgroundColor = .white
            content.addSublayer(shape)
            content.addSublayer(divider)
        case .over:
            ringClip.masksToBounds = true
            content.addSublayer(ringClip)
        }
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) is not supported")
    }

    override func hitTest(_ point: NSPoint) -> NSView? { nil }

    /// Shows what the last frame described; without motion the glows hold still and no
    /// ring grows.
    func show(_ effects: IslandEffects, animated: Bool) {
        // Only what changed is set: an equal path set again is drawn again.
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        defer { CATransaction.commit() }
        layOutTopDown()
        if animated != self.animated {
            self.animated = animated
            for glow in glows.values { glow.clip.removeFromSuperlayer() }
            for ring in rings.values { ring.removeFromSuperlayer() }
            glows = [:]
            rings = [:]
        }
        switch place {
        case .under:
            if shape.path != effects.shape {
                shape.path = effects.shape
            }
            let stroke = effects.pill ? CGColor(gray: 1, alpha: 0.12) : nil
            if shape.strokeColor != stroke {
                shape.strokeColor = stroke
            }
            if divider.frame != effects.divider {
                divider.frame = effects.divider
            }
            if divider.opacity != Float(effects.dividerAlpha) {
                divider.opacity = Float(effects.dividerAlpha)
            }
            showGlows(effects.glows)
        case .over:
            if ringClip.frame != effects.ringClip {
                ringClip.frame = effects.ringClip
            }
            showRings(effects.rings, origin: effects.ringClip.origin)
            for spark in effects.sparks {
                add(spark, origin: effects.ringClip.origin)
            }
        }
    }

    /// AppKit decides which of the layers above are flipped; the content flips itself so
    /// that, counted from the window down, its geometry runs top down.
    private func layOutTopDown() {
        var flips = 0
        var above = content.superlayer
        while let layer = above {
            if layer.isGeometryFlipped { flips += 1 }
            above = layer.superlayer
        }
        let flipped = flips % 2 == 0
        if content.isGeometryFlipped != flipped {
            content.isGeometryFlipped = flipped
        }
        if content.frame != root.bounds {
            content.frame = root.bounds
        }
    }

    private func showGlows(_ wanted: [String: IslandEffects.Glow]) {
        for (id, glow) in glows where wanted[id] == nil {
            glow.clip.removeFromSuperlayer()
            glows[id] = nil
        }
        let radius = IslandScene.sprite * 0.8
        for (id, glow) in wanted {
            let layers = glows[id] ?? makeGlow(radius: radius)
            glows[id] = layers
            if layers.clip.frame != glow.clip {
                layers.clip.frame = glow.clip
            }
            if layers.clip.opacity != Float(glow.alpha) {
                layers.clip.opacity = Float(glow.alpha)
            }
            let frame = CGRect(
                x: glow.center.x - radius - glow.clip.minX,
                y: glow.center.y - radius - glow.clip.minY, width: radius * 2,
                height: radius * 2)
            if layers.gradient.frame != frame {
                layers.gradient.frame = frame
            }
        }
    }

    /// The mockup's pulse, 0.3 ± 0.14 over about a second and a half.
    private func makeGlow(radius: Double) -> (clip: CALayer, gradient: CAGradientLayer) {
        let clip = CALayer()
        clip.masksToBounds = true
        let gradient = CAGradientLayer()
        gradient.type = .radial
        gradient.colors = [IslandScene.orange, IslandScene.orange.copy(alpha: 0)!]
        gradient.locations = [NSNumber(value: 2 / radius), 1]
        gradient.startPoint = CGPoint(x: 0.5, y: 0.5)
        gradient.endPoint = CGPoint(x: 1, y: 1)
        if animated {
            let pulse = CABasicAnimation(keyPath: "opacity")
            pulse.fromValue = 0.16
            pulse.toValue = 0.44
            pulse.duration = .pi * 0.24
            pulse.autoreverses = true
            pulse.repeatCount = .infinity
            pulse.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
            gradient.add(pulse, forKey: "pulse")
        }
        gradient.opacity = 0.3
        clip.addSublayer(gradient)
        // Glows go over the strip and its divider.
        content.addSublayer(clip)
        return (clip, gradient)
    }

    private func showRings(_ wanted: [String: CGPoint], origin: CGPoint) {
        for (id, ring) in rings where wanted[id] == nil {
            ring.removeFromSuperlayer()
            rings[id] = nil
        }
        for (id, center) in wanted {
            let ring = rings[id] ?? makeRing()
            rings[id] = ring
            let position = CGPoint(x: center.x - origin.x, y: center.y - origin.y)
            if ring.position != position {
                ring.position = position
            }
        }
    }

    /// Grows from the badge's edge by six points and fades, every 1.4 seconds.
    private func makeRing() -> CAShapeLayer {
        let ring = CAShapeLayer()
        ring.fillColor = nil
        ring.strokeColor = IslandScene.orange
        ring.lineWidth = 1.3
        ring.path = Self.circle(10.5)
        ring.opacity = 0
        let grow = CABasicAnimation(keyPath: "path")
        grow.fromValue = Self.circle(4.5)
        grow.toValue = Self.circle(10.5)
        let fade = CABasicAnimation(keyPath: "opacity")
        fade.fromValue = 1
        fade.toValue = 0
        let group = CAAnimationGroup()
        group.animations = [grow, fade]
        group.duration = 1.4
        group.repeatCount = .infinity
        ring.add(group, forKey: "ring")
        ringClip.addSublayer(ring)
        return ring
    }

    /// A z or a sparkle that rises and fades for its life, then goes.
    private func add(_ spark: IslandEffects.Spark, origin: CGPoint) {
        let layer = CALayer()
        layer.anchorPoint = .zero
        if spark.isZ, let image = IslandArt.z(color: spark.color) {
            layer.bounds = CGRect(x: 0, y: 0, width: 4, height: 5)
            layer.contents = image
            layer.contentsScale = 2
            layer.magnificationFilter = .nearest
        } else {
            layer.bounds = CGRect(x: 0, y: 0, width: spark.size, height: spark.size)
            layer.backgroundColor = spark.color
        }
        let start = CGPoint(x: spark.origin.x - origin.x, y: spark.origin.y - origin.y)
        let end = CGPoint(
            x: start.x + spark.velocity.dx * spark.life, y: start.y + spark.velocity.dy * spark.life
        )
        layer.position = end
        layer.opacity = 0
        let move = CABasicAnimation(keyPath: "position")
        move.fromValue = start
        move.toValue = end
        let fade = CABasicAnimation(keyPath: "opacity")
        fade.fromValue = 1
        fade.toValue = 0
        let group = CAAnimationGroup()
        group.animations = [move, fade]
        group.duration = spark.life
        layer.add(group, forKey: "spark")
        ringClip.addSublayer(layer)
        DispatchQueue.main.asyncAfter(deadline: .now() + spark.life) {
            layer.removeFromSuperlayer()
        }
    }

    private static func circle(_ radius: Double) -> CGPath {
        CGPath(
            ellipseIn: CGRect(x: -radius, y: -radius, width: radius * 2, height: radius * 2),
            transform: nil)
    }
}
