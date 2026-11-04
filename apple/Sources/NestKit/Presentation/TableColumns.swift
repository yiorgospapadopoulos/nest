/// How a message's table shares its width between columns, as a browser's automatic table
/// does. The text is built once and cached for any pane width, so this runs at layout.
public enum TableColumns {
    /// Each column's width, filling `room`, from the width of its longest cell and of its
    /// longest word: every column gets what it wants when all fit; otherwise each keeps its
    /// longest word and the rest goes to the long ones.
    public static func widths(longest: [Double], longestWord: [Double], room: Double) -> [Double] {
        let wanted = zip(longest, longestWord).map { max($0, $1) }
        let totalWanted = wanted.reduce(0, +)
        let totalWords = longestWord.reduce(0, +)
        if totalWanted <= room {
            guard totalWanted > 0 else {
                return wanted.map { _ in room / Double(max(wanted.count, 1)) }
            }
            return wanted.map { $0 * room / totalWanted }
        }
        if totalWords >= room {
            return longestWord.map { $0 * room / totalWords }
        }
        let spare = room - totalWords
        let stretch = totalWanted - totalWords
        return zip(wanted, longestWord).map { $1 + spare * ($0 - $1) / stretch }
    }
}
