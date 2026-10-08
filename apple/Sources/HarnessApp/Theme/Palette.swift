import AppKit
import HarnessKit
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

/// The design tokens as SwiftUI colors, named after the mockup's variables. The glass
/// colors follow the theme: see `GlassPalette`.
enum Palette {
    typealias Tokens = DesignTokens.Colors

    static let t1 = Color(Tokens.Text.primary)
    static let t2 = Color(Tokens.Text.secondary)
    static let t3 = Color(Tokens.Text.tertiary)
    static let hair = Color(Tokens.Line.hairline)
    static let hair2 = Color(Tokens.Line.strong)
    static let fill = Color(Tokens.Fill.subtle)
    static let fill2 = Color(Tokens.Fill.strong)
    static let codeBackground = Color(Tokens.Surface.code)
    static let scrim = Color(Tokens.Surface.scrim)
    static let page = Color(Tokens.Page.base)
    static let approve = Color(Tokens.Signal.approve)
    static let runningRing = Color(Tokens.Signal.runningRing)
    static let attentionGlow = Color(Tokens.Signal.attentionGlow)
    static let addedText = Color(Tokens.Diff.addedText)
    static let removedText = Color(Tokens.Diff.removedText)

    /// Text on the amber badge.
    static let onWaiting = Color(red: 0.169, green: 0.09, blue: 0)
}

extension StatusTone {
    var color: Color { Color(fill) }
    var textColor: Color { Color(text) }

    var soft: Color {
        switch self {
        case .running: Color(DesignTokens.Status.Running.soft)
        case .waiting: Color(DesignTokens.Status.Waiting.soft)
        case .review: Color(DesignTokens.Status.Review.soft)
        case .failed: Color(DesignTokens.Status.Failed.soft)
        case .interrupted: Color(DesignTokens.Status.Interrupted.soft)
        case .done: Color(DesignTokens.Status.Done.soft)
        }
    }
}

/// The colors that follow the user's accent and bubble choice.
struct AccentColors {
    var accent: Color
    var onAccent: Color
    var bubble: Color
    var bubbleText: Color

    /// Selection and drop zone tint.
    var soft: Color { accent.opacity(0.12) }
    /// The focused pane's ring.
    var line: Color { accent.opacity(0.42) }

    init(accent name: AccentName, bubble style: BubbleStyle) {
        let accent = Theme.accent(name)
        self.accent = Color(accent.fill)
        onAccent = Color(accent.on)
        let neutral = style == .neutral
        bubble = Color(neutral ? DesignTokens.Colors.Surface.neutralBubble : accent.fill)
        bubbleText = Color(neutral ? DesignTokens.Colors.Text.primary : accent.on)
    }

    static let graphite = AccentColors(accent: .graphite, bubble: .accent)
}

extension EnvironmentValues {
    @Entry var accentColors = AccentColors.graphite
    /// Snapshots draw glass as flat tinted fills, since offscreen rendering has no backdrop.
    @Entry var flatGlass = false
    /// The window shows the desktop through its glass, so reading surfaces tint denser.
    @Entry var seeThrough = false
    /// The pane sits under a maximized one: its AppKit content (a web view or terminal)
    /// must hide, since transparency alone neither hides it reliably nor stops its clicks.
    @Entry var paneHidden = false
    /// The pane's slot in the workspace: its content lays out to it and never past it.
    @Entry var paneSize: CGSize?
    /// What the pane's header and composer show at the slot's width.
    @Entry var paneFit = PaneFit(width: 600)
    /// Reduce Motion, or a snapshot that must hold still.
    @Entry var reducedMotion = false
    /// Snapshots show controls that otherwise appear on hover, such as Copy.
    @Entry var revealsHoverControls = false
}

/// Type sizes from the tokens.
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
}

extension Font {
    static func ui(_ size: Double, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight)
    }

    static func mono(_ size: Double, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
}
