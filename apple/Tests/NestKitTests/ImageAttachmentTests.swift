import CoreGraphics
import Foundation
import ImageIO
import Testing
import UniformTypeIdentifiers

@testable import NestKit

/// An image of this size encoded as `type`.
private func image(width: Int, height: Int, as type: UTType) throws -> Data {
    let context = try #require(
        CGContext(
            data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: 0,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
    context.setFillColor(CGColor(red: 0.2, green: 0.4, blue: 0.8, alpha: 1))
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    let picture = try #require(context.makeImage())
    let data = NSMutableData()
    let destination = try #require(
        CGImageDestinationCreateWithData(data, type.identifier as CFString, 1, nil))
    CGImageDestinationAddImage(destination, picture, nil)
    #expect(CGImageDestinationFinalize(destination))
    return data as Data
}

/// The pixel size and type of encoded image data.
private func size(of data: Data) throws -> (width: Int, height: Int, type: String) {
    let source = try #require(CGImageSourceCreateWithData(data as CFData, nil))
    let properties = try #require(
        CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any])
    return (
        properties[kCGImagePropertyPixelWidth] as? Int ?? 0,
        properties[kCGImagePropertyPixelHeight] as? Int ?? 0,
        CGImageSourceGetType(source) as String? ?? ""
    )
}

/// Images are prepared as Claude Code prepares them: HEIC becomes JPEG, types Claude
/// cannot read become PNG, and a long edge over 2000 pixels is scaled down (B59).
@Suite struct ImageAttachmentTests {
    @Test func aSmallSupportedImageIsSentAsItIs() throws {
        let png = try image(width: 40, height: 30, as: .png)
        let prepared = try #require(ImageAttachment.prepare(png, filename: "shot.png"))
        #expect(prepared.data == png)
        #expect(prepared.filename == "shot.png")
        #expect(prepared.mediaType == "image/png")
    }

    @Test func heicBecomesJPEG() throws {
        let heic = try image(width: 64, height: 48, as: .heic)
        let prepared = try #require(ImageAttachment.prepare(heic, filename: "IMG_0001.HEIC"))
        #expect(prepared.filename == "IMG_0001.jpeg")
        #expect(prepared.mediaType == "image/jpeg")
        let shape = try size(of: prepared.data)
        #expect((shape.width, shape.height) == (64, 48))
        #expect(shape.type == UTType.jpeg.identifier)
    }

    @Test func tiffBecomesPNG() throws {
        let tiff = try image(width: 20, height: 20, as: .tiff)
        let prepared = try #require(ImageAttachment.prepare(tiff, filename: "Pasted image"))
        #expect(prepared.filename == "Pasted image.png")
        #expect(prepared.mediaType == "image/png")
        #expect(try size(of: prepared.data).type == UTType.png.identifier)
    }

    @Test func aLargeImageIsScaledToTheLongEdgeLimit() throws {
        let wide = try image(width: 3000, height: 1500, as: .png)
        let prepared = try #require(ImageAttachment.prepare(wide, filename: "wide.png"))
        let shape = try size(of: prepared.data)
        #expect((shape.width, shape.height) == (2000, 1000))
        #expect(prepared.filename == "wide.png")

        let tall = try image(width: 1200, height: 2400, as: .jpeg)
        let scaled = try #require(ImageAttachment.prepare(tall, filename: "tall.jpeg"))
        let tallShape = try size(of: scaled.data)
        #expect((tallShape.width, tallShape.height) == (1000, 2000))
        #expect(scaled.mediaType == "image/jpeg")
        #expect(scaled.filename == "tall.jpeg")
    }

    /// A large GIF loses its animation to be scaled, as a PNG.
    @Test func aLargeGIFIsScaledAsPNG() throws {
        let gif = try image(width: 2400, height: 100, as: .gif)
        let prepared = try #require(ImageAttachment.prepare(gif, filename: "anim.gif"))
        #expect(prepared.filename == "anim.png")
        #expect(try size(of: prepared.data).width == 2000)
        let small = try image(width: 24, height: 10, as: .gif)
        #expect(ImageAttachment.prepare(small, filename: "a.gif")?.data == small)
    }

    @Test func otherFilesAreNotImages() {
        #expect(ImageAttachment.prepare(Data("hello".utf8), filename: "notes.txt") == nil)
        #expect(ImageAttachment.prepare(Data(), filename: "empty.png") == nil)
    }

    @Test func thumbnailsAreSmallPNGs() throws {
        let photo = try image(width: 800, height: 400, as: .heic)
        let thumbnail = try #require(ImageAttachment.thumbnail(photo))
        let shape = try size(of: thumbnail)
        #expect((shape.width, shape.height) == (ImageAttachment.thumbnailEdge, 48))
        #expect(shape.type == UTType.png.identifier)
        #expect(ImageAttachment.thumbnail(Data("x".utf8)) == nil)
    }
}

@Suite struct PreparedAttachmentTests {
    @Test func aFileIsReadAndPreparedWithItsThumbnail() async throws {
        let url = FileManager.default.temporaryDirectory.appending(path: "\(UUID()).heic")
        try image(width: 2200, height: 1100, as: .heic).write(to: url)
        defer { try? FileManager.default.removeItem(at: url) }
        let prepared = try await AttachmentFile.prepare(url)
        #expect(prepared.filename == url.deletingPathExtension().lastPathComponent + ".jpeg")
        #expect(prepared.mediaType == "image/jpeg")
        #expect(try size(of: prepared.data).width == 2000)
        #expect(prepared.thumbnail != nil)
    }

    @Test func otherFilesKeepTheirBytesAndType() async throws {
        let url = FileManager.default.temporaryDirectory.appending(path: "\(UUID()).txt")
        try Data("notes".utf8).write(to: url)
        defer { try? FileManager.default.removeItem(at: url) }
        let prepared = try await AttachmentFile.prepare(url)
        #expect(prepared.data == Data("notes".utf8))
        #expect(prepared.mediaType == "text/plain")
        #expect(prepared.thumbnail == nil)

        let odd = FileManager.default.temporaryDirectory.appending(path: "\(UUID()).zzqq")
        try Data([1]).write(to: odd)
        defer { try? FileManager.default.removeItem(at: odd) }
        #expect(try await AttachmentFile.prepare(odd).mediaType == "application/octet-stream")
    }

    @Test func pastedDataIsPreparedAndLimited() async throws {
        let png = try image(width: 10, height: 10, as: .tiff)
        let prepared = try await AttachmentFile.prepare(data: png, filename: "Pasted image")
        #expect(prepared.filename == "Pasted image.png")
        #expect(prepared.thumbnail != nil)

        let huge = Data(count: AttachmentFile.maximumSize + 1)
        await #expect(throws: AttachmentFileError.tooLarge) {
            _ = try await AttachmentFile.prepare(data: huge, filename: "x.png")
        }
        let text = try await AttachmentFile.prepare(data: Data("a".utf8), filename: "a")
        #expect(text.mediaType == "application/octet-stream")
    }

    @Test func uploadSendsThePreparedFile() async throws {
        let api = FakeAPI()
        let url = FileManager.default.temporaryDirectory.appending(path: "\(UUID()).tiff")
        try image(width: 10, height: 10, as: .tiff).write(to: url)
        defer { try? FileManager.default.removeItem(at: url) }
        let attachment = try await AttachmentFile.upload(url, with: api)
        #expect(attachment.mediaType == "image/png")
        #expect(attachment.filename.hasSuffix(".png"))
    }
}

/// What Cmd+V in the composer pastes (B59): copied image files, else image data with no
/// text beside it, else the text.
@Suite struct ImagePasteTests {
    let png = "public.png"
    let text = "public.utf8-plain-text"

    @Test func imageFilesAreAttached() {
        let photo = URL(fileURLWithPath: "/tmp/a.HEIC")
        let notes = URL(fileURLWithPath: "/tmp/b.txt")
        #expect(
            ImagePaste.choice(types: ["public.file-url", text], fileURLs: [photo, notes])
                == .files([photo]))
        // Other files paste as their names, as before.
        #expect(ImagePaste.choice(types: [text], fileURLs: [notes]) == .text)
    }

    @Test func imageDataIsAttachedUnlessTextComesWithIt() {
        #expect(ImagePaste.choice(types: ["public.tiff", png], fileURLs: []) == .data(type: png))
        #expect(
            ImagePaste.choice(types: ["public.tiff"], fileURLs: []) == .data(type: "public.tiff"))
        #expect(
            ImagePaste.choice(types: ["com.adobe.photoshop-image"], fileURLs: [])
                == .data(type: "com.adobe.photoshop-image"))
        // A spreadsheet's copy holds a picture of the cells beside their text.
        #expect(ImagePaste.choice(types: [text, "public.tiff"], fileURLs: []) == .text)
        #expect(ImagePaste.choice(types: ["public.rtf"], fileURLs: []) == .text)
        #expect(ImagePaste.choice(types: [], fileURLs: []) == .text)
    }

    @Test func pastedImagesAreNamedByType() {
        #expect(ImagePaste.filename(type: png) == "Pasted image.png")
        #expect(ImagePaste.filename(type: "public.jpeg") == "Pasted image.jpeg")
        #expect(ImagePaste.filename(type: "no.such.type") == "Pasted image")
    }
}
