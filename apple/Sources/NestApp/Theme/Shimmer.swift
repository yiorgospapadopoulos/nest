import SwiftUI

/// A soft highlight sweeping across content while something runs; with Reduce Motion the
/// content is brightened instead.
private struct Shimmer: ViewModifier {
    static let period = 1.8

    let active: Bool
    @Environment(\.reducedMotion) private var reduceMotion

    func body(content: Content) -> some View {
        if !active {
            content
        } else if reduceMotion {
            content.foregroundStyle(Palette.t1)
        } else {
            content.overlay {
                TimelineView(.animation(minimumInterval: 1 / 30)) { context in
                    let time = context.date.timeIntervalSinceReferenceDate
                    // Sweeps from before the leading edge to past the trailing one.
                    let phase = (time.truncatingRemainder(dividingBy: Self.period)) / Self.period
                    let center = -0.4 + phase * 1.8
                    LinearGradient(
                        stops: [
                            .init(color: .clear, location: 0),
                            .init(color: Palette.t1, location: 0.5),
                            .init(color: .clear, location: 1),
                        ],
                        startPoint: UnitPoint(x: center - 0.35, y: 0.5),
                        endPoint: UnitPoint(x: center + 0.35, y: 0.5))
                }
                .mask(content)
                .allowsHitTesting(false)
            }
        }
    }
}

extension View {
    /// Shimmers while `active`.
    func shimmer(_ active: Bool) -> some View {
        modifier(Shimmer(active: active))
    }
}
