import AppKit
import CoreImage
import ImageIO
import NestKit
import SwiftUI
import UniformTypeIdentifiers

/// The chat background (B39, the approved design's): the chosen image with the approved design's dither at the
/// chosen grain, laid under the whole window. The window's chrome shows it heavily blurred under a deep
/// tint (`WindowBackground`); the workspace shows it here, aligned with the window's, over
/// the base color: sharp at the empty visibility while no pane is open, hazed at the
/// "with chats" visibility once panes are open.
struct ChatBackdrop: View {
    @Environment(Shell.self) private var shell
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        if let background = shell.chatBackground {
            let hasChats = shell.workspaceHasChats
            let visibility = background.visibility(hasChats: hasChats)
            let easing = ChatBackdrop.easing(ChatBackground.transition(hasChats: hasChats))
            let hazed = ChatBackground.workspaceBlur(hasChats: true)
            Palette.windowOpaque
                .overlay {
                    // The sharp image fades out over the haze, as a blur coming in.
                    ZStack {
                        WindowAlignedImage(
                            path: background.image, blur: hazed, grain: background.grain)
                        WindowAlignedImage(path: background.image, grain: background.grain)
                            .opacity(hasChats ? 0 : 1)
                    }
                    .opacity(visibility)
                    .animation(reduceMotion ? nil : easing, value: hasChats)
                    .animation(reduceMotion ? nil : easing, value: visibility)
                }
                .clipped()
                .allowsHitTesting(false)
                .accessibilityHidden(true)
        }
    }

    /// the approved design's ease-out.
    static func easing(_ duration: Double) -> Animation {
        .timingCurve(0.22, 1, 0.36, 1, duration: duration)
    }
}

extension View {
    /// The chat background behind a workspace, when one is chosen.
    func chatBackdrop() -> some View {
        background { ChatBackdrop() }
    }

    /// Names the window's coordinate space and hands its size down, so the backdrop's
    /// layers line up wherever they are drawn.
    func windowSpace(size: CGSize) -> some View {
        coordinateSpace(.named(WindowSpace.name)).environment(\.windowSize, size)
    }
}

enum WindowSpace {
    static let name = "nest.window"
}

extension EnvironmentValues {
    /// The window's content size, for layers aligned with the whole window.
    @Entry var windowSize: CGSize = .zero
}

/// The image laid out over the whole window, showing only the part under this view, so
/// the chrome's blurred copy and the workspace's line up. `blur` is in window points;
/// `grain` is the share of the dithered copy over the plain one.
struct WindowAlignedImage: View {
    let path: String
    var blur = 0.0
    var grain = 0.0
    @Environment(\.windowSize) private var window
    @State private var frame = CGRect.zero

    var body: some View {
        let size = window == .zero ? frame.size : window
        Color.clear
            .overlay(alignment: .topLeading) {
                GrainedImage(path: path, blur: blur, grain: grain)
                    .frame(width: size.width, height: size.height)
                    .offset(x: -frame.minX, y: -frame.minY)
            }
            .clipShape(Rectangle())
            .onGeometryChange(for: CGRect.self) {
                $0.frame(in: .named(WindowSpace.name))
            } action: {
                frame = $0
            }
    }
}

/// The plain image with the dithered copy over it at the grain's opacity.
struct GrainedImage: View {
    let path: String
    var blur = 0.0
    let grain: Double

    var body: some View {
        let effect = ChatBackground.effectOpacity(grain: grain)
        ZStack {
            if effect < 1 {
                BackdropImage(path: path, blur: blur, dithered: false)
            }
            if effect > 0 {
                BackdropImage(path: path, blur: blur, dithered: true).opacity(effect)
            }
        }
    }
}

/// The image, dithered or plain, filling its frame like CSS `cover`, blurred by `blur`
/// window points; it fades in once it is ready and draws nothing until then or if the file
/// cannot be read.
struct BackdropImage: View {
    let path: String
    var blur = 0.0
    var dithered = true
    @Environment(\.reducedMotion) private var reduceMotion
    @State private var shown: (key: BackdropRenderer.Key, image: CGImage)?

    var body: some View {
        let key = BackdropRenderer.Key(path: path, blur: blur, dithered: dithered)
        Color.clear
            .overlay {
                if let shown, shown.key == key {
                    Image(decorative: shown.image, scale: 1)
                        .resizable()
                        .interpolation(.high)
                        .scaledToFill()
                        .transition(.opacity)
                }
            }
            .clipped()
            // Clipping hides the overflow of a filled image but it still takes clicks, which
            // left the rows above a settings preview dead (user, 2026-11-03).
            .allowsHitTesting(false)
            .task(id: key) {
                guard let image = await BackdropRenderer.shared.image(for: key) else { return }
                withAnimation(reduceMotion ? nil : ChatBackdrop.easing(0.12)) {
                    shown = (key, image)
                }
            }
    }
}

/// Renders each image's dithered and plain copies once per blur, off the main thread, and
/// keeps the latest few, as the approved design's worker does. Blurred copies are made here rather
/// than with a live blur, which costs every frame and which offscreen snapshots leave out.
actor BackdropRenderer {
    struct Key: Hashable, Sendable {
        let path: String
        var blur = 0.0
        var dithered = true
    }

    static let shared = BackdropRenderer()
    /// Sharp and hazed copies, dithered and plain, and the chrome's.
    private static let kept = 6

    private var renders: [Key: Task<CGImage?, Never>] = [:]
    private var order: [Key] = []

    func image(for key: Key) async -> CGImage? {
        if let render = renders[key] {
            return await render.value
        }
        let render = Task.detached(priority: .utility) {
            Self.render(key).flatMap { Self.blurred($0, points: key.blur) }
        }
        renders[key] = render
        order.append(key)
        if order.count > Self.kept {
            renders[order.removeFirst()] = nil
        }
        return await render.value
    }

    /// The image blurred by `points` of a 1440 by 900 point window, its edges clamped so
    /// they stay opaque.
    private nonisolated static func blurred(_ image: CGImage, points: Double) -> CGImage? {
        let radius = Dither.blurPixels(points: points, width: image.width, height: image.height)
        guard radius > 0 else { return image }
        let input = CIImage(cgImage: image)
        let output = input.clampedToExtent()
            .applyingGaussianBlur(sigma: radius)
            .cropped(to: input.extent)
        return CIContext().createCGImage(output, from: input.extent)
    }

    /// The image at most 2048 pixels on a side, oriented, dithered unless the key asks for
    /// the plain image.
    private nonisolated static func render(_ key: Key) -> CGImage? {
        let url = URL(fileURLWithPath: key.path)
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: Int(Dither.maxSide),
        ]
        guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
            let decoded = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary),
            let space = CGColorSpace(name: CGColorSpace.sRGB)
        else { return nil }
        let size = Dither.fittedSize(width: decoded.width, height: decoded.height)
        let bytesPerRow = size.width * 4
        var pixels = [UInt8](repeating: 0, count: bytesPerRow * size.height)
        let drawn = pixels.withUnsafeMutableBytes { buffer -> Bool in
            guard
                let context = CGContext(
                    data: buffer.baseAddress, width: size.width, height: size.height,
                    bitsPerComponent: 8, bytesPerRow: bytesPerRow, space: space,
                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
            else { return false }
            context.interpolationQuality = .high
            context.draw(decoded, in: CGRect(x: 0, y: 0, width: size.width, height: size.height))
            return true
        }
        guard drawn else { return nil }
        Dither.unpremultiply(&pixels)
        let output =
            key.dithered ? Dither.render(pixels, width: size.width, height: size.height) : pixels
        guard let provider = CGDataProvider(data: Data(output) as CFData) else { return nil }
        return CGImage(
            width: size.width, height: size.height, bitsPerComponent: 8, bitsPerPixel: 32,
            bytesPerRow: bytesPerRow, space: space,
            bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.last.rawValue),
            provider: provider, decode: nil, shouldInterpolate: true, intent: .defaultIntent)
    }
}

extension Shell {
    /// The chat background on screen: the current project's own image, else the global
    /// one, which the Pixies tab shows too.
    var chatBackground: ChatBackground? {
        settings.chatBackground.background(for: pixiesOpen ? nil : project)
    }

    /// The workspace on screen, a project's or the Pixies tab's, has a pane open.
    var workspaceHasChats: Bool {
        !workspaceState.layout.leaves.isEmpty
    }

    /// Asks for an image and uses a copy of it as the global background, or as `project`'s
    /// own.
    func chooseChatBackground(for project: String? = nil) {
        let panel = NSOpenPanel()
        panel.title = project == nil ? "Choose chat background" : "Choose project chat background"
        panel.allowedContentTypes = [.png, .jpeg, .gif, .webP]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let library = ChatBackgroundLibrary.standard()
        do {
            let copy = try library.save(url)
            var settings = self.settings.chatBackground
            if let project {
                if var own = settings.projects[project] {
                    library.remove(own.image)
                    own.image = copy
                    settings.projects[project] = own
                } else {
                    settings.projects[project] = settings.newProjectBackground(image: copy)
                }
            } else {
                settings.image.map(library.remove)
                settings.image = copy
            }
            self.settings.chatBackground = settings
        } catch {
            show(error, doing: "Could not use that image")
        }
    }

    /// Removes the global background, or `project`'s own so it follows the global one.
    func removeChatBackground(for project: String? = nil) {
        let library = ChatBackgroundLibrary.standard()
        if let project {
            settings.chatBackground.projects.removeValue(forKey: project).map {
                library.remove($0.image)
            }
        } else {
            settings.chatBackground.image.map(library.remove)
            settings.chatBackground.image = nil
        }
    }
}
