import Testing

@testable import NestKit

/// The line under the tab strip takes its colours from the chat background (B73).
@Suite struct PhotoLineTests {
    /// RGBA pixels, row by row, each pixel from `color(x, y)`.
    func image(width: Int, height: Int, _ color: (Int, Int) -> [UInt8]) -> [UInt8] {
        (0..<height).flatMap { y in (0..<width).flatMap { x in color(x, y) + [255] } }
    }

    @Test func eachBandIsTheAverageOfItsColumnsInTheTopThird() {
        // Left half red, right half blue in the top third; green below, which is ignored.
        let pixels = image(width: 4, height: 6) { x, y in
            y >= 2 ? [0, 255, 0] : x < 2 ? [200, 0, 0] : [0, 0, 100]
        }
        let colors = PhotoLine.colors(rgba: pixels, width: 4, height: 6, bands: 2)
        #expect(
            colors == [
                PhotoLine.Color(red: 200, green: 0, blue: 0),
                PhotoLine.Color(red: 0, green: 0, blue: 100),
            ])
    }

    @Test func aBandSpanningTwoColoursMixesThem() {
        let pixels = image(width: 2, height: 3) { x, _ in x == 0 ? [100, 0, 0] : [0, 50, 0] }
        #expect(
            PhotoLine.colors(rgba: pixels, width: 2, height: 3, bands: 1)
                == [PhotoLine.Color(red: 50, green: 25, blue: 0)])
    }

    @Test func narrowOrEmptyImagesGiveAtMostOneBandPerColumn() {
        let pixels = image(width: 2, height: 1) { x, _ in [UInt8(x * 10), 0, 0] }
        #expect(PhotoLine.colors(rgba: pixels, width: 2, height: 1, bands: 8).count == 2)
        #expect(PhotoLine.colors(rgba: [], width: 0, height: 0, bands: 8).isEmpty)
        #expect(PhotoLine.colors(rgba: pixels, width: 2, height: 1, bands: 0).isEmpty)
        // A buffer shorter than its size says reads nothing.
        #expect(PhotoLine.colors(rgba: [1, 2, 3], width: 2, height: 2, bands: 2).isEmpty)
    }

    /// One colour for the whole line: the photo's most colourful band, made bright.
    @Test func theLineTakesThePhotosMostColourfulToneBrightened() {
        let pink = PhotoLine.lineColor([
            PhotoLine.Color(red: 140, green: 140, blue: 140),
            PhotoLine.Color(red: 160, green: 60, blue: 100),
            PhotoLine.Color(red: 120, green: 90, blue: 100),
        ])
        #expect(pink == PhotoLine.Color(red: 240, green: 90, blue: 150))
    }

    /// A black and white photo, or one with only faint colour, gives a white line; so does
    /// a photo that could not be read.
    @Test func aPhotoWithoutColourGivesWhite() {
        let white = PhotoLine.Color(red: 255, green: 255, blue: 255)
        #expect(
            PhotoLine.lineColor([
                PhotoLine.Color(red: 220, green: 220, blue: 220),
                PhotoLine.Color(red: 10, green: 10, blue: 12),
                PhotoLine.Color(red: 0, green: 0, blue: 0),
            ]) == white)
        #expect(PhotoLine.lineColor([]) == white)
    }
}
