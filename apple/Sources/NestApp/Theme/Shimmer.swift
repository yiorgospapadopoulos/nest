import NestKit
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
                // Sweeps from before the leading edge to past the trailing one.
                LightSweep(
                    color: Palette.t1,
                    sweep: Sweep(
                        from: -0.4, to: 1.4, halfWidth: 0.35, period: Self.period, eases: false)
                )
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
