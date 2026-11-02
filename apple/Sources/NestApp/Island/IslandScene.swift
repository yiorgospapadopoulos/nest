import AppKit
import NestKit

/// Where the island sits in its panel's flipped view, in points.
struct IslandGeometry: Equatable {
    /// The pill below the menu bar, on a screen without a notch (C7).
    var pill: Bool
    /// The notch's edges; the pill's centre gap's.
    var notchMinX: Double
    var notchMaxX: Double
    /// The strip's top and height: the menu bar's height around the notch.
    var top: Double
    var height: Double

    var centerX: Double { (notchMinX + notchMaxX) / 2 }
}

/// What Core Animation shows around the drawn sprites, so the strip, the needs-you glows
/// and their rings change without the app drawing frames.
struct IslandEffects {
    struct Glow: Equatable {
        /// The glow's centre and the part of the strip it may light.
        var center: CGPoint
        var clip: CGRect
        /// The pixie's own opacity as it folds into the +N.
        var alpha: Double
    }

    /// The strip's black shape; the pill's has a faint outline.
    var shape: CGPath?
    var pill = false
    /// The line between the strip and the open list, and its strength.
    var divider = CGRect.zero
    var dividerAlpha = 0.0
    /// By pixie id.
    var glows: [String: Glow] = [:]
    /// The centres of the needs-you badges whose rings grow, by pixie id.
    var rings: [String: CGPoint] = [:]
    /// Where the rings and sparks may show: the strip.
    var ringClip = CGRect.zero
    /// Sleeping z's and sparkles that appeared this frame, to rise and fade on their own.
    var sparks: [Spark] = []

    struct Spark {
        /// The top left of a z, the corner of a sparkle.
        var origin: CGPoint
        /// Points per second.
        var velocity: CGVector
        /// Seconds.
        var life: Double
        var color: CGColor
        var size: Double
        var isZ: Bool
    }
}

/// How soon the island wants its next frame.
enum IslandPace: Equatable {
    /// Something moves across the island: every display frame up to 60 a second.
    case smooth
    /// A pixie hops or spins in its place.
    case hop
    /// Nothing moves until then (milliseconds on the scene's clock).
    case at(Double)
    /// Nothing moves.
    case still
}

/// The island's animation (mockup v11): the strip around the notch, its pixies and their
/// moves, the +N, and the strip growing into the list. Times are in milliseconds and
/// lengths in points, as in the mockup.
@MainActor
final class IslandScene {
    enum Motion: Equatable {
        case idle, asleep, working, done, alert, seen
    }

    struct Member: Hashable {
        var mascot: Mascot
        var color: String
    }

    enum Art: Hashable {
        case pixie(Mascot, color: String)
        case team([Member])
    }

    /// Something drawn on a side: an entry, or the resting Nightshade or Bluebell.
    struct Item {
        var id: String
        var art: Art
        var motion: Motion
        var entry: IslandEntry?
        /// Its sparks' colour.
        var color: String
    }

    private enum Side { case left, right }

    private struct Flight {
        var start: Double
        var x: Double
        var y: Double
    }

    private struct Sprite {
        var art: Art
        var color: String
        var x: Double
        var y: Double
        var side: Side
        var flight: Flight?
        /// When it landed in its place, for the done spin.
        var arrived: Double
        var alpha = 1.0
        var leaving: Double?
    }

    private struct Particle {
        var x: Double
        var y: Double
        /// Points per second.
        var vx = 0.0
        var vy = 0.0
        var life = 1.0
        /// Life lost per second.
        var decay: Double
        var color: CGColor
        var size = 2.0
        /// A trail: drawn under the island, outside its shape.
        var free = false
        var isZ = false
    }

    static let sprite = IslandLayout.sprite
    static let slot = IslandLayout.slot
    static let pad = IslandLayout.pad
    /// The list's width: the notch's, and the wider pill's.
    var listWidth: Double { geometry.pill ? 420 : 360 }
    static let rowHeight = 46.0
    static let visibleRows = 5
    static let listTop = 6.0
    static let listBottom = 12.0
    static let flight = 1300.0

    static let orange = CGColor.hex("#F5A524")
    static let green = CGColor.hex("#2f9e44")
    static let spark = CGColor.hex("#FFE08A")
    static let lilac = CGColor.hex("#c9c3ff")

    var geometry: IslandGeometry
    var reduceMotion = false
    /// The strip, glows and rings are left to `effects` for Core Animation; else they are
    /// drawn with the rest, as offscreen snapshots need.
    var usesLayers = false
    private(set) var effects = IslandEffects()
    /// The list is open: hovered or pinned.
    var wantsOpen = false
    private(set) var state = IslandState.empty
    private(set) var fit = IslandLayout.fit(.empty, left: 0, right: 0, pill: false)
    private var left: [Item] = []
    private var right: [Item] = []

    private var leftWidth = 40.0
    private var rightWidth = 40.0
    /// 0 closed to 1 open.
    private(set) var open = 0.0
    private var sprites: [String: Sprite] = [:]
    private var particles: [Particle] = []
    /// When each sleeping pixie lets out its next z.
    private var nextZ: [String: Double] = [:]
    /// Pixies clicked away, with when: they pop as they leave, if they leave soon after.
    private var popped: [String: Double] = [:]
    private var last: Double?
    /// This frame's length in seconds, for spawns.
    private var frameStep = 0.0

    /// What a click at a point hits, the +N first.
    private(set) var hits: [(rect: CGRect, target: IslandTarget)] = []
    /// The strip in the bar, the island's hover target.
    private(set) var stripRect = CGRect.zero
    /// The list's frame and its fade.
    private(set) var listFrame = CGRect.zero
    private(set) var listAlpha = 0.0
    /// What the last frame drew: the strip alone while the list is closed and nothing flies
    /// under it, else nil for the whole view.
    private(set) var drawnRect: CGRect?
    /// When a pose changes next, so a slow frame rate does not start a hop late.
    private(set) var nextChange: Double?

    init(geometry: IslandGeometry) {
        self.geometry = geometry
    }

    var listHeight: Double {
        Self.listTop + Self.listBottom
            + Self.rowHeight * Double(min(Self.visibleRows, max(1, state.list.count)))
    }

    /// Takes a new state; pixies that are gone fade away, unless a click popped them.
    func update(_ state: IslandState, fit: IslandFit) {
        self.state = state
        self.fit = fit
        left =
            state.nightshade.map { mode in
                [
                    Item(
                        id: "nightshade", art: .pixie(.nightshade, color: IslandArt.nightshade),
                        motion: mode == .working ? .working : mode == .asleep ? .asleep : .idle,
                        entry: nil, color: IslandArt.nightshade)
                ]
            } ?? state.left.map(Self.item)
        right =
            state.restingBluebell
            ? [
                Item(
                    id: "bluebell", art: .pixie(.bluebell, color: IslandArt.bluebell),
                    motion: state.nightshade == .asleep ? .asleep : .idle, entry: nil,
                    color: IslandArt.bluebell)
            ] : state.right.map(Self.item)
    }

    static func item(_ entry: IslandEntry) -> Item {
        let motion: Motion =
            switch entry.status {
            case .working: .working
            case .needsYou, .failed, .interrupted: .alert
            case .seen: .seen
            case .done: .done
            }
        switch entry.figure {
        case .pixie(let pixie):
            return Item(
                id: entry.id, art: .pixie(pixie.mascot, color: pixie.color), motion: motion,
                entry: entry, color: pixie.color)
        case .team(_, let color, let cells):
            let members = cells.map { Member(mascot: $0.pixie.mascot, color: $0.pixie.color) }
            return Item(
                id: entry.id, art: .team(members), motion: motion, entry: entry,
                color: color ?? cells.first?.pixie.color ?? PixieColor.standard)
        }
    }

    /// Everything at rest in its place, as a snapshot shows it.
    func settle(at time: Double) {
        leftWidth = fit.left.width
        rightWidth = fit.right.width
        open = wantsOpen ? 1 : 0
        sprites = [:]
        particles = []
        popped = [:]
        for want in wants() {
            sprites[want.item.id] = Sprite(
                art: want.item.art, color: want.item.color, x: want.x, y: want.y,
                side: want.side, arrived: time - 10_000, alpha: want.hidden ? 0 : 1)
        }
        last = time
    }

    /// A click opened this pixie's chat and it will leave: it pops instead of fading.
    func pop(_ id: String) {
        popped[id] = last ?? 0
    }

    /// The pixie is in its place and has had its landing: a finished one seen in the
    /// focused chat waits for this before it pops.
    func hasLanded(_ id: String) -> Bool {
        guard !reduceMotion, let sprite = sprites[id], let last else { return true }
        return sprite.flight == nil && last - sprite.arrived >= Self.landing
    }

    /// The spin and its sparks, and a beat to see the tick.
    private static let landing = 1200.0

    private struct Want {
        var item: Item
        var side: Side
        var x: Double
        var y: Double
        var hidden: Bool
    }

    private var stripLeft: Double { geometry.notchMinX - leftWidth }
    private var spriteTop: Double {
        geometry.top + ((geometry.height - Self.sprite) / 2).rounded()
    }

    private func wants() -> [Want] {
        let s = Self.sprite
        let pad = Self.pad
        let slot = Self.slot
        let left = stripLeft
        let shownLeft = Double(fit.left.shown)
        let shownRight = Double(fit.right.shown)
        let plusLeft =
            fit.left.countInline ? left + pad + shownLeft * slot - 4 : left + pad + s / 2 - 6
        let plusRight =
            fit.right.countInline
            ? geometry.notchMaxX + pad + shownRight * slot - 2
            : geometry.notchMaxX + pad + s / 2 - 6
        var wants: [Want] = []
        for (index, item) in self.left.enumerated() {
            let hidden = index >= fit.left.shown
            wants.append(
                Want(
                    item: item, side: .left,
                    x: hidden ? plusLeft : left + pad + Double(index) * slot, y: spriteTop,
                    hidden: hidden))
        }
        for (index, item) in right.enumerated() {
            let hidden = index >= fit.right.shown
            wants.append(
                Want(
                    item: item, side: .right,
                    x: hidden ? plusRight : geometry.notchMaxX + pad + Double(index) * slot,
                    y: spriteTop, hidden: hidden))
        }
        return wants
    }

    // MARK: Frame

    private struct Pacer {
        var smooth = false
        var hop = false
        var next = Double.infinity

        mutating func at(_ time: Double) {
            next = min(next, time)
        }

        var pace: IslandPace {
            if smooth { return .smooth }
            if hop { return .hop }
            return next.isFinite ? .at(next) : .still
        }
    }

    private struct Pose {
        var frame = IslandFrame.rest
        var dy = 0.0
        var flip = false
        var scale = 1.0
    }

    /// Steps the animation to `time` and draws it into a flipped context.
    @discardableResult
    func render(in context: CGContext, at time: Double) -> IslandPace {
        let t = time
        let dt = min(0.05, max(0, (t - (last ?? t)) / 1000))
        last = t
        frameStep = dt
        let reduce = reduceMotion
        var pacer = Pacer()
        let s = Self.sprite
        let top = geometry.top
        let height = geometry.height
        hits = []

        let widthStep = reduce ? 1 : min(1, dt * 7)
        leftWidth += (fit.left.width - leftWidth) * widthStep
        rightWidth += (fit.right.width - rightWidth) * widthStep
        if abs(leftWidth - fit.left.width) > 0.05 || abs(rightWidth - fit.right.width) > 0.05 {
            pacer.smooth = true
        } else {
            leftWidth = fit.left.width
            rightWidth = fit.right.width
        }
        let left = stripLeft
        let right = geometry.notchMaxX + rightWidth

        // The strip grows into the list in place.
        let target = wantsOpen ? 1.0 : 0
        open += (target - open) * (reduce ? 1 : min(1, dt * 9))
        if abs(open - target) < 0.002 {
            open = target
        } else {
            pacer.smooth = true
        }
        let p = Self.ease(open)
        let half = listWidth / 2
        let openLeft = min(left, geometry.centerX - half)
        let openRight = max(right, geometry.centerX + half)
        let shapeLeft = left + (openLeft - left) * p
        let shapeRight = right + (openRight - right) * p
        let shapeBottom = top + height + listHeight * p
        let shape: CGPath
        if geometry.pill {
            let radius = min(height / 2, 26) + (20 - min(height / 2, 26)) * p
            let rect = CGRect(
                x: shapeLeft, y: top, width: shapeRight - shapeLeft, height: shapeBottom - top)
            shape = CGPath(
                roundedRect: rect, cornerWidth: min(radius, rect.width / 2),
                cornerHeight: min(radius, rect.height / 2), transform: nil)
        } else {
            shape = Self.notchPath(
                left: shapeLeft, right: shapeRight, bottom: shapeBottom, radius: 12 + 12 * p)
        }
        let divider = CGRect(
            x: shapeLeft + 14, y: top + height, width: shapeRight - shapeLeft - 28, height: 1)
        let dividerAlpha = p > 0.02 ? 0.08 * p : 0
        effects = IslandEffects(
            shape: shape, pill: geometry.pill, divider: divider, dividerAlpha: dividerAlpha)
        if !usesLayers {
            context.setFillColor(.black)
            context.addPath(shape)
            context.fillPath()
            if geometry.pill {
                context.addPath(shape)
                context.setStrokeColor(CGColor(gray: 1, alpha: 0.12))
                context.setLineWidth(1)
                context.strokePath()
            }
            context.setFillColor(CGColor(gray: 1, alpha: dividerAlpha))
            context.fill(divider)
        }
        listFrame = CGRect(
            x: openLeft, y: top + height, width: openRight - openLeft, height: listHeight)
        listAlpha = max(0, (open - 0.45) / 0.55)
        stripRect = CGRect(x: left, y: top, width: right - left, height: height)
        effects.ringClip = stripRect

        context.saveGState()
        context.clip(to: stripRect)
        let wants = wants()
        let wanted = Set(wants.map(\.item.id))
        nextZ = nextZ.filter { wanted.contains($0.key) }
        for (id, sprite) in sprites where !wanted.contains(id) {
            var sprite = sprite
            let pops = popped[id] != nil
            if pops && !reduce {
                burst(
                    x: sprite.x + 14, y: sprite.y + 14, color: sprite.color, count: 22, speed: 2.2)
            }
            if sprite.leaving == nil { sprite.leaving = t }
            if pops || t - (sprite.leaving ?? t) > 300 {
                sprites[id] = nil
                popped[id] = nil
            } else {
                sprites[id] = sprite
                pacer.smooth = true
            }
        }
        popped = popped.filter { t - $0.value < 2000 }

        var flying: [(item: Item, pose: Pose, sprite: Sprite)] = []
        for want in wants {
            let item = want.item
            var sprite =
                sprites[item.id]
                ?? Sprite(
                    art: item.art, color: item.color, x: want.x,
                    y: reduce ? want.y : top - s - 4, side: want.side, arrived: t)
            sprite.art = item.art
            sprite.color = item.color
            sprite.leaving = nil
            if sprite.side != want.side {
                sprite.side = want.side
                if reduce {
                    sprite.x = want.x
                    sprite.y = want.y
                    sprite.arrived = t
                } else {
                    sprite.flight = Flight(start: t, x: sprite.x, y: sprite.y)
                }
            }
            var isFlying = false
            if let flight = sprite.flight {
                let progress = min(1, (t - flight.start) / Self.flight)
                let eased = Self.ease(progress)
                let dip = top + height + 14
                sprite.x = flight.x + (want.x - flight.x) * eased
                sprite.y =
                    flight.y + (want.y - flight.y) * eased
                    + sin(progress * .pi) * (dip - min(flight.y, want.y))
                isFlying = true
                pacer.smooth = true
                trail(from: sprite, dt: dt)
                if progress >= 1 {
                    sprite.flight = nil
                    sprite.arrived = t
                    isFlying = false
                    if item.motion == .done {
                        burst(
                            x: sprite.x + s / 2, y: sprite.y + s / 2, color: item.color,
                            count: 10, speed: 1.2)
                    } else if item.motion == .alert {
                        burst(
                            x: sprite.x + s / 2, y: sprite.y + s / 2, color: "#F5A524", count: 6,
                            speed: 1)
                    }
                }
            } else {
                let step = reduce ? 1 : min(1, dt * 9)
                sprite.x += (want.x - sprite.x) * step
                sprite.y += (want.y - sprite.y) * step
                if abs(want.x - sprite.x) > 0.05 || abs(want.y - sprite.y) > 0.05 {
                    pacer.smooth = true
                } else {
                    sprite.x = want.x
                    sprite.y = want.y
                }
            }
            if isFlying {
                var pose = Pose()
                pose.frame = Int(t / 80) % 2 == 1 ? .flap : .rest
                sprite.alpha = 1
                sprites[item.id] = sprite
                flying.append((item, pose, sprite))
                continue
            }
            let near = abs(sprite.x - want.x) < 3 && abs(sprite.y - want.y) < 3
            let alpha = want.hidden && near ? 0.0 : 1
            sprite.alpha +=
                (alpha - sprite.alpha) * (reduce ? 1 : min(1, dt * (want.hidden ? 8 : 6)))
            if abs(alpha - sprite.alpha) > 0.01 {
                pacer.smooth = true
            } else {
                sprite.alpha = alpha
            }
            sprites[item.id] = sprite
            // One folded into the +N is not drawn, so it neither moves nor sparkles.
            if want.hidden && sprite.alpha < 0.03 { continue }
            let pose = pose(of: item, sprite: sprite, at: t, pacer: &pacer, context: context)
            draw(
                item.art, id: item.id, motion: item.motion, pose: pose, x: sprite.x,
                y: sprite.y + pose.dy,
                at: t, alpha: sprite.alpha,
                scale: pose.scale * (want.hidden ? 0.6 + 0.4 * sprite.alpha : 1),
                pacer: &pacer, in: context)
            if want.hidden { continue }
            guard let entry = item.entry else { continue }
            if item.motion != .working && sprite.alpha > 0.5 {
                badge(item.motion, x: sprite.x + s - 3, y: sprite.y + s - 4, at: t, in: context)
                if usesLayers && item.motion == .alert && !reduce {
                    effects.rings[item.id] = CGPoint(x: sprite.x + s - 3, y: sprite.y + s - 4)
                }
            }
            if item.motion == .working && reduce {
                context.setFillColor(Self.runningDot)
                context.fillEllipse(
                    in: CGRect(x: sprite.x + s - 6, y: sprite.y + s - 7, width: 6, height: 6))
            }
            hits.append(
                (CGRect(x: sprite.x - 1, y: top, width: Self.slot, height: height), .entry(entry)))
        }
        for (id, sprite) in sprites where !wanted.contains(id) {
            guard let leaving = sprite.leaving else { continue }
            let alpha = 1 - (t - leaving) / 300
            if alpha > 0 {
                draw(
                    sprite.art, id: id, motion: .idle, pose: Pose(frame: .flap), x: sprite.x,
                    y: sprite.y - (1 - alpha) * 8, at: t, alpha: alpha, scale: 1,
                    pacer: &pacer, in: context)
            }
        }
        drawParticles(free: false, dt: dt, pacer: &pacer, in: context)
        drawCounts(left: left, in: context)
        context.restoreGState()

        if !geometry.pill {
            // The camera hides whatever passes behind it.
            context.setFillColor(.black)
            context.fill(
                CGRect(
                    x: geometry.notchMinX, y: 0, width: geometry.notchMaxX - geometry.notchMinX,
                    height: top + height))
        } else {
            context.setFillColor(CGColor(gray: 1, alpha: 0.3))
            context.fillEllipse(
                in: CGRect(x: geometry.centerX - 2, y: top + height / 2 - 2, width: 4, height: 4))
        }
        // Flights and their trails go under the island, outside its shape.
        drawParticles(free: true, dt: dt, pacer: &pacer, in: context)
        for (item, pose, sprite) in flying {
            draw(
                item.art, id: item.id, motion: item.motion, pose: pose, x: sprite.x,
                y: sprite.y + pose.dy,
                at: t, alpha: 1, scale: 1, flying: true, pacer: &pacer, in: context)
        }
        particles.removeAll { $0.life <= 0 }
        let under = !flying.isEmpty || particles.contains(where: \.free)
        // As wide as the strip will grow to, so the next frame fits too.
        let farLeft = geometry.notchMinX - max(leftWidth, fit.left.width)
        let farRight = geometry.notchMaxX + max(rightWidth, fit.right.width)
        drawnRect =
            open > 0 || wantsOpen || under
            ? nil
            : CGRect(
                x: farLeft - 8, y: 0, width: farRight - farLeft + 16, height: top + height + 2)
        nextChange = pacer.next.isFinite ? pacer.next : nil
        return pacer.pace
    }

    // MARK: Moves

    private static let runningDot: CGColor = {
        let rgba = StatusTone.running.themedColor.dark
        return CGColor(srgbRed: rgba.red, green: rgba.green, blue: rgba.blue, alpha: rgba.alpha)
    }()

    /// The frame, lift and turn of an item at rest in its place, by its motion; the needs
    /// you glow is drawn here, behind the sprite.
    private func pose(
        of item: Item, sprite: Sprite, at t: Double, pacer: inout Pacer, context: CGContext
    ) -> Pose {
        let reduce = reduceMotion
        let s = Self.sprite
        let unit = s / 14
        var pose = Pose()
        let offset = SpriteMotion.phase(of: item.id) * 3
        switch item.motion {
        case .asleep:
            pose.frame = .blink
            if !reduce {
                let bob = (t + offset).truncatingRemainder(dividingBy: 2200)
                pose.dy = bob < 1100 ? -1 : 0
                pacer.at(t + (bob < 1100 ? 1100 - bob : 2200 - bob))
                // The mockup's odds of a z each frame, as a wait between z's, so the island
                // wakes only to let one out.
                let due = nextZ[item.id] ?? t + Self.wait(rate: 0.012 * 60)
                if t >= due {
                    spawn(
                        Particle(
                            x: sprite.x + s * 0.85, y: sprite.y + s * 0.35, vx: 0.25 * 60,
                            vy: -0.08 * 60, decay: 0.009 * 60, color: Self.lilac, size: 0,
                            isZ: true), pacer: &pacer)
                    nextZ[item.id] = t + Self.wait(rate: 0.012 * 60)
                } else {
                    nextZ[item.id] = due
                }
                pacer.at(nextZ[item.id] ?? due)
            }
        case .idle:
            let cycle = (t + offset).truncatingRemainder(dividingBy: 5200)
            pose.frame = cycle < 160 || (cycle > 2600 && cycle < 2760) ? .blink : .rest
            pacer.at(t + ([160, 2600, 2760, 5200].first { $0 > cycle } ?? 5200) - cycle)
            if !reduce {
                let flutter = (t + offset).truncatingRemainder(dividingBy: 7000)
                if flutter > 6200 {
                    pose.frame = Int(flutter / 90) % 2 == 1 ? .flap : .rest
                    pose.dy = -unit
                    pacer.at(t + 90 - flutter.truncatingRemainder(dividingBy: 90))
                } else {
                    pacer.at(t + 6200 - flutter)
                }
            }
        case .working:
            guard !reduce, case .pixie = item.art else { break }
            let phase = SpriteMotion.phase(of: item.id)
            let frame = SpriteMotion.frame(at: t + phase)
            pose.dy = frame.lifted ? -unit : 0
            pose.frame =
                frame.lifted ? IslandFrame(blinking: frame.blinking, flapping: true) : .rest
            pacer.at(Self.nextStep(t, phase: phase))
        case .done:
            guard !reduce else { break }
            let since = t - sprite.arrived
            if since < 520 {
                pose.flip = Int(since / 130) % 2 == 1
                pose.scale = 1 + 0.12 * sin(since / 520 * .pi)
                pacer.hop = true
            } else {
                let cycle = (since - 520).truncatingRemainder(dividingBy: 2600)
                if cycle > 1200 && cycle < 1360 { pose.frame = .blink }
                pacer.at(t + ([300, 1200, 1360, 2600].first { $0 > cycle } ?? 2600) - cycle)
                // The mockup's occasional sparkles, as many but all while it hops, so the
                // island rests in between.
                if cycle < 300 {
                    pose.dy = -sin(cycle / 300 * .pi) * 1.5 * unit
                    pose.frame = .flap
                    pacer.hop = true
                }
                if cycle < 300 && chance(0.02 * 60 * 2600 / 300) {
                    spawn(
                        Particle(
                            x: sprite.x + 4 + .random(in: 0..<1) * (s - 8),
                            y: sprite.y + 4 + .random(in: 0..<1) * (s - 8), vy: -0.04 * 60,
                            decay: 0.03 * 60, color: Self.spark, size: 1.5),
                        pacer: &pacer)
                }
            }
        case .alert:
            let center = CGPoint(x: sprite.x + s / 2, y: sprite.y + s * 0.55)
            let clip = CGRect(
                x: sprite.x - s * 0.4, y: geometry.top, width: s * 1.8, height: geometry.height)
            if usesLayers {
                effects.glows[item.id] = IslandEffects.Glow(
                    center: center, clip: clip, alpha: sprite.alpha)
            } else {
                drawGlow(at: center, clip: clip, alpha: sprite.alpha, t: t, in: context)
            }
            guard !reduce else { break }
            let cycle = t.truncatingRemainder(dividingBy: 1500)
            if cycle < 600 {
                let jump = cycle.truncatingRemainder(dividingBy: 300) / 300
                pose.dy = -sin(jump * .pi) * 1.5 * unit
                pose.frame = .flap
                pacer.hop = true
            } else if cycle < 700 {
                pose.frame = .blink
            }
            pacer.at(t + ([600, 700, 1500].first { $0 > cycle } ?? 1500) - cycle)
        case .seen:
            guard !reduce else { break }
            let cycle = t.truncatingRemainder(dividingBy: 2400)
            if cycle < 160 { pose.frame = .blink }
            pose.dy = cycle.truncatingRemainder(dividingBy: 1200) < 600 ? 0 : -1
            pacer.at(t + ([160, 600, 1200, 1800, 2400].first { $0 > cycle } ?? 2400) - cycle)
        }
        return pose
    }

    /// The orange glow behind a pixie that needs the user, pulsing unless motion is reduced.
    private func drawGlow(
        at center: CGPoint, clip: CGRect, alpha: Double, t: Double, in context: CGContext
    ) {
        let glow = (reduceMotion ? 0.3 : 0.3 + 0.14 * sin(t / 240)) * alpha
        context.saveGState()
        context.clip(to: clip)
        if let gradient = CGGradient(
            colorsSpace: CGColorSpace(name: CGColorSpace.sRGB),
            colors: [Self.orange.copy(alpha: glow)!, Self.orange.copy(alpha: 0)!] as CFArray,
            locations: [0, 1])
        {
            context.drawRadialGradient(
                gradient, startCenter: center, startRadius: 2, endCenter: center,
                endRadius: Self.sprite * 0.8, options: .drawsBeforeStartLocation)
        }
        context.restoreGState()
    }

    /// The next 170 ms step of a hop with this phase.
    private static func nextStep(_ t: Double, phase: Double) -> Double {
        let step = SpriteMotion.step * 1000
        let into = (t + phase).truncatingRemainder(dividingBy: step)
        return t + step - into + 0.5
    }

    /// A random spawn at `rate` per second over this frame, the mockup's per frame odds
    /// at 60 frames a second.
    private func chance(_ rate: Double) -> Bool {
        Double.random(in: 0..<1) < rate * frameStep
    }

    /// A random wait in milliseconds before the next of something that comes `rate` times a
    /// second on average.
    private static func wait(rate: Double) -> Double {
        -log(1 - Double.random(in: 0..<1)) / rate * 1000
    }

    /// A z or a sparkle: Core Animation moves and fades it, else it is drawn each frame.
    private func spawn(_ particle: Particle, pacer: inout Pacer) {
        guard usesLayers else {
            particles.append(particle)
            pacer.smooth = true
            return
        }
        effects.sparks.append(
            IslandEffects.Spark(
                origin: CGPoint(x: particle.x, y: particle.isZ ? particle.y - 5 : particle.y),
                velocity: CGVector(dx: particle.vx, dy: particle.vy),
                life: 1 / particle.decay, color: particle.color, size: particle.size,
                isZ: particle.isZ))
    }

    // MARK: Drawing

    private func draw(
        _ art: Art, id: String, motion: Motion, pose: Pose, x: Double, y: Double, at t: Double,
        alpha: Double, scale: Double, flying: Bool = false, pacer: inout Pacer,
        in context: CGContext
    ) {
        let s = Self.sprite
        switch art {
        case .pixie(let mascot, let color):
            guard let image = IslandArt.image(mascot, color: color, frame: pose.frame) else {
                return
            }
            IslandArt.draw(
                image, in: context, rect: CGRect(x: snap(x), y: snap(y), width: s, height: s),
                flip: pose.flip, scale: scale, alpha: alpha)
        case .team(let members):
            let half = s / 2
            for (index, member) in members.prefix(4).enumerated() {
                var frame = IslandFrame.rest
                var dy = 0.0
                if flying {
                    frame = pose.frame
                } else if motion == .working && !reduceMotion {
                    let phase = SpriteMotion.phase(of: "\(id)\(index)")
                    let hop = SpriteMotion.frame(at: t + phase)
                    dy = hop.lifted ? -s / 28 : 0
                    frame = hop.lifted ? IslandFrame(blinking: hop.blinking, flapping: true) : .rest
                    pacer.at(Self.nextStep(t, phase: phase))
                }
                guard let image = IslandArt.image(member.mascot, color: member.color, frame: frame)
                else { continue }
                let rect = CGRect(
                    x: snap(x + Double(index % 2) * half),
                    y: snap(y + Double(index / 2) * half + dy), width: half, height: half)
                IslandArt.draw(
                    image, in: context, rect: rect, flip: pose.flip, scale: scale, alpha: alpha)
            }
        }
    }

    /// Whole device pixels, so the sprites stay crisp.
    private func snap(_ value: Double) -> Double {
        (value * 2).rounded() / 2
    }

    /// The done tick, or the "!" of one that needs the user with its ring while it waits.
    private func badge(_ motion: Motion, x: Double, y: Double, at t: Double, in context: CGContext)
    {
        let warn = motion != .done
        context.saveGState()
        context.translateBy(x: x, y: y)
        if motion == .alert && !reduceMotion && !usesLayers {
            let cycle = t.truncatingRemainder(dividingBy: 1400) / 1400
            context.setStrokeColor(Self.orange.copy(alpha: 1 - cycle)!)
            context.setLineWidth(1.3)
            let radius = 4.5 + cycle * 6
            context.strokeEllipse(
                in: CGRect(x: -radius, y: -radius, width: radius * 2, height: radius * 2))
        }
        context.setFillColor(warn ? Self.orange : Self.green)
        context.fillEllipse(in: CGRect(x: -4.5, y: -4.5, width: 9, height: 9))
        context.setFillColor(.white)
        if warn {
            context.fill(CGRect(x: -0.7, y: -3, width: 1.5, height: 3.6))
            context.fill(CGRect(x: -0.7, y: 1.4, width: 1.5, height: 1.5))
        } else {
            for (a, c) in [(0, 2), (1, 3), (2, 2), (3, 1), (4, 0)] {
                context.fill(
                    CGRect(
                        x: -3 + Double(a) * 1.2, y: -2 + Double(c) * 1.1, width: 1.4, height: 1.4))
            }
        }
        context.restoreGState()
    }

    /// Each side's +N: beside its pixies when it fits, else a small pill on top of the
    /// first; orange when a hidden one needs the user.
    private func drawCounts(left: Double, in context: CGContext) {
        let s = Self.sprite
        let top = geometry.top
        let sy = spriteTop
        let sides: [(fit: IslandSideFit, start: Double, inlineGap: Double)] = [
            (fit.left, left, 3), (fit.right, geometry.notchMaxX, 5),
        ]
        for (side, start, gap) in sides where side.more > 0 {
            let text = "+\(side.more)"
            let warn = side.moreIsAlert
            if side.countInline {
                let pixel = 1.25
                let x = start + Self.pad + Double(side.shown) * Self.slot + gap
                IslandArt.text(
                    text, at: CGPoint(x: x, y: sy + s / 2 + 4 - 5 * pixel), pixel: pixel,
                    color: warn ? Self.orange : CGColor.hex("#d8d8de"), in: context)
                let width = IslandArt.width(of: text, pixel: pixel)
                hits.insert(
                    (
                        CGRect(x: x - 3, y: top, width: width + 6, height: geometry.height),
                        .more
                    ), at: 0)
            } else {
                let x = start + Self.pad + s / 2
                let y = top + 1
                let width = IslandArt.width(of: text, pixel: 1) + 6
                context.setFillColor(warn ? Self.orange : CGColor.hex("#3a3a44"))
                context.addPath(
                    CGPath(
                        roundedRect: CGRect(x: x, y: y, width: width, height: 11),
                        cornerWidth: 5.5, cornerHeight: 5.5, transform: nil))
                context.fillPath()
                IslandArt.text(
                    text, at: CGPoint(x: x + 3, y: y + 3), pixel: 1,
                    color: warn ? CGColor.hex("#1a1204") : CGColor.hex("#f0f0f4"), in: context)
                hits.insert((CGRect(x: x, y: top, width: width, height: 12), .more), at: 0)
            }
        }
    }

    // MARK: Particles

    private func burst(x: Double, y: Double, color: String, count: Int, speed: Double) {
        let ink = CGColor.hex(color)
        for index in 0..<count {
            let angle = Double.random(in: 0..<(2 * .pi))
            let velocity = (0.5 + .random(in: 0..<1)) * speed * 60
            particles.append(
                Particle(
                    x: x, y: y, vx: cos(angle) * velocity, vy: sin(angle) * velocity * 0.5,
                    decay: 0.07 * 60, color: index % 3 != 0 ? Self.spark : ink))
        }
    }

    /// Two specks a frame at 60 frames a second behind a flying sprite, which fade at once.
    private func trail(from sprite: Sprite, dt: Double) {
        let s = Self.sprite
        let ink = CGColor.hex(sprite.color)
        let count = 120 * dt
        var spawn = Int(count)
        if Double.random(in: 0..<1) < count - Double(spawn) { spawn += 1 }
        for _ in 0..<spawn {
            particles.append(
                Particle(
                    x: sprite.x + s / 2 + .random(in: -4..<4),
                    y: sprite.y + s * 0.55 + .random(in: -3..<3), decay: 0.035 * 60,
                    color: Bool.random() ? ink : Self.spark, free: true))
        }
    }

    private func drawParticles(
        free: Bool, dt: Double, pacer: inout Pacer, in context: CGContext
    ) {
        for index in particles.indices where particles[index].free == free {
            var particle = particles[index]
            particle.x += particle.vx * dt
            particle.y += particle.vy * dt
            particle.life -= particle.decay * dt
            particles[index] = particle
            guard particle.life > 0 else { continue }
            pacer.smooth = true
            let color = particle.color.copy(alpha: (particle.color.alpha) * particle.life)!
            if particle.isZ {
                IslandArt.text(
                    "z", at: CGPoint(x: particle.x, y: particle.y - 5), pixel: 1, color: color,
                    in: context)
            } else {
                context.setFillColor(color)
                context.fill(
                    CGRect(
                        x: particle.x.rounded(), y: particle.y.rounded(), width: particle.size,
                        height: particle.size))
            }
        }
    }

    // MARK: Shapes

    /// The notch grown into wings: outer top corners flaring into the bar, round bottom
    /// corners.
    static func notchPath(left: Double, right: Double, bottom: Double, radius: Double) -> CGPath {
        let path = CGMutablePath()
        path.move(to: CGPoint(x: left - 6, y: 0))
        path.addQuadCurve(to: CGPoint(x: left, y: 6), control: CGPoint(x: left, y: 0))
        path.addLine(to: CGPoint(x: left, y: bottom - radius))
        path.addQuadCurve(
            to: CGPoint(x: left + radius, y: bottom), control: CGPoint(x: left, y: bottom))
        path.addLine(to: CGPoint(x: right - radius, y: bottom))
        path.addQuadCurve(
            to: CGPoint(x: right, y: bottom - radius), control: CGPoint(x: right, y: bottom))
        path.addLine(to: CGPoint(x: right, y: 6))
        path.addQuadCurve(to: CGPoint(x: right + 6, y: 0), control: CGPoint(x: right, y: 0))
        path.closeSubpath()
        return path
    }

    static func ease(_ p: Double) -> Double {
        p < 0.5 ? 2 * p * p : 1 - pow(-2 * p + 2, 2) / 2
    }
}
