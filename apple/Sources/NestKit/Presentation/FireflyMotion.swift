import Foundation

// The working animation (B80), "Bold fireflies": three dots in a 16 by 12 point box, each
// drifting, growing and fading on its own ease-in-out loop, as the iPhone's CSS keyframes
// do. A running row adds a band of light sweeping across it. Times are in seconds.

/// One dot at one moment, in the box at size 1.
public struct FireflyPose: Sendable, Hashable {
    /// The dot's centre, from the box's top-left corner.
    public let x: Double
    public let y: Double
    /// Of the dot's 3 point diameter, around its centre.
    public let scale: Double
    public let opacity: Double
}

/// A keyframe of a dot's loop: `at` is the fraction of its period, the rest its
/// translation, scale and opacity there.
struct FireflyKey: Sendable {
    let at: Double
    let dx: Double
    let dy: Double
    let scale: Double
    let opacity: Double
}

/// A dot: its top-left in the box, its period and its keyframes from 0 to 1.
struct Firefly: Sendable {
    let left: Double
    let top: Double
    let period: Double
    let keys: [FireflyKey]
}

public enum FireflyMotion {
    public static let width = 16.0
    public static let height = 12.0
    public static let diameter = 3.0

    /// The box's width at a height, keeping its 4:3 shape.
    public static func width(forHeight height: Double) -> Double {
        height * width / self.height
    }

    static let dots: [Firefly] = [
        Firefly(
            left: 1, top: 5, period: 2.4,
            keys: [
                FireflyKey(at: 0, dx: 0, dy: 0, scale: 1, opacity: 1),
                FireflyKey(at: 0.3, dx: 4, dy: -4, scale: 0.75, opacity: 0.55),
                FireflyKey(at: 0.6, dx: 6, dy: 1, scale: 1.15, opacity: 1),
                FireflyKey(at: 1, dx: 0, dy: 0, scale: 1, opacity: 1),
            ]),
        Firefly(
            left: 7, top: 1, period: 2.9,
            keys: [
                FireflyKey(at: 0, dx: 0, dy: 0, scale: 0.8, opacity: 0.6),
                FireflyKey(at: 0.4, dx: -4, dy: 5, scale: 1.15, opacity: 1),
                FireflyKey(at: 0.7, dx: 3, dy: 6, scale: 0.9, opacity: 0.7),
                FireflyKey(at: 1, dx: 0, dy: 0, scale: 0.8, opacity: 0.6),
            ]),
        Firefly(
            left: 12, top: 8, period: 2.1,
            keys: [
                FireflyKey(at: 0, dx: 0, dy: 0, scale: 1.1, opacity: 1),
                FireflyKey(at: 0.5, dx: -6, dy: -5, scale: 0.8, opacity: 0.55),
                FireflyKey(at: 1, dx: 0, dy: 0, scale: 1.1, opacity: 1),
            ]),
    ]

    /// The three dots at a time; each loops on its own period.
    public static func poses(at time: Double) -> [FireflyPose] {
        dots.map { pose(of: $0, at: time) }
    }

    /// The dots held still, as Reduce Motion draws them: their first keyframes.
    public static let still = poses(at: 0)

    static func pose(of dot: Firefly, at time: Double) -> FireflyPose {
        let progress = Motion.fraction(time, of: dot.period)
        // The last key is at 1, past any progress, so a segment always follows.
        let next = dot.keys.firstIndex { $0.at > progress }!
        let from = dot.keys[next - 1]
        let to = dot.keys[next]
        let eased = Motion.easeInOut((progress - from.at) / (to.at - from.at))
        func blend(_ value: (FireflyKey) -> Double) -> Double {
            value(from) + (value(to) - value(from)) * eased
        }
        return FireflyPose(
            x: dot.left + diameter / 2 + blend(\.dx),
            y: dot.top + diameter / 2 + blend(\.dy),
            scale: blend(\.scale), opacity: blend(\.opacity))
    }
}

/// A status mark's sizes: the fireflies while the tone is running, else the plain dot.
/// Where running and other marks share a list, each takes a slot as wide as the fireflies,
/// the dot centred in it, so the text after them lines up.
public enum StatusMarkMetrics {
    public static let dotSize = 6.0
    public static let fireflyHeight = 9.0
    public static let slotWidth = FireflyMotion.width(forHeight: fireflyHeight)

    public static func animates(_ tone: StatusTone) -> Bool {
        tone == .running
    }
}

/// The band of light across a running row: transparent, the accent at 24%, transparent,
/// half the row wide, sweeping from fully off its left edge to fully off its right.
public enum RowGlow {
    public static let period = 1.8
    /// Of the row's width.
    public static let bandWidth = 0.5
    public static let peakOpacity = 0.24

    /// The band's centre at a time, as a fraction of the row's width: from -0.25, its
    /// right edge at the row's left, to 1.25, its left edge at the row's right.
    public static func center(at time: Double) -> Double {
        let eased = Motion.easeInOut(Motion.fraction(time, of: period))
        return -bandWidth / 2 + eased * (1 + bandWidth)
    }
}

enum Motion {
    /// How far through its loop of `period` seconds a time is, from 0 up to 1; times before
    /// the epoch count forward too.
    static func fraction(_ time: Double, of period: Double) -> Double {
        let wrapped = time.truncatingRemainder(dividingBy: period)
        return (wrapped < 0 ? wrapped + period : wrapped) / period
    }

    /// CSS `ease-in-out`, the cubic Bezier through (0.42, 0) and (0.58, 1): the curve's
    /// height where its horizontal position is `x`, found by halving.
    static func easeInOut(_ x: Double) -> Double {
        func bezier(_ s: Double, _ first: Double, _ second: Double) -> Double {
            let rest = 1 - s
            return 3 * rest * rest * s * first + 3 * rest * s * s * second + s * s * s
        }
        var low = 0.0
        var high = 1.0
        for _ in 0..<40 {
            let middle = (low + high) / 2
            if bezier(middle, 0.42, 0.58) < x {
                low = middle
            } else {
                high = middle
            }
        }
        return bezier((low + high) / 2, 0, 1)
    }
}
