import CoreGraphics
import ImageIO
import NestKit
import SwiftUI

/// The 1 point line along the bottom of the tab strip (B73): the chat background's colours
/// left to right, or the accent colour without one, fading out towards both ends.
struct PhotoLineView: View {
    /// The chat background's image file, if one is chosen.
    let image: String?
    @Environment(\.accentColors) private var accent
    @State private var sampled: (path: String, colors: [Color])?

    var body: some View {
        let colors: [Color] =
            if let image {
                sampled?.path == image ? sampled?.colors ?? [] : []
            } else {
                [accent.accent]
            }
        LinearGradient(
            colors: colors.count == 1 ? colors + colors : colors, startPoint: .leading,
            endPoint: .trailing
        )
        .frame(height: 1)
        .mask {
            LinearGradient(
                stops: [
                    .init(color: .clear, location: 0), .init(color: .black, location: 0.12),
                    .init(color: .black, location: 0.88), .init(color: .clear, location: 1),
                ], startPoint: .leading, endPoint: .trailing)
        }
        .opacity(colors.isEmpty ? 0 : image == nil ? 0.7 : 0.9)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
        .task(id: image) {
            guard let image else { return }
            let colors = await PhotoLineSampler.colors(path: image)
            sampled = (image, colors)
        }
    }
}

/// Reads a small copy of the image off the main thread and samples its colours.
enum PhotoLineSampler {
    /// The small copy's longest side, in pixels; enough for a few bands of colour.
    static let side = 96

    static func colors(path: String) async -> [Color] {
        await Task.detached(priority: .utility) {
            sample(path: path).map {
                Color(
                    red: Double($0.red) / 255, green: Double($0.green) / 255,
                    blue: Double($0.blue) / 255)
            }
        }.value
    }

    private static func sample(path: String) -> [PhotoLine.Color] {
        let url = URL(fileURLWithPath: path)
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: side,
        ]
        guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
            let image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary),
            let space = CGColorSpace(name: CGColorSpace.sRGB)
        else { return [] }
        let width = image.width
        let height = image.height
        var pixels = [UInt8](repeating: 0, count: width * height * 4)
        let drawn = pixels.withUnsafeMutableBytes { buffer -> Bool in
            guard
                let context = CGContext(
                    data: buffer.baseAddress, width: width, height: height, bitsPerComponent: 8,
                    bytesPerRow: width * 4, space: space,
                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
            else { return false }
            context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
            return true
        }
        guard drawn else { return [] }
        Dither.unpremultiply(&pixels)
        return PhotoLine.colors(
            rgba: pixels, width: width, height: height, bands: PhotoLine.bands)
    }
}
