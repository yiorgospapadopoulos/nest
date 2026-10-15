import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

/// An attachment ready to upload: its bytes, name and media type, with a small PNG of an
/// image for the composer's chip.
public struct PreparedAttachment: Sendable, Hashable {
    public var data: Data
    public var filename: String
    public var mediaType: String
    public var thumbnail: Data?
}

/// Images are sent as Claude Code sends them (B59): HEIC becomes JPEG, types Claude
/// cannot read become PNG, and a long edge over 2000 pixels is scaled down.
public enum ImageAttachment {
    public static let maxEdge = 2000
    /// The composer chip's thumbnail, in pixels.
    public static let thumbnailEdge = 96
    /// Image types Claude reads as they are, with their media types.
    static let readable: [String: String] = [
        UTType.png.identifier: "image/png", UTType.jpeg.identifier: "image/jpeg",
        UTType.gif.identifier: "image/gif", UTType.webP.identifier: "image/webp",
    ]

    /// What an image is converted to: its type, media type and filename extension.
    private struct Format {
        let type: UTType
        let mediaType: String
        let fileExtension: String

        static let jpeg = Format(type: .jpeg, mediaType: "image/jpeg", fileExtension: "jpeg")
        static let png = Format(type: .png, mediaType: "image/png", fileExtension: "png")
    }

    /// The image as it should be sent; nil when the data is not an image.
    public static func prepare(_ data: Data, filename: String) -> PreparedAttachment? {
        guard let source = imageSource(data), let type = CGImageSourceGetType(source) as String?,
            let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil)
                as? [CFString: Any]
        else { return nil }
        let large = [kCGImagePropertyPixelWidth, kCGImagePropertyPixelHeight].contains {
            (properties[$0] as? Int).map { $0 > maxEdge } == true
        }
        if let mediaType = readable[type], !large {
            return PreparedAttachment(
                data: data, filename: filename, mediaType: mediaType, thumbnail: nil)
        }
        let isPhoto =
            type == UTType.jpeg.identifier || UTType(type)?.conforms(to: .heic) == true
            || UTType(type)?.conforms(to: .heif) == true
        let target = isPhoto ? Format.jpeg : Format.png
        let image =
            large
            ? scaled(source, to: maxEdge)
            : CGImageSourceCreateImageAtIndex(source, 0, nil)
        guard let image, let encoded = encode(image, as: target.type) else { return nil }
        return PreparedAttachment(
            data: encoded, filename: renamed(filename, from: type, to: target),
            mediaType: target.mediaType, thumbnail: nil)
    }

    /// A PNG at most `thumbnailEdge` pixels on its long edge; nil when not an image.
    public static func thumbnail(_ data: Data) -> Data? {
        guard let source = imageSource(data), let image = scaled(source, to: thumbnailEdge)
        else { return nil }
        return encode(image, as: .png)
    }

    private static func imageSource(_ data: Data) -> CGImageSource? {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
            CGImageSourceGetCount(source) > 0
        else { return nil }
        return source
    }

    /// The first frame scaled so its long edge is `edge`, turned upright.
    private static func scaled(_ source: CGImageSource, to edge: Int) -> CGImage? {
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: edge,
        ]
        return CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary)
    }

    private static func encode(_ image: CGImage, as type: UTType) -> Data? {
        let data = NSMutableData()
        let destination = CGImageDestinationCreateWithData(
            data, type.identifier as CFString, 1, nil)
        guard let destination else { return nil }
        let options: [CFString: Any] = [kCGImageDestinationLossyCompressionQuality: 0.85]
        CGImageDestinationAddImage(destination, image, options as CFDictionary)
        return CGImageDestinationFinalize(destination) ? data as Data : nil
    }

    /// The name with the new type's extension: "IMG_1.HEIC" becomes "IMG_1.jpeg", and a
    /// name without one gets it ("Pasted image.png"). Kept when the type is unchanged.
    private static func renamed(_ filename: String, from type: String, to target: Format)
        -> String
    {
        guard type != target.type.identifier else { return filename }
        let name = filename as NSString
        let known = UTType(filenameExtension: name.pathExtension).map { !$0.isDynamic } ?? false
        let base = known ? name.deletingPathExtension : filename
        return "\(base).\(target.fileExtension)"
    }
}

/// What Cmd+V in the composer pastes (B59).
public enum ImagePaste {
    public enum Choice: Sendable, Hashable {
        /// Copied image files, attached like dropped ones.
        case files([URL])
        /// Image data of this pasteboard type, attached as a new file.
        case data(type: String)
        /// The field pastes as usual.
        case text
    }

    /// Image types preferred when the pasteboard holds several.
    static let preferred = [
        UTType.png, .jpeg, .heic, .heif, .tiff, .gif, .webP,
    ].map(\.identifier)

    /// Copied image files first; else image data, unless text comes with it (a copy from a
    /// spreadsheet or a document holds a picture of the text too); else the text.
    public static func choice(types: [String], fileURLs: [URL]) -> Choice {
        let images = fileURLs.filter {
            UTType(filenameExtension: $0.pathExtension)?.conforms(to: .image) == true
        }
        if !images.isEmpty {
            return .files(images)
        }
        guard !types.contains(UTType.utf8PlainText.identifier) else { return .text }
        let type =
            preferred.first(where: types.contains)
            ?? types.first { UTType($0)?.conforms(to: .image) == true }
        return type.map { .data(type: $0) } ?? .text
    }

    /// "Pasted image.png" for the pasted type.
    public static func filename(type: String) -> String {
        let name = "Pasted image"
        return UTType(type)?.preferredFilenameExtension.map { "\(name).\($0)" } ?? name
    }
}
