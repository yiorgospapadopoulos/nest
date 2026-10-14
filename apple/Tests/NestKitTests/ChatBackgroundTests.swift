import Foundation
import Testing

@testable import NestKit

@Suite struct ChatBackgroundTests {
    /// the approved design's range and default for both visibilities.
    @Test func visibilitiesStartAtTheDefaultAndStayInRange() {
        let background = ChatBackground(image: "/a.png")
        #expect(background.emptyVisibility == 0.24)
        #expect(background.chatsVisibility == 0.24)
        let clamped = ChatBackground(image: "/a.png", emptyVisibility: 0.01, chatsVisibility: 0.9)
        #expect(clamped.emptyVisibility == 0.05)
        #expect(clamped.chatsVisibility == 0.65)
        #expect(ChatBackground.clamp(.nan) == 0.24)
        #expect(ChatBackground.clamp(.infinity) == 0.24)
        #expect(ChatBackground.clamp(0.4) == 0.4)
    }

    @Test func theVisibilityFollowsWhetherChatsAreOpen() {
        let background = ChatBackground(image: "/a.png", emptyVisibility: 0.5, chatsVisibility: 0.1)
        #expect(background.visibility(hasChats: false) == 0.5)
        #expect(background.visibility(hasChats: true) == 0.1)
    }

    /// Grain runs from the plain image (0) to the approved design's full effect (1), the default.
    @Test func grainIsTheEffectsShareOverThePlainImage() {
        #expect(ChatBackground(image: "/a.png").grain == 1)
        #expect(ChatBackground(image: "/a.png", grain: 0.3).grain == 0.3)
        #expect(ChatBackground(image: "/a.png", grain: -1).grain == 0)
        #expect(ChatBackground(image: "/a.png", grain: 4).grain == 1)
        #expect(ChatBackground.clampGrain(.nan) == 1)
        #expect(ChatBackground.effectOpacity(grain: 0) == 0)
        #expect(ChatBackground.effectOpacity(grain: 0.5) == 0.5)
        #expect(ChatBackground.effectOpacity(grain: 2) == 1)
    }

    /// 600 ms once chats are open, the approved design's 120 ms feedback otherwise.
    @Test func openingChatsFadesSlowly() {
        #expect(ChatBackground.transition(hasChats: true) == 0.6)
        #expect(ChatBackground.transition(hasChats: false) == 0.12)
    }

    /// The window's chrome shows the image heavily blurred; the workspace shows it sharp
    /// while empty and hazed once panes are open, as the approved design's open sessions.
    @Test func theImageBlursUnderTheChromeAndBehindOpenChats() {
        #expect(ChatBackground.chromeBlur == 36)
        #expect(ChatBackground.workspaceBlur(hasChats: false) == 0)
        #expect(ChatBackground.workspaceBlur(hasChats: true) == 12)
    }

    @Test func aProjectsOwnImageOverridesTheGlobalOne() {
        var settings = ChatBackgroundSettings()
        #expect(settings.background(for: nil) == nil)
        #expect(settings.background(for: "todo-ui") == nil)

        settings.image = "/global.png"
        settings.emptyVisibility = 0.3
        settings.chatsVisibility = 0.1
        settings.grain = 0.6
        let global = ChatBackground(
            image: "/global.png", emptyVisibility: 0.3, chatsVisibility: 0.1, grain: 0.6)
        #expect(settings.background(for: nil) == global)
        #expect(settings.background(for: "todo-ui") == global)

        let own = ChatBackground(image: "/own.png", emptyVisibility: 0.6, chatsVisibility: 0.2)
        settings.projects["todo-ui"] = own
        #expect(settings.background(for: "todo-ui") == own)
        #expect(settings.background(for: "map-viewer") == global)

        settings.image = nil
        #expect(settings.background(for: "map-viewer") == nil)
        #expect(settings.background(for: "todo-ui") == own)
    }

    /// A new project override starts at the global visibilities, as in the approved design.
    @Test func aNewProjectImageStartsAtTheGlobalVisibilities() {
        var settings = ChatBackgroundSettings()
        settings.emptyVisibility = 0.4
        settings.chatsVisibility = 0.12
        settings.grain = 0.5
        #expect(
            settings.newProjectBackground(image: "/p.png")
                == ChatBackground(
                    image: "/p.png", emptyVisibility: 0.4, chatsVisibility: 0.12, grain: 0.5))
    }
}

@Suite struct DitherTests {
    /// Images are drawn at most 2048 pixels on a side, keeping their shape.
    @Test func largeImagesShrinkToFit() {
        typealias Size = Dither.Size
        #expect(Dither.fittedSize(width: 1000, height: 500) == Size(width: 1000, height: 500))
        #expect(Dither.fittedSize(width: 4096, height: 2048) == Size(width: 2048, height: 1024))
        #expect(Dither.fittedSize(width: 1000, height: 3000) == Size(width: 683, height: 2048))
        #expect(Dither.fittedSize(width: 5000, height: 1) == Size(width: 2048, height: 1))
        #expect(Dither.fittedSize(width: 0, height: 0) == Size(width: 1, height: 1))
    }

    private func image(_ width: Int, _ height: Int, _ pixel: (Int, Int) -> [UInt8]) -> [UInt8] {
        var pixels: [UInt8] = []
        for y in 0..<height {
            for x in 0..<width {
                pixels += pixel(x, y)
            }
        }
        return pixels
    }

    private func pixel(_ pixels: [UInt8], _ width: Int, _ x: Int, _ y: Int) -> [UInt8] {
        Array(pixels[(y * width + x) * 4..<(y * width + x) * 4 + 4])
    }

    /// A bright 2 by 2 block is raised to full brightness, keeping its hue; a dark one
    /// keeps 8 percent. Bright or dark is the block's peak against its Bayer threshold.
    @Test func blocksAreRaisedOrDarkenedByTheirThreshold() {
        let flat = image(4, 2) { _, _ in [200, 100, 50, 255] }
        let out = Dither.render(flat, width: 4, height: 2)
        // The first block's threshold is 0: bright, scaled by 255 / 200 and rounded as
        // the approved design's canvas does (100 * 1.275 is just under 127.5 in floating point).
        #expect(pixel(out, 4, 0, 0) == [255, 127, 64, 255])
        #expect(pixel(out, 4, 1, 1) == [255, 127, 64, 255])
        // The second block's threshold is 8: 200 / 255 still clears 8.5 / 16.
        #expect(pixel(out, 4, 2, 0) == [255, 127, 64, 255])

        let dim = image(4, 2) { _, _ in [100, 50, 25, 255] }
        let dark = Dither.render(dim, width: 4, height: 2)
        #expect(pixel(dark, 4, 0, 0) == [255, 127, 64, 255])
        // 100 / 255 is under 8.5 / 16: 8 percent.
        #expect(pixel(dark, 4, 3, 1) == [8, 4, 2, 255])
    }

    /// Mid grey turns half its blocks white and half nearly black, in the Bayer order: the
    /// fine regular dot screen of the reference.
    @Test func midGreyMakesTheBayerScreen() {
        let grey = image(8, 8) { _, _ in [128, 128, 128, 255] }
        let out = Dither.render(grey, width: 8, height: 8)
        var dark: [[Bool]] = []
        for by in 0..<4 {
            dark.append((0..<4).map { bx in pixel(out, 8, bx * 2, by * 2)[0] < 128 })
        }
        #expect(
            dark == [
                [false, true, false, true],
                [true, false, true, false],
                [false, true, false, true],
                [true, false, true, false],
            ])
        #expect(pixel(out, 8, 2, 0) == [10, 10, 10, 255])
        #expect(pixel(out, 8, 0, 0) == [255, 255, 255, 255])
    }

    /// A block takes the color of its bottom right pixel, inside the image at its edges.
    @Test func blocksSampleTheirBottomRightPixel() {
        let corner = image(3, 3) { x, y in
            x == 1 && y == 1
                ? [255, 0, 0, 255] : x == 2 && y == 2 ? [0, 255, 0, 200] : [0, 0, 0, 255]
        }
        let out = Dither.render(corner, width: 3, height: 3)
        #expect(pixel(out, 3, 0, 0) == [255, 0, 0, 255])
        #expect(pixel(out, 3, 1, 0) == [255, 0, 0, 255])
        // The one pixel block at (2, 2) samples itself, alpha included.
        #expect(pixel(out, 3, 2, 2) == [0, 255, 0, 200])
        // Black: never bright, 8 percent of nothing.
        #expect(pixel(out, 3, 2, 0) == [0, 0, 0, 255])
    }

    /// A blur in points becomes pixels of the image as it covers a 1440 by 900 point
    /// window.
    @Test func blurIsMeasuredInWindowPoints() {
        #expect(Dither.blurPixels(points: 36, width: 1440, height: 900) == 36)
        #expect(Dither.blurPixels(points: 36, width: 2048, height: 1280) == 51.2)
        // A tall image covers the width: 720 pixels across 1440 points.
        #expect(Dither.blurPixels(points: 12, width: 720, height: 2000) == 6)
        #expect(Dither.blurPixels(points: 0, width: 2048, height: 1280) == 0)
    }

    @Test func premultipliedPixelsAreRestored() {
        var pixels: [UInt8] = [128, 64, 0, 128, 10, 20, 30, 0, 9, 8, 7, 255]
        Dither.unpremultiply(&pixels)
        #expect(pixels == [255, 128, 0, 128, 10, 20, 30, 0, 9, 8, 7, 255])
    }
}

@Suite struct ChatBackgroundLibraryTests {
    private func temporaryFolder() -> URL {
        FileManager.default.temporaryDirectory.appending(path: "nest-tests-\(UUID().uuidString)")
    }

    /// The copy is the app's own, so moving or deleting the original does not break it.
    @Test func savingCopiesTheImageIntoTheFolder() throws {
        let root = temporaryFolder()
        defer { try? FileManager.default.removeItem(at: root) }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let original = root.appending(path: "Beach.JPG")
        try Data("pixels".utf8).write(to: original)
        let library = ChatBackgroundLibrary(folder: root.appending(path: "Backgrounds"))

        let saved = try library.save(original)
        let other = try library.save(original)
        try FileManager.default.removeItem(at: original)

        let url = URL(fileURLWithPath: saved)
        let folder = url.deletingLastPathComponent().standardizedFileURL
        #expect(folder == library.folder.standardizedFileURL)
        #expect(url.pathExtension == "jpg")
        #expect(saved != other)
        #expect(try Data(contentsOf: url) == Data("pixels".utf8))
    }

    @Test func savingAMissingFileFails() {
        let root = temporaryFolder()
        defer { try? FileManager.default.removeItem(at: root) }
        let library = ChatBackgroundLibrary(folder: root)
        #expect(throws: (any Error).self) {
            try library.save(root.appending(path: "missing.png"))
        }
    }

    /// Only the library's own copies are ever deleted.
    @Test func removingDeletesOnlyTheLibrarysCopies() throws {
        let root = temporaryFolder()
        defer { try? FileManager.default.removeItem(at: root) }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let outside = root.appending(path: "mine.png")
        try Data("x".utf8).write(to: outside)
        let library = ChatBackgroundLibrary(folder: root.appending(path: "Backgrounds"))
        let saved = try library.save(outside)

        library.remove(outside.path)
        library.remove(saved)
        library.remove(saved)

        #expect(FileManager.default.fileExists(atPath: outside.path))
        #expect(!FileManager.default.fileExists(atPath: saved))
    }

    @Test func theStandardFolderIsInTheAppsApplicationSupport() {
        let home = URL(fileURLWithPath: "/Users/someone")
        #expect(
            ChatBackgroundLibrary.standard(bundleID: "local.nest.app", home: home).folder.path
                == "/Users/someone/Library/Application Support/local.nest.app/Backgrounds")
        #expect(
            ChatBackgroundLibrary.standard(bundleID: nil, home: home).folder.path
                == "/Users/someone/Library/Application Support/local.nest.app/Backgrounds")
        #expect(ChatBackgroundLibrary.standard().folder.path.hasSuffix("/Backgrounds"))
    }
}
