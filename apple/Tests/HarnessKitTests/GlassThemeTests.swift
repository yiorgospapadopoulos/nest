import Foundation
import Testing

@testable import HarnessKit

@Suite struct GlassThemeTests {
    typealias Themes = DesignTokens.GlassTheme

    @Test func findsEveryThemeByItsID() {
        for style in Themes.all {
            #expect(Theme.glass(named: style.name) == style)
        }
        #expect(Themes.all.map(\.name) == ["clear", "frosted", "smoke", "bluegrey", "deep"])
    }

    @Test func anUnknownIDFallsBackToClear() {
        #expect(Theme.glass(named: "sand") == Themes.clear)
        #expect(Theme.glass(named: "") == Themes.clear)
        #expect(Themes.default == Themes.clear)
    }

    @Test func theWindowIsSeeThroughUnlessTransparencyIsReduced() {
        #expect(WindowBackdrop.of(reduceTransparency: false) == .desktop)
        #expect(WindowBackdrop.of(reduceTransparency: true) == .opaque)
        #expect(WindowBackdrop.desktop.isSeeThrough)
        #expect(!WindowBackdrop.opaque.isSeeThrough)
    }

    /// Clear matches the preview: no window-wide blur, so the desktop shows crisply
    /// between panels, while the panels keep regular Liquid Glass. (Window blur under
    /// regular glass was too frosted; the see-through glass variant was too clear.)
    @Test func onlyClearHasNoWindowBlur() {
        #expect(WindowGlass.of(Themes.clear).material == WindowGlass.Material.none)
        for style in Themes.all where style != Themes.clear {
            #expect(WindowGlass.of(style).material != WindowGlass.Material.none)
        }
    }

    /// In fullscreen nothing is behind the window, so the desktop wallpaper is drawn in it:
    /// blurred as the window blur would be, except for Clear, which has none.
    @Test func theFullscreenWallpaperIsBlurredLikeTheWindow() {
        #expect(WindowGlass.of(Themes.clear).wallpaperBlur == 0)
        #expect(WindowGlass.of(Themes.frosted).wallpaperBlur == Themes.frosted.backdrop.blur)
        #expect(WindowGlass.of(Themes.smoke).wallpaperBlur == Themes.smoke.backdrop.blur)
    }

    @Test func fullscreenShowsTheWallpaperUnlessTransparencyIsReduced() {
        #expect(WindowBackdrop.of(reduceTransparency: false, fullScreen: true) == .wallpaper)
        #expect(WindowBackdrop.of(reduceTransparency: true, fullScreen: true) == .opaque)
        #expect(WindowBackdrop.of(reduceTransparency: false, fullScreen: false) == .desktop)
        #expect(WindowBackdrop.wallpaper.isSeeThrough)
    }

    @Test func heavierBlurPicksADenserMaterial() {
        #expect(WindowGlass.of(Themes.smoke).material == .medium)
        #expect(WindowGlass.of(Themes.bluegrey).material == .medium)
        #expect(WindowGlass.of(Themes.deep).material == .heavy)
        #expect(WindowGlass.of(Themes.frosted).material == .heavy)
    }

    @Test func clearHasNoFrostAndFrostedTheMost() {
        let clear = WindowGlass.of(Themes.clear)
        #expect(clear.frost.light.alpha == 0)
        #expect(clear.frost.dark.alpha == 0)
        let frosted = WindowGlass.of(Themes.frosted)
        #expect(frosted.frost.light.alpha == WindowGlass.maxFrost)
        #expect(frosted.frost.dark.alpha == WindowGlass.maxFrost)
        let order = Themes.all.sorted { $0.backdrop.blur < $1.backdrop.blur }
        let frosts = order.map { WindowGlass.of($0).frost.light.alpha }
        #expect(frosts == frosts.sorted())
        #expect(Set(frosts).count == frosts.count)
    }

    @Test func frostIsTheThemesSurfaceColor() {
        let deep = Themes.deep
        let frost = WindowGlass.of(deep).frost
        let surface = deep.colors.surface
        #expect(frost.light.red == surface.light.red)
        #expect(frost.light.green == surface.light.green)
        #expect(frost.light.blue == surface.light.blue)
        #expect(frost.dark.blue == surface.dark.blue)
        #expect(abs(frost.dark.alpha - WindowGlass.maxFrost * 34 / 38) < 1e-9)
    }

    @Test func blurOutsideTheThemesRangeIsClamped() {
        #expect(WindowGlass.frost(blur: 0) == 0)
        #expect(WindowGlass.frost(blur: 200) == WindowGlass.maxFrost)
        #expect(WindowGlass.material(blur: 0) == WindowGlass.Material.none)
        #expect(WindowGlass.material(blur: 20) == .medium)
        #expect(WindowGlass.material(blur: 200) == .heavy)
    }

    @Test func clearReadsOnItsPlainTintAsInThePreview() {
        #expect(Themes.clear.readingTint == Themes.clear.colors.tint)
    }

    @Test func readingTintSitsBetweenTintAndSurface() {
        for style in Themes.all where style != Themes.clear {
            let tint = style.colors.tint
            let surface = style.colors.surface
            let reading = style.readingTint
            for (from, to, mixed) in [
                (tint.light, surface.light, reading.light), (tint.dark, surface.dark, reading.dark),
            ] {
                #expect(abs(mixed.alpha - (from.alpha + (to.alpha - from.alpha) / 3)) < 1e-9)
                #expect(abs(mixed.red - (from.red + (to.red - from.red) / 3)) < 1e-9)
                #expect(abs(mixed.green - (from.green + (to.green - from.green) / 3)) < 1e-9)
                #expect(abs(mixed.blue - (from.blue + (to.blue - from.blue) / 3)) < 1e-9)
            }
        }
    }

    @Test func mixingAndAlphaKeepTheOtherChannels() {
        let black = RGBA(red: 0, green: 0, blue: 0, alpha: 0)
        let white = RGBA(red: 1, green: 1, blue: 1, alpha: 1)
        let grey = RGBA(red: 0.5, green: 0.5, blue: 0.5, alpha: 0.5)
        #expect(black.mixed(toward: white, by: 0.5) == grey)
        #expect(black.mixed(toward: white, by: 0) == black)
        #expect(white.withAlpha(0.3) == RGBA(red: 1, green: 1, blue: 1, alpha: 0.3))
        let themed = ThemedColor(light: white, dark: black)
        let faded = ThemedColor(light: white.withAlpha(0.2), dark: black.withAlpha(0.2))
        #expect(themed.withAlpha(0.2) == faded)
    }
}
