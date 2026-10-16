import AppKit
import NestKit
import SwiftUI

extension NSColor {
    /// A color that follows the drawing appearance, light or dark. AppKit resolves it on
    /// whichever thread draws, hence the nonisolated provider.
    convenience init(_ themed: ThemedColor) {
        self.init(name: nil) { @Sendable appearance in
            let dark = appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
            let rgba = dark ? themed.dark : themed.light
            return NSColor(
                srgbRed: rgba.red, green: rgba.green, blue: rgba.blue, alpha: rgba.alpha)
        }
    }
}

extension Color {
    /// A color that follows the window's light or dark appearance.
    init(_ themed: ThemedColor) {
        self.init(nsColor: NSColor(themed))
    }

    init(_ rgba: RGBA) {
        self.init(.sRGB, red: rgba.red, green: rgba.green, blue: rgba.blue, opacity: rgba.alpha)
    }
}

/// The Mac look's colors, the one place views take them from. Each follows the window's
/// light or dark appearance by itself; only the accent is a choice (`AccentColors`).
enum Palette {
    typealias Mac = DesignTokens.Colors.Mac

    /// The window's tint over the desktop's blur.
    static let window = Color(Mac.window)
    /// The window's tint at full strength: fullscreen, Reduce Transparency and offscreen
    /// snapshots.
    static let windowOpaque = Color(Mac.windowOpaque)
    /// Over the blurred chat background image under the window's chrome.
    static let backdropTint = Color(Mac.backdropTint)
    /// Sidebar, right panel and other side surfaces: darker than the panes.
    static let side = Color(Mac.side)
    /// The board and other reading surfaces: the window's base.
    static let pane = Color(Mac.pane)
    /// A chat, terminal or browser pane: a soft card in light, the base in dark.
    static let chatPane = Color(Mac.chatPane)
    /// Sheets, popovers, menus, the palette and floating banners.
    static let sheet = Color(Mac.sheet)
    /// A selected row, tab or segment with the default accent; see `AccentColors.selection`.
    static let selection = Color(Mac.selection)
    /// The composer's field.
    static let composer = Color(Mac.composer)
    /// Cards, inline code, fields and soft buttons.
    static let soft = Color(Mac.soft)
    /// Hovered rows and buttons.
    static let hover = Color(Mac.hover)
    /// The user's message and the tracks of bars.
    static let raised = Color(Mac.raised)
    /// 1 point lines between areas and sections.
    static let divider = Color(Mac.divider)
    /// The faint lines behind panes; see `scanlines()`.
    static let scanline = Color(Mac.scanline)
    /// Text that matters: titles, messages, values.
    static let t1 = Color(Mac.textPrimary)
    /// Most other text: subtitles, tool calls, buttons without a fill.
    static let t2 = Color(Mac.textSecondary)
    /// Labels, metadata, times and icons.
    static let t3 = Color(Mac.textTertiary)
    /// File paths and links.
    static let link = Color(Mac.link)

    /// Dims the window behind a sheet.
    static let scrim = Color(DesignTokens.Colors.Surface.scrim)
    /// Added and removed lines of a diff, readable on their tinted rows.
    static let addedText = Color(DesignTokens.Colors.Diff.addedText)
    static let removedText = Color(DesignTokens.Colors.Diff.removedText)
    /// The amber glow of a background tab that needs the user (the tab strip's look before
    /// B36; the restyled strip uses a thin `StatusTone.waiting` outline instead).
    static let attentionGlow = Color(DesignTokens.Colors.Signal.attentionGlow)
}

extension StatusTone {
    /// The tone's dot and its quiet word.
    var color: Color { Color(themedColor) }
    /// A faint wash of the tone, for the few fills that need one, such as a drop target or
    /// an error row; status itself is a dot and a word, never a tinted pill.
    var soft: Color { color.opacity(0.14) }
}

/// The colors that follow the user's accent: primary buttons, selection and focus. The
/// default accent, graphite, is the look's own button and selection colors.
struct AccentColors {
    /// The primary button's fill.
    var accent: Color
    /// Text and icons on the primary button.
    var onAccent: Color
    /// Selected rows, tabs and segments.
    var selection: Color
    /// Focus rings and drop targets.
    var focus: Color

    init(accent name: AccentName) {
        if name == .graphite {
            accent = Color(Palette.Mac.button)
            onAccent = Color(Palette.Mac.buttonText)
            selection = Palette.selection
            focus = Palette.t3
        } else {
            let colors = Theme.accent(name)
            accent = Color(colors.fill)
            onAccent = Color(colors.on)
            selection = accent.opacity(0.16)
            focus = accent.opacity(0.6)
        }
    }

    static let graphite = AccentColors(accent: .graphite)
}

extension EnvironmentValues {
    @Entry var accentColors = AccentColors.graphite
    /// Offscreen snapshots: nothing is behind the window, so it draws opaque, and AppKit
    /// views that cannot render offscreen are left out.
    @Entry var offscreen = false
    /// The pane sits under a maximized one: its AppKit content (a web view or terminal)
    /// must hide, since transparency alone neither hides it reliably nor stops its clicks.
    @Entry var paneHidden = false
    /// The pane's slot in the workspace: its content lays out to it and never past it.
    @Entry var paneSize: CGSize?
    /// What the pane's header and composer show at the slot's width.
    @Entry var paneFit = PaneFit(width: 600)
    /// Reduce Motion, a snapshot that must hold still, or a window nobody can see:
    /// continuous animations stop.
    @Entry var reducedMotion = false
    /// Snapshots show controls that otherwise appear on hover, such as Copy.
    @Entry var revealsHoverControls = false
}

/// Type sizes from the tokens. The look's text: `ui` for controls and lists, `reading`
/// for transcript text, `meta` for labels, times and mono code, `button` for buttons and
/// chips.
enum TypeSize {
    typealias Size = DesignTokens.Typography.Size
    static let micro = Size.micro
    static let caption = Size.caption
    static let label = Size.label
    static let small = Size.small
    static let callout = Size.callout
    static let body = Size.body
    static let subhead = Size.subhead
    static let headline = Size.headline

    static let ui = Size.small
    static let reading = Size.callout
    static let meta = Size.caption
    static let button = Size.label
}

/// Corner radii of the look, in points.
enum Radius {
    typealias Tokens = DesignTokens.Radius
    /// Inline code and other small chips.
    static let chip = Tokens.macChip
    /// Buttons and segments.
    static let button = Tokens.macButton
    /// List rows and tabs.
    static let row = Tokens.macRow
    /// Soft-fill cards.
    static let card = Tokens.macCard
    /// The user's message.
    static let bubble = Tokens.macBubble
    /// Sheets, popovers and the palette.
    static let sheet = Tokens.macSheet
}

/// Fixed heights of the look, in points.
enum Metrics {
    typealias Tokens = DesignTokens.Spacing
    /// The project tab strip.
    static let stripHeight = Tokens.macStripHeight
    /// A pane's or column's header.
    static let headerHeight = Tokens.macHeaderHeight
    /// A list row.
    static let rowHeight = Tokens.macRowHeight
    /// A small button.
    static let buttonHeight = Tokens.macButtonHeight
    /// Every project tab's widest width (B60): about 16 characters of its name at the
    /// tab's size, with the icon, the status and the close button; longer names truncate.
    static let projectTabWidth = 180.0
    /// The narrowest a project tab gets when the window is too narrow for every tab at
    /// full width: the tabs shrink together, keeping one width, down to this.
    static let projectTabMinWidth = 56.0
    /// One scanline every this many points.
    static let scanlinePeriod = Tokens.macScanlinePeriod
}

extension Shape where Self == RoundedRectangle {
    /// The continuous rounded rectangle every rounded element uses.
    static func rounded(_ radius: Double) -> RoundedRectangle {
        RoundedRectangle(cornerRadius: radius, style: .continuous)
    }
}

extension Font {
    static func ui(_ size: Double, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight)
    }

    static func mono(_ size: Double, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
}
