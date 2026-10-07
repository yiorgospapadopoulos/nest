import Foundation
import Testing

@testable import HarnessKit

@Suite struct DiffRowsTests {
    func line(_ kind: DiffLineKind, _ text: String, _ old: Int?, _ new: Int?) -> DiffLine {
        DiffLine(kind: kind, text: text, oldLine: old, newLine: new)
    }

    func hunk(_ lines: [DiffLine], header: String = "") -> Hunk {
        Hunk(oldStart: 1, oldLines: 4, newStart: 1, newLines: 5, header: header, lines: lines)
    }

    @Test func pairsDeletionsWithTheAdditionsThatFollow() {
        let rows = DiffRows.sideBySide(
            hunk([
                line(.context, "a", 1, 1),
                line(.delete, "b", 2, nil),
                line(.delete, "c", 3, nil),
                line(.add, "B", nil, 2),
                line(.context, "d", 4, 3),
                line(.add, "e", nil, 4),
                line(.add, "f", nil, 5),
            ]))

        #expect(rows.count == 6)
        #expect(rows[0].old == DiffCell(number: 1, text: "a", kind: .context))
        #expect(rows[0].new == DiffCell(number: 1, text: "a", kind: .context))
        #expect(rows[1].old?.text == "b")
        #expect(rows[1].new == DiffCell(number: 2, text: "B", kind: .add))
        #expect(rows[2].old == DiffCell(number: 3, text: "c", kind: .delete))
        #expect(rows[2].new == nil)
        #expect(rows[3].old?.number == 4)
        #expect(rows[4].old == nil)
        #expect(rows[4].new?.text == "e")
        #expect(rows[5].new?.number == 5)
    }

    @Test func aDeletionAfterAdditionsStartsANewRun() {
        let rows = DiffRows.sideBySide(
            hunk([
                line(.add, "x", nil, 1),
                line(.delete, "y", 1, nil),
                line(.unknown, "?", nil, nil),
            ]))
        #expect(rows.map(\.old?.text) == [nil, "y", "?"])
        #expect(rows.map(\.new?.text) == ["x", nil, "?"])
        #expect(rows[2].old?.number == 0)
        let unnumbered = DiffRows.sideBySide(
            hunk([line(.delete, "y", nil, nil), line(.add, "x", nil, nil)]))
        #expect(unnumbered.map(\.old?.number) == [0])
        #expect(unnumbered.map(\.new?.number) == [0])
    }

    @Test func headersAndTitles() {
        #expect(DiffRows.header(hunk([], header: "func a()")) == "@@ -1,4 +1,5 @@ func a()")
        #expect(DiffRows.header(hunk([])) == "@@ -1,4 +1,5 @@")
        let files = Fixture.diff.files
        #expect(DiffRows.title(files[0]) == "app/globals.css")
        #expect(DiffRows.title(files[1]) == "public/old-logo.png → public/logo.png")
        var renamed = files[1]
        renamed.oldPath = nil
        #expect(DiffRows.title(renamed) == "public/logo.png")
    }
}
