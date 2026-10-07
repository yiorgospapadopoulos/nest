import HarnessKit
import SwiftUI

/// The mockup's three glass strengths.
enum GlassTint {
    /// Main panels and panes.
    case regular
    /// Menus, popovers and floating chips.
    case strong
    /// Board columns.
    case clear
    /// Panes, where the transcript is read: as regular, but denser over the see-through
    /// desktop so text stays readable over busy windows.
    case reading

    func color(seeThrough: Bool) -> Color {
        switch self {
        case .regular: Palette.glassRegular
        case .strong: Palette.glassStrong
        case .clear: Palette.glassClear
        case .reading: seeThrough ? Palette.glassStrong : Palette.glassRegular
        }
    }
}

/// Liquid Glass in a shape; a flat tinted fill with the glass edge when rendering
/// offscreen, and over the opaque page color with Reduce Transparency.
struct PanelGlass<S: Shape>: ViewModifier {
    let shape: S
    let tint: GlassTint
    let interactive: Bool
    @Environment(\.flatGlass) private var flat
    @Environment(\.seeThrough) private var seeThrough
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    func body(content: Content) -> some View {
        if flat || reduceTransparency {
            content
                .background(shape.fill(tint.color(seeThrough: seeThrough)))
                .background(shape.fill(reduceTransparency ? Palette.page : .clear))
                .overlay(shape.stroke(Palette.glassBorder, lineWidth: 1))
        } else {
            content.glassEffect(glass, in: shape)
        }
    }

    private var glass: Glass {
        let base: Glass =
            switch tint {
            case .regular: .regular.tint(Palette.glassClear)
            case .strong: .regular.tint(Palette.glassRegular)
            case .clear: .clear
            case .reading: .regular.tint(seeThrough ? Palette.glassRegular : Palette.glassClear)
            }
        return interactive ? base.interactive() : base
    }
}

extension View {
    func panelGlass(
        radius: Double, tint: GlassTint = .regular, interactive: Bool = false
    ) -> some View {
        modifier(
            PanelGlass(
                shape: RoundedRectangle(cornerRadius: radius, style: .continuous), tint: tint,
                interactive: interactive))
    }

    /// Sheets, popovers and the palette: strong glass with a dense tint, so text over a
    /// busy window stays readable.
    func sheetGlass(radius: Double) -> some View {
        modifier(SheetGlass(shape: RoundedRectangle(cornerRadius: radius, style: .continuous)))
    }

    func capsuleGlass(tint: GlassTint = .strong) -> some View {
        modifier(PanelGlass(shape: Capsule(), tint: tint, interactive: false))
    }
}

struct SheetGlass<S: Shape>: ViewModifier {
    let shape: S
    @Environment(\.flatGlass) private var flat
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    func body(content: Content) -> some View {
        if flat || reduceTransparency {
            // No backdrop offscreen: the page color stands in for the blur.
            content
                .background(shape.fill(Palette.glassStrong))
                .background(shape.fill(Palette.page.opacity(reduceTransparency ? 1 : 0.85)))
                .overlay(shape.stroke(Palette.glassBorder, lineWidth: 1))
        } else {
            content
                .background(shape.fill(Palette.glassStrong))
                .glassEffect(.regular, in: shape)
        }
    }
}

/// What the window shows behind its glass: nothing of its own over the desktop (the
/// window's behind-window blur shows through), a painted wallpaper, or the opaque page
/// with Reduce Transparency. Snapshots draw a sample desktop for the see-through choice.
struct WindowBackground: View {
    let backdrop: WindowBackdrop
    @Environment(\.flatGlass) private var flat

    var body: some View {
        switch backdrop {
        case .desktop:
            #if DEBUG
                if flat {
                    SampleDesktop()
                }
            #endif
        case .painted(let name):
            Wallpaper(name: name)
        case .opaque:
            Palette.page.ignoresSafeArea()
        }
    }
}

/// The window's wallpaper: a base color, three soft glows and three orbs behind the glass.
struct Wallpaper: View {
    let name: WallpaperName

    var body: some View {
        if let style = Theme.wallpaper(name) {
            painted(style)
        }
    }

    private func painted(_ style: WallpaperStyle) -> some View {
        GeometryReader { geometry in
            let size = geometry.size
            ZStack(alignment: .topLeading) {
                Color(style.base)
                ForEach(Array(style.stops.enumerated()), id: \.offset) { _, stop in
                    glow(stop, in: size)
                }
                ForEach(Array(orbs(style).enumerated()), id: \.offset) { _, orb in
                    orb.view(in: size)
                }
            }
        }
        .ignoresSafeArea()
        .allowsHitTesting(false)
    }

    private func glow(_ stop: WallpaperStop, in size: CGSize) -> some View {
        let color = Color(stop.color)
        return Rectangle()
            .fill(
                EllipticalGradient(
                    colors: [color, color.opacity(0)], center: .center, startRadiusFraction: 0,
                    endRadiusFraction: stop.fade * 0.5)
            )
            .frame(width: 2 * stop.radiusX * size.width, height: 2 * stop.radiusY * size.height)
            .position(x: stop.centerX * size.width, y: stop.centerY * size.height)
    }

    /// The mockup's orbs, placed for a 1440 by 900 window and scaled to the real one.
    private func orbs(_ style: WallpaperStyle) -> [Orb] {
        let order: [Int] =
            switch name {
            case .stone, .desktop: [1, 2, 0]
            case .sage: [2, 1, 0]
            case .sky: [1, 0, 2]
            case .slate: [0, 1, 2]
            }
        let colors = order.map { Color(style.stops[$0].color) }
        return [
            Orb(x: -80, y: 420, size: 340, angle: 140, from: colors[0], to: colors[1]),
            Orb(x: 1080, y: -90, size: 420, angle: 200, from: colors[2], to: colors[0]),
            Orb(x: 640, y: 640, size: 300, angle: 160, from: colors[1], to: colors[2]),
        ]
    }
}

private struct Orb {
    let x: Double
    let y: Double
    let size: Double
    let angle: Double
    let from: Color
    let to: Color

    func view(in window: CGSize) -> some View {
        let scaleX = window.width / 1440
        let scaleY = window.height / 900
        let diameter = size * min(scaleX, scaleY)
        let radians = (angle - 90) * .pi / 180
        let start = UnitPoint(x: 0.5 - cos(radians) / 2, y: 0.5 - sin(radians) / 2)
        let end = UnitPoint(x: 0.5 + cos(radians) / 2, y: 0.5 + sin(radians) / 2)
        return Circle()
            .fill(LinearGradient(colors: [from, to], startPoint: start, endPoint: end))
            .opacity(0.8)
            .mask(
                RadialGradient(
                    colors: [.black, .black, .clear], center: .center, startRadius: 0,
                    endRadius: diameter / 2)
            )
            .frame(width: diameter, height: diameter)
            .position(x: x * scaleX + diameter / 2, y: y * scaleY + diameter / 2)
    }
}
