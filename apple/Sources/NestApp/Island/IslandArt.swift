import AppKit
import NestKit

/// A sprite's look on the island: one frame of a mascot in a pixie's colour.
struct IslandFrame: Hashable {
    var blinking = false
    /// Wings beating: the outer wing cells are left out.
    var flapping = false

    static let rest = IslandFrame()
    static let blink = IslandFrame(blinking: true)
    static let flap = IslandFrame(flapping: true)
}

/// The island's sprites as 14 by 14 pixel images, drawn scaled without smoothing, and its
/// pixel font for the +N and the sleeping z's.
@MainActor
enum IslandArt {
    private static var images: [String: CGImage] = [:]

    /// The violet and blue of the resting Nightshade and Bluebell.
    static let nightshade = "#8B7CF6"
    static let bluebell = "#0090FF"

    /// The frame's image; row 0 is the image's top.
    static func image(_ mascot: Mascot, color: String, frame: IslandFrame) -> CGImage? {
        let key = "\(mascot.rawValue)|\(color)|\(frame.blinking)|\(frame.flapping)"
        if let image = images[key] { return image }
        let rows = mascot.rows
        let size = rows.count
        guard size > 0,
            let context = CGContext(
                data: nil, width: size, height: size, bitsPerComponent: 8, bytesPerRow: 0,
                space: CGColorSpace(name: CGColorSpace.sRGB)!,
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
        else { return nil }
        for (y, row) in rows.enumerated() {
            for (x, code) in row.enumerated() {
                if frame.flapping && code == "*" && (x < 2 || x > size - 3) { continue }
                guard
                    let ink = SpriteTones.ink(of: code, color: color, blinking: frame.blinking),
                    let rgba = PixieColor.rgba(ink.hex)
                else { continue }
                context.setFillColor(
                    CGColor(
                        srgbRed: rgba.red, green: rgba.green, blue: rgba.blue,
                        alpha: ink.opacity))
                context.fill(CGRect(x: x, y: size - 1 - y, width: 1, height: 1))
            }
        }
        let image = context.makeImage()
        images[key] = image
        return image
    }

    /// Draws an image upright into a flipped context at `rect`, mirrored when `flip`.
    static func draw(
        _ image: CGImage, in context: CGContext, rect: CGRect, flip: Bool = false,
        scale: Double = 1, alpha: Double = 1
    ) {
        context.saveGState()
        context.setAlpha(alpha)
        context.interpolationQuality = .none
        context.translateBy(x: rect.midX, y: rect.midY)
        context.scaleBy(x: (flip ? -1 : 1) * scale, y: -scale)
        context.draw(
            image,
            in: CGRect(
                x: -rect.width / 2, y: -rect.height / 2, width: rect.width, height: rect.height))
        context.restoreGState()
    }

    // MARK: Pixel font

    /// Five rows of four cells per character, as the mockup's pixel font draws them.
    private static let glyphs: [Character: [String]] = [
        "0": [".##.", "#..#", "#..#", "#..#", ".##."],
        "1": [".##.", "..#.", "..#.", "..#.", ".###"],
        "2": ["###.", "...#", ".##.", "#...", "####"],
        "3": ["###.", "...#", ".##.", "...#", "###."],
        "4": ["#..#", "#..#", "####", "...#", "...#"],
        "5": ["####", "#...", "###.", "...#", "###."],
        "6": [".##.", "#...", "###.", "#..#", ".##."],
        "7": ["####", "...#", "..#.", ".#..", ".#.."],
        "8": [".##.", "#..#", ".##.", "#..#", ".##."],
        "9": [".##.", "#..#", ".###", "...#", ".##."],
        "+": ["...", ".#.", "###", ".#.", "..."],
        "z": ["....", "####", "..#.", ".#..", "####"],
    ]

    /// A sleeping z at two pixels a cell, for a layer of 4 by 5 points.
    static func z(color: CGColor) -> CGImage? {
        guard
            let context = CGContext(
                data: nil, width: 8, height: 10, bitsPerComponent: 8, bytesPerRow: 0,
                space: CGColorSpace(name: CGColorSpace.sRGB)!,
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
        else { return nil }
        context.translateBy(x: 0, y: 10)
        context.scaleBy(x: 1, y: -1)
        text("z", at: .zero, pixel: 2, color: color, in: context)
        return context.makeImage()
    }

    /// The text's width at `pixel` points per cell, one cell between characters.
    static func width(of text: String, pixel: Double) -> Double {
        let cells = text.compactMap { glyphs[$0]?.first?.count }
        guard !cells.isEmpty else { return 0 }
        return Double(cells.reduce(0, +) + cells.count - 1) * pixel
    }

    /// Draws the text with its top left at `origin`.
    static func text(
        _ text: String, at origin: CGPoint, pixel: Double, color: CGColor, in context: CGContext
    ) {
        context.setFillColor(color)
        var x = origin.x
        for character in text {
            guard let rows = glyphs[character] else { continue }
            for (y, row) in rows.enumerated() {
                for (column, cell) in row.enumerated() where cell == "#" {
                    context.fill(
                        CGRect(
                            x: x + Double(column) * pixel, y: origin.y + Double(y) * pixel,
                            width: pixel, height: pixel))
                }
            }
            x += Double((rows.first?.count ?? 0) + 1) * pixel
        }
    }
}

extension CGColor {
    /// `#RRGGBB` at an opacity; the standard violet for anything else.
    static func hex(_ hex: String, alpha: Double = 1) -> CGColor {
        let rgba = PixieColor.rgba(hex) ?? PixieColor.rgba(PixieColor.standard)!
        return CGColor(srgbRed: rgba.red, green: rgba.green, blue: rgba.blue, alpha: alpha)
    }
}
