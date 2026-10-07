import AppKit
import HarnessKit
import SwiftUI

/// The active glass theme as SwiftUI values. Views read it from the environment, so a
/// theme picked in Settings applies at once.
struct GlassPalette {
    let style: GlassStyle
    /// Panels and panes.
    let tint: Color
    /// Transcript panes and the composer over the see-through desktop.
    let reading: Color
    /// Menus, popovers, sheets and selected segments.
    let surface: Color
    /// Board columns, option rows and inset fields.
    let subtle: Color
    let stroke: Color
    let highlight: Color
    let rim: Color
    let shadow: Color
    let strip: Color
    let shell: Color
    let window: WindowGlass
    let frost: Color

    var radius: GlassRadius { style.radius }
    var spacing: GlassSpacing { style.spacing }
    /// Sheets sit a little rounder than panels, and the palette between the two.
    var sheetRadius: Double { radius.panel + 4 }
    var paletteRadius: Double { radius.panel + 2 }

    private init(_ style: GlassStyle) {
        self.style = style
        let colors = style.colors
        tint = Color(colors.tint)
        reading = Color(style.readingTint)
        surface = Color(colors.surface)
        subtle = Color(colors.surfaceSubtle)
        stroke = Color(colors.stroke)
        highlight = Color(colors.highlight)
        rim = Color(colors.rim)
        shadow = Color(colors.shadowColor)
        strip = Color(colors.strip)
        shell = Color(colors.shell)
        window = WindowGlass.of(style)
        frost = Color(window.frost)
    }

    /// Built once per theme, so views compare equal values between renders.
    private static let all = Dictionary(
        uniqueKeysWithValues: DesignTokens.GlassTheme.all.map { ($0.name, GlassPalette($0)) })

    static func of(_ style: GlassStyle) -> GlassPalette {
        all[style.name] ?? GlassPalette(style)
    }

    static let standard = of(DesignTokens.GlassTheme.default)

    /// A control's shape: a pill, or Smoke's rounded rectangle. A radius larger than half
    /// the height draws a pill.
    var control: RoundedRectangle {
        RoundedRectangle(cornerRadius: radius.control, style: .continuous)
    }

    func rounded(_ radius: Double) -> RoundedRectangle {
        RoundedRectangle(cornerRadius: radius, style: .continuous)
    }
}

extension EnvironmentValues {
    @Entry var glass = GlassPalette.standard
}

/// The glass strengths of the mockup's `.gl`, `.gl2` and `.gl3`.
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

    func color(in glass: GlassPalette, seeThrough: Bool) -> Color {
        switch self {
        case .regular: glass.tint
        case .strong: glass.surface
        case .clear: glass.subtle
        case .reading: seeThrough ? glass.reading : glass.tint
        }
    }
}

/// Liquid Glass in a shape with the theme's tint, edges and depth. Offscreen snapshots,
/// which have no backdrop, draw a flat tinted fill over a stand-in for the glass's own
/// frosting; Reduce Transparency draws it over the opaque page color.
struct PanelGlass<S: InsettableShape>: ViewModifier {
    let shape: S
    let tint: GlassTint
    let interactive: Bool
    /// Casts the theme's panel shadow.
    var raised = true
    @Environment(\.glass) private var glass
    @Environment(\.flatGlass) private var flat
    @Environment(\.seeThrough) private var seeThrough
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    func body(content: Content) -> some View {
        let fill = tint.color(in: glass, seeThrough: seeThrough)
        Group {
            if flat || reduceTransparency {
                content
                    .background(shape.fill(fill))
                    .background(shape.fill(reduceTransparency ? Palette.page : Self.frosting))
            } else {
                content.glassEffect(liquid(fill), in: shape)
            }
        }
        .overlay(GlassEdges(shape: shape))
        .background {
            if raised {
                GlassDepth(shape: shape, shadow: glass.style.shadow.panel)
            }
        }
    }

    /// Offscreen stand-in for the system glass's own frosting under the tint.
    static var frosting: Color { Palette.page.opacity(0.3) }

    private func liquid(_ fill: Color) -> Glass {
        let base: Glass = tint == .clear ? .clear.tint(fill) : .regular.tint(fill)
        return interactive ? base.interactive() : base
    }
}

/// The theme's edges: a border, a specular highlight along the top and a rim along the
/// bottom, as the mockup's `inset 0 1px 0` shadows.
struct GlassEdges<S: InsettableShape>: View {
    let shape: S
    @Environment(\.glass) private var glass

    var body: some View {
        let reach = max(glass.radius.item, 8)
        ZStack {
            shape.strokeBorder(glass.stroke, lineWidth: 1)
            shape.inset(by: 1).strokeBorder(glass.highlight, lineWidth: 1)
                .mask(alignment: .top) { fade(from: .top).frame(height: reach) }
            shape.inset(by: 1).strokeBorder(glass.rim, lineWidth: 1)
                .mask(alignment: .bottom) { fade(from: .bottom).frame(height: reach) }
        }
        .allowsHitTesting(false)
    }

    private func fade(from edge: UnitPoint) -> LinearGradient {
        LinearGradient(
            colors: [.black, .clear], startPoint: edge,
            endPoint: edge == .top ? .bottom : .top)
    }
}

/// A theme shadow drawn only outside its shape, as CSS box shadows are, so it never
/// darkens the translucent glass above it. A negative spread shrinks the shadow.
struct GlassDepth<S: InsettableShape>: View {
    let shape: S
    let shadow: GlassShadow
    @Environment(\.glass) private var glass

    var body: some View {
        let reach = shadow.blur + abs(shadow.y) + 8
        // The shrunken fill stays inside the shape, where the mask hides it; only its
        // shadow shows.
        shape.inset(by: max(-shadow.spread, 0))
            .fill(.black)
            .shadow(color: glass.shadow, radius: shadow.blur / 2, y: shadow.y)
            .mask {
                ZStack {
                    Rectangle().padding(-reach)
                    shape.fill(.black).blendMode(.destinationOut)
                }
                .compositingGroup()
            }
            .allowsHitTesting(false)
    }
}

extension View {
    func panelGlass(
        radius: Double, tint: GlassTint = .regular, interactive: Bool = false,
        raised: Bool = true
    ) -> some View {
        modifier(
            PanelGlass(
                shape: RoundedRectangle(cornerRadius: radius, style: .continuous), tint: tint,
                interactive: interactive, raised: raised))
    }

    /// Sheets, popovers and the palette: strong glass with a dense tint, so text over a
    /// busy window stays readable.
    func sheetGlass(radius: Double) -> some View {
        modifier(SheetGlass(shape: RoundedRectangle(cornerRadius: radius, style: .continuous)))
    }

    /// Floating chips such as toasts: strong glass in the theme's control shape.
    func controlGlass(tint: GlassTint = .strong) -> some View {
        modifier(ControlGlass(tint: tint))
    }
}

struct ControlGlass: ViewModifier {
    let tint: GlassTint
    @Environment(\.glass) private var glass

    func body(content: Content) -> some View {
        content.modifier(
            PanelGlass(shape: glass.control, tint: tint, interactive: false, raised: false))
    }
}

struct SheetGlass<S: InsettableShape>: ViewModifier {
    let shape: S
    @Environment(\.glass) private var glass
    @Environment(\.flatGlass) private var flat
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    func body(content: Content) -> some View {
        Group {
            if flat || reduceTransparency {
                // No backdrop offscreen: the page color stands in for the blur.
                content
                    .background(shape.fill(glass.surface))
                    .background(shape.fill(Palette.page.opacity(reduceTransparency ? 1 : 0.85)))
            } else {
                content
                    .background(shape.fill(glass.surface))
                    .glassEffect(.regular, in: shape)
            }
        }
        .overlay(GlassEdges(shape: shape))
    }
}

/// What the window shows behind its glass: over the desktop, the theme's frost wash on
/// the window's behind-window blur; with Reduce Transparency, the opaque page. Snapshots
/// draw a sample desktop under the frost, since they have no real desktop.
struct WindowBackground: View {
    let backdrop: WindowBackdrop
    @Environment(\.glass) private var glass
    @Environment(\.flatGlass) private var flat

    var body: some View {
        switch backdrop {
        case .desktop:
            ZStack {
                #if DEBUG
                    if flat {
                        SampleDesktop()
                    }
                #endif
                glass.frost
            }
            .ignoresSafeArea()
            .allowsHitTesting(false)
        case .wallpaper:
            ZStack {
                DesktopWallpaper(blur: glass.window.wallpaperBlur)
                glass.frost
            }
            .ignoresSafeArea()
            .allowsHitTesting(false)
        case .opaque:
            Palette.page.ignoresSafeArea()
        }
    }
}

/// The current desktop picture of the main screen, for a fullscreen window, which has
/// nothing behind it; the page color when macOS does not give one.
private struct DesktopWallpaper: View {
    let blur: Double
    @State private var image: NSImage?

    var body: some View {
        GeometryReader { geometry in
            if let image {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFill()
                    .frame(width: geometry.size.width, height: geometry.size.height)
                    .blur(radius: blur, opaque: true)
                    .clipped()
            } else {
                Palette.page
            }
        }
        .task {
            guard let screen = NSScreen.main,
                let url = NSWorkspace.shared.desktopImageURL(for: screen)
            else { return }
            image = NSImage(contentsOf: url)
        }
    }
}
