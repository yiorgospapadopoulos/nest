/// The thin line under the Mac's tab strip (B73): with a chat background its colours come
/// from the photo, left to right, so each part matches the picture there; without one it
/// is the accent colour.
public enum PhotoLine {
    public struct Color: Sendable, Hashable {
        public let red: UInt8
        public let green: UInt8
        public let blue: UInt8
    }

    /// Bands sampled across the photo's width.
    public static let bands = 8

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
