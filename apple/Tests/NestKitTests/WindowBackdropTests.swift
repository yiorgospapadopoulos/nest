import Foundation
import Testing

@testable import NestKit

@Suite struct WindowBackdropTests {
    @Test func theWindowIsSeeThroughUnlessTransparencyIsReduced() {
        #expect(WindowBackdrop.of(reduceTransparency: false) == .desktop)
        #expect(WindowBackdrop.of(reduceTransparency: true) == .opaque)
        #expect(WindowBackdrop.desktop.isSeeThrough)
        #expect(!WindowBackdrop.opaque.isSeeThrough)
    }

    /// In fullscreen nothing is behind the window and macOS reports a placeholder for every
    /// desktop picture, so the window draws its plain color.
    @Test func fullscreenDrawsThePlainWindowColor() {
        #expect(WindowBackdrop.of(reduceTransparency: false, fullScreen: true) == .opaque)
        #expect(WindowBackdrop.of(reduceTransparency: true, fullScreen: true) == .opaque)
        #expect(WindowBackdrop.of(reduceTransparency: false, fullScreen: false) == .desktop)
    }

    /// The opaque window is the see-through tint at full strength: the same color, so Reduce
    /// Transparency and snapshots keep the look.
    @Test func theOpaqueWindowIsTheTintAtFullStrength() {
        let mac = DesignTokens.Colors.Mac.self
        for (tint, opaque) in [
            (mac.window.light, mac.windowOpaque.light), (mac.window.dark, mac.windowOpaque.dark),
        ] {
            #expect(tint.alpha == 0.36)
            #expect(opaque.alpha == 1)
            #expect([tint.red, tint.green, tint.blue] == [opaque.red, opaque.green, opaque.blue])
        }
    }
}
