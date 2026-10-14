import Foundation

/// One side of a side-by-side diff row.
public struct DiffCell: Sendable, Hashable {
    public let number: Int
    public let text: String
    /// `.context`, `.delete` (old side) or `.add` (new side).
    public let kind: DiffLineKind
}

/// A row of a side-by-side diff: the old line on the left, the new one on the right.
/// A side is nil where the other side added or removed a line.
public struct DiffRow: Sendable, Hashable {
    public let old: DiffCell?
    public let new: DiffCell?
}

/// Lays hunks out for the diff sheet.
public enum DiffRows {
    /// Context lines sit on both sides; a run of deletions faces the additions that
    /// follow it line by line, and the longer run continues against blanks.
    public static func sideBySide(_ hunk: Hunk) -> [DiffRow] {
        var rows: [DiffRow] = []
        var deleted: [DiffCell] = []
        var added: [DiffCell] = []

        func flush() {
            for index in 0..<max(deleted.count, added.count) {
                rows.append(
                    DiffRow(
                        old: deleted.indices.contains(index) ? deleted[index] : nil,
                        new: added.indices.contains(index) ? added[index] : nil))
            }
            deleted = []
            added = []
        }

        for line in hunk.lines {
            switch line.kind {
            case .delete:
                if !added.isEmpty {
                    flush()
                }
                deleted.append(DiffCell(number: line.oldLine ?? 0, text: line.text, kind: .delete))
            case .add:
                added.append(DiffCell(number: line.newLine ?? 0, text: line.text, kind: .add))
            case .context, .unknown:
                flush()
                rows.append(
                    DiffRow(
                        old: DiffCell(number: line.oldLine ?? 0, text: line.text, kind: .context),
                        new: DiffCell(number: line.newLine ?? 0, text: line.text, kind: .context)))
            }
        }
        flush()
        return rows
    }

    /// The hunk's range line, such as "@@ -12,7 +12,9 @@ func render".
    public static func header(_ hunk: Hunk) -> String {
        let range = "@@ -\(hunk.oldStart),\(hunk.oldLines) +\(hunk.newStart),\(hunk.newLines) @@"
        return hunk.header.isEmpty ? range : "\(range) \(hunk.header)"
    }

    /// The file's name as the sheet lists it; a rename shows where it came from.
    public static func title(_ file: FileDiff) -> String {
        guard file.status == .renamed, let old = file.oldPath else { return file.path }
        return "\(old) → \(file.path)"
    }
}
