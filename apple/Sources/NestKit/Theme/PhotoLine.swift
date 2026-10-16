/// The thin line under the Mac's tab strip (B73): one colour along its whole width, the
/// chat background's most colourful tone made bright (white for a black and white photo);
/// without a photo it is the accent colour.
public enum PhotoLine {
    public struct Color: Sendable, Hashable {
        public let red: UInt8
        public let green: UInt8
        public let blue: UInt8
    }

    /// Bands sampled across the photo's width.
    public static let bands = 8

    /// The line's brightest channel, out of 255, once its colour is chosen.
    static let level = 240
    /// Bands with less colour than this (0 grey to 1 pure colour) count as grey.
    static let colourful = 0.25

    /// One colour for the whole line: the photo's most colourful band brightened to
    /// `level`, or white for a photo without real colour (black and white, faint tints)
    /// or one that could not be read.
    public static func lineColor(_ colors: [Color]) -> Color {
        let white = Color(red: 255, green: 255, blue: 255)
        func saturation(_ color: Color) -> Double {
            let top = Double(max(color.red, color.green, color.blue))
            return top == 0 ? 0 : (top - Double(min(color.red, color.green, color.blue))) / top
        }
        guard let best = colors.max(by: { saturation($0) < saturation($1) }),
            saturation(best) >= colourful
        else { return white }
        let top = Int(max(best.red, best.green, best.blue))
        let lift = { (channel: UInt8) in UInt8((Int(channel) * level + top / 2) / top) }
        return Color(red: lift(best.red), green: lift(best.green), blue: lift(best.blue))
    }

    /// The average colour of each of `bands` equal column ranges of the top third of
    /// `width` by `height` RGBA pixels, left to right; at most one band per column, and
    /// none when the buffer is shorter than its size.
    public static func colors(rgba: [UInt8], width: Int, height: Int, bands: Int) -> [Color] {
        guard width > 0, height > 0, bands > 0, rgba.count >= width * height * 4 else {
            return []
        }
        let count = min(bands, width)
        let rows = max(1, height / 3)
        return (0..<count).map { band in
            let columns = band * width / count..<(band + 1) * width / count
            var sum = [0, 0, 0]
            for y in 0..<rows {
                for x in columns {
                    let index = (y * width + x) * 4
                    for channel in 0..<3 {
                        sum[channel] += Int(rgba[index + channel])
                    }
                }
            }
            let pixels = rows * columns.count
            let average = sum.map { UInt8(($0 + pixels / 2) / pixels) }
            return Color(red: average[0], green: average[1], blue: average[2])
        }
    }
}
