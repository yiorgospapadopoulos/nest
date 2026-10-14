import Foundation

/// An image drawn behind the workspace, as the approved design's chat background (B39): its copy in
/// the app's folder, how visible it is while no chat is open and once chats are open, and
/// its grain, how much of the approved design's dither effect lies over the plain image.
public struct ChatBackground: Sendable, Hashable {
    public static let minVisibility = 0.05
    public static let maxVisibility = 0.65
    public static let defaultVisibility = 0.24

    /// The path of the app's own copy of the image (`ChatBackgroundLibrary`).
    public var image: String
    public var emptyVisibility: Double
    public var chatsVisibility: Double
    /// 0 is the plain image, 1 (the default) the approved design's full effect.
    public var grain: Double

    public init(
        image: String, emptyVisibility: Double = defaultVisibility,
        chatsVisibility: Double = defaultVisibility, grain: Double = 1
    ) {
        self.image = image
        self.emptyVisibility = Self.clamp(emptyVisibility)
        self.chatsVisibility = Self.clamp(chatsVisibility)
        self.grain = Self.clampGrain(grain)
    }

    /// A grain from 0 to 1; anything not a number is the full effect.
    public static func clampGrain(_ value: Double) -> Double {
        guard value.isFinite else { return 1 }
        return min(1, max(0, value))
    }

    /// The opacity of the effect's copy laid over the plain image.
    public static func effectOpacity(grain: Double) -> Double {
        clampGrain(grain)
    }

    /// A visibility inside the approved design's range; anything not a number is the default.
    public static func clamp(_ value: Double) -> Double {
        guard value.isFinite else { return defaultVisibility }
        return min(maxVisibility, max(minVisibility, value))
    }

    public func visibility(hasChats: Bool) -> Double {
        hasChats ? chatsVisibility : emptyVisibility
    }

    /// Points of blur of the image under the window's chrome (tab strip, toolbar, side
    /// panels, bottom bar), which leaves a deep tint of its colors.
    public static let chromeBlur = 36.0

    /// Points of blur of the image behind the workspace: sharp while it is empty, the approved design's
    /// haze once panes are open, so the chats are the focus.
    public static func workspaceBlur(hasChats: Bool) -> Double {
        hasChats ? 12 : 0
    }

    /// Seconds a change of visibility takes: 600 ms once chats are open, the approved design's 120 ms
    /// feedback otherwise.
    public static func transition(hasChats: Bool) -> Double {
        hasChats ? 0.6 : 0.12
    }
}

/// The chat background settings of this Mac: the global image (none by default), the
/// global visibilities, and the projects that have an image of their own.
public struct ChatBackgroundSettings: Sendable, Hashable {
    public var image: String?
    public var emptyVisibility = ChatBackground.defaultVisibility
    public var chatsVisibility = ChatBackground.defaultVisibility
    public var grain = 1.0
    /// By repo name.
    public var projects: [String: ChatBackground] = [:]

    public init() {}

    /// The project's own background, else the global one; nil when neither has an image.
    public func background(for project: String?) -> ChatBackground? {
        if let project, let own = projects[project] {
            return own
        }
        return image.map(newProjectBackground)
    }

    /// A project's first own image starts at the global visibilities and grain.
    public func newProjectBackground(image: String) -> ChatBackground {
        ChatBackground(
            image: image, emptyVisibility: emptyVisibility, chatsVisibility: chatsVisibility,
            grain: grain)
    }
}

/// The app's own copies of chosen background images, so moving or deleting an original
/// does not break the background.
public struct ChatBackgroundLibrary: Sendable {
    public let folder: URL

    public init(folder: URL) {
        self.folder = folder
    }

    /// `~/Library/Application Support/<bundle id>/Backgrounds`.
    public static func standard(
        bundleID: String? = Bundle.main.bundleIdentifier,
        home: URL = FileManager.default.homeDirectoryForCurrentUser
    ) -> ChatBackgroundLibrary {
        ChatBackgroundLibrary(
            folder: home.appending(path: "Library/Application Support")
                .appending(path: bundleID ?? "local.harness.app")
                .appending(path: "Backgrounds"))
    }

    /// Copies the image under a new name and returns the copy's path.
    public func save(_ source: URL) throws -> String {
        let manager = FileManager.default
        try manager.createDirectory(at: folder, withIntermediateDirectories: true)
        let copy = folder.appending(path: UUID().uuidString)
            .appendingPathExtension(source.pathExtension.lowercased())
        try manager.copyItem(at: source, to: copy)
        return copy.path
    }

    /// Deletes a copy this library made; any other path is left alone.
    public func remove(_ path: String) {
        let url = URL(fileURLWithPath: path).standardizedFileURL
        guard url.deletingLastPathComponent() == folder.standardizedFileURL else { return }
        try? FileManager.default.removeItem(at: url)
    }
}

/// the approved design's Dither effect on RGBA pixels, the look of its reference screenshots: 2 by 2
/// pixel blocks against a 4 by 4 Bayer matrix; a block whose brightest channel clears its
/// threshold is raised to full brightness, keeping its hue, and the others keep 8 percent,
/// so bright areas stay clean with a few dark dots and darker areas fill in with a fine
/// regular screen.
public enum Dither {
    public struct Size: Sendable, Hashable {
        public let width: Int
        public let height: Int
    }

    /// Images are drawn at most this many pixels on a side.
    public static let maxSide = 2048.0

    static let bayer: [[Double]] = [
        [0, 8, 2, 10],
        [12, 4, 14, 6],
        [3, 11, 1, 9],
        [15, 7, 13, 5],
    ]

    public static func fittedSize(width: Int, height: Int) -> Size {
        let scale = min(1, maxSide / Double(width), maxSide / Double(height))
        return Size(
            width: max(1, Int((Double(width) * scale).rounded())),
            height: max(1, Int((Double(height) * scale).rounded())))
    }

    /// A blur in points as pixels of a `width` by `height` image covering a 1440 by 900
    /// point window, so blurred copies can be made once, ahead of drawing.
    public static func blurPixels(points: Double, width: Int, height: Int) -> Double {
        points / max(1440 / Double(width), 900 / Double(height))
    }

    /// Turns premultiplied RGBA, as Core Graphics draws it, back into plain RGBA.
    public static func unpremultiply(_ pixels: inout [UInt8]) {
        for alpha in stride(from: 3, to: pixels.count, by: 4) {
            let a = Int(pixels[alpha])
            guard a > 0, a < 255 else { continue }
            for channel in alpha - 3..<alpha {
                pixels[channel] = UInt8(min(255, (Int(pixels[channel]) * 255 + a / 2) / a))
            }
        }
    }

    /// The effect on `width` by `height` RGBA pixels, row by row.
    public static func render(_ pixels: [UInt8], width: Int, height: Int) -> [UInt8] {
        var output = [UInt8](repeating: 0, count: pixels.count)
        for y in stride(from: 0, to: height, by: 2) {
            for x in stride(from: 0, to: width, by: 2) {
                // The block's bottom right pixel, inside the image.
                let sample = (min(y + 1, height - 1) * width + min(x + 1, width - 1)) * 4
                let peak = Double(max(pixels[sample], pixels[sample + 1], pixels[sample + 2]))
                let threshold = bayer[(y / 2) % 4][(x / 2) % 4]
                let bright = peak / 255 > (threshold + 0.5) / 16
                let gain = bright ? 255 / max(peak, 1) : 0.08
                let color = (0..<3).map {
                    UInt8((Double(pixels[sample + $0]) * gain + 0.5).rounded(.down))
                }
                for dy in 0..<min(2, height - y) {
                    for dx in 0..<min(2, width - x) {
                        let pixel = ((y + dy) * width + x + dx) * 4
                        output[pixel] = color[0]
                        output[pixel + 1] = color[1]
                        output[pixel + 2] = color[2]
                        output[pixel + 3] = pixels[sample + 3]
                    }
                }
            }
        }
        return output
    }
}
