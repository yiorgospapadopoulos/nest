import NestKit
import SwiftUI

/// What the window shows behind its content: over the desktop, the look's tint on the
/// window's behind-window blur (`SeeThroughWindow`); in fullscreen, with Reduce
/// Transparency or offscreen, the tint at full strength. The whole window is this one
/// slab: the areas inside it are only a shade apart. With a chat background image, the
/// same in every case: the image under the whole window, heavily blurred, under a deep
/// tint of the base, which the chrome shows; the workspace lays its own view of the image
/// over it (`ChatBackdrop`).
struct WindowBackground: View {
    let backdrop: WindowBackdrop
    var image: String?

    var body: some View {
        Group {
            if let image {
                ZStack {
                    Palette.windowOpaque
                    WindowAlignedImage(path: image, blur: ChatBackground.chromeBlur)
                    Palette.backdropTint
                }
            } else {
                switch backdrop {
                case .desktop:
                    Palette.window
                case .opaque:
                    Palette.windowOpaque
                }
            }
        }
        .ignoresSafeArea()
        .allowsHitTesting(false)
    }
}

/// Faint horizontal lines, 1 point every `Metrics.scanlinePeriod`, drawn as one path on
/// whole points so they stay crisp; plain drawing, so offscreen snapshots show them too.
struct Scanlines: View {
    var body: some View {
        Canvas(rendersAsynchronously: false) { context, size in
            let period = Metrics.scanlinePeriod
            var path = Path()
            var y = 0.0
            while y < size.height {
                path.addRect(CGRect(x: 0, y: y, width: size.width, height: 1))
                y += period
            }
            context.fill(path, with: .color(Palette.scanline), style: FillStyle(antialiased: false))
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

extension View {
    /// Sidebar, right panel and other side areas: a shade lighter than the window, square,
    /// meeting their neighbours at a `Separator`.
    func sideSurface() -> some View {
        background(Palette.side)
    }

    /// Chat panes, the board and other reading areas: a shade darker than the window, over
    /// the scanlines, square, meeting their neighbours at a `Separator`.
    func paneSurface() -> some View {
        background { Scanlines().background(Palette.pane) }
    }

    /// The scanlines alone, behind content that already sits on a pane surface.
    func scanlines() -> some View {
        background { Scanlines() }
    }

    /// A soft-fill container: cards, the approval card, board cards, inline fields. No
    /// border and no shadow.
    func softFill(radius: Double = Radius.card) -> some View {
        background(Palette.soft, in: .rounded(radius))
    }

    /// Sheets, popovers, menus, the palette, banners and toasts, which float over the
    /// window's content: the opaque sheet color, a 1 point divider edge and a soft shadow.
    func sheetSurface(radius: Double = Radius.sheet) -> some View {
        modifier(SheetSurface(radius: radius))
    }
}

private struct SheetSurface: ViewModifier {
    let radius: Double

    func body(content: Content) -> some View {
        let shape = RoundedRectangle.rounded(radius)
        content
            .background {
                shape.fill(Palette.sheet).shadow(color: .black.opacity(0.16), radius: 16, y: 6)
            }
            .overlay(shape.strokeBorder(Palette.divider, lineWidth: 1).allowsHitTesting(false))
    }
}
