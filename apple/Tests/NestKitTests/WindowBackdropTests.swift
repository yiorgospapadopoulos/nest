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
}
