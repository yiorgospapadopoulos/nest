import Foundation
import Testing

@testable import NestKit

private func edit(_ name: String, _ input: [String: JSONValue], result: String? = "ok")
    -> ToolCall
{
    ToolCall(id: "e1", name: name, input: .object(input), result: result, isError: false)
}

private func shape(_ lines: [EditDiff.Line]) -> [String] {
    lines.map { line in
        let mark =
            switch line.kind {
            case .add: "+"
            case .delete: "-"
            default: " "
            }
        return mark + line.text
    }
}

@Suite struct EditDiffTests {
    @Test func anEditShowsTheReplacedLinesWithTheUnchangedOnesAsContext() throws {
        let diff = try #require(
            EditDiff(
                edit(
                    "Edit",
                    [
                        "file_path": .string("/repo/a.swift"),
                        "old_string": .string("let a = 1\nlet b = 2\nlet c = 3"),
                        "new_string": .string("let a = 1\nlet b = 20\nlet b2 = 21\nlet c = 3"),
                    ])))
        #expect(diff.path == "/repo/a.swift")
        #expect(diff.hunks.count == 1)
        #expect(
            shape(diff.hunks[0]) == [
                " let a = 1", "-let b = 2", "+let b = 20", "+let b2 = 21", " let c = 3",
            ])
        #expect(diff.additions == 2)
        #expect(diff.deletions == 1)
    }

    @Test func aMultiEditShowsOneHunkPerEdit() throws {
        let diff = try #require(
            EditDiff(
                edit(
                    "MultiEdit",
                    [
                        "file_path": .string("/repo/b.py"),
                        "edits": .array([
                            .object(["old_string": .string("x"), "new_string": .string("y")]),
                            .object(["old_string": .string("gone\n"), "new_string": .string("")]),
                            .object(["new_string": .string("no old")]),
                            .string("not an edit"),
                        ]),
                    ])))
        #expect(diff.hunks.map(shape) == [["-x", "+y"], ["-gone"], ["+no old"]])
        #expect(diff.additions == 2)
        #expect(diff.deletions == 2)
    }

    @Test func aWriteIsAllAdded() throws {
        let diff = try #require(
            EditDiff(
                edit(
                    "Write",
                    ["file_path": .string("/repo/new.md"), "content": .string("# Title\n\nBody\n")]
                )))
        #expect(shape(diff.hunks[0]) == ["+# Title", "+", "+Body"])
        #expect(diff.additions == 3)
        #expect(diff.deletions == 0)
    }

    @Test func callsWithoutAPathOrAChangeOrOfOtherToolsHaveNoDiff() {
        #expect(EditDiff(edit("Edit", ["old_string": .string("a"), "new_string": .string("b")])) == nil)
        #expect(
            EditDiff(
                edit(
                    "Edit",
                    [
                        "file_path": .string("/a"), "old_string": .string("same"),
                        "new_string": .string("same"),
                    ])) == nil)
        #expect(EditDiff(edit("Write", ["file_path": .string("/a"), "content": .string("")])) == nil)
        #expect(EditDiff(edit("MultiEdit", ["file_path": .string("/a")])) == nil)
        #expect(EditDiff(edit("Read", ["file_path": .string("/a")])) == nil)
        #expect(EditDiff(edit("Edit", ["file_path": .string("/a")])) == nil)
    }

    @Test func aFailedEditHasNoDiffSinceNothingChanged() {
        var call = edit(
            "Edit",
            [
                "file_path": .string("/a"), "old_string": .string("a"), "new_string": .string("b"),
            ])
        call.isError = true
        #expect(EditDiff(call) == nil)
    }

    @Test func aLongDiffShowsItsFirstLinesAcrossHunksUntilExpanded() throws {
        let long = (1...12).map { "line \($0)" }.joined(separator: "\n")
        let diff = try #require(
            EditDiff(
                edit(
                    "MultiEdit",
                    [
                        "file_path": .string("/a"),
                        "edits": .array([
                            .object(["old_string": .string("a\nb"), "new_string": .string("c")]),
                            .object(["old_string": .string(""), "new_string": .string(long)]),
                        ]),
                    ])))
        #expect(diff.hiddenLines == 15 - EditDiff.previewLines)
        #expect(diff.expandLabel == "Show 7 more lines")
        let preview = diff.shown(expanded: false)
        #expect(preview.map(\.count) == [3, 5])
        #expect(diff.shown(expanded: true) == diff.hunks)
    }

    @Test func aShortDiffShowsWhole() throws {
        let diff = try #require(
            EditDiff(edit("Write", ["file_path": .string("/a"), "content": .string("one")])))
        #expect(diff.hiddenLines == 0)
        #expect(diff.expandLabel == nil)
        #expect(diff.shown(expanded: false) == diff.hunks)
        let nine = try #require(
            EditDiff(
                edit(
                    "Write",
                    [
                        "file_path": .string("/a"),
                        "content": .string((1...9).map(String.init).joined(separator: "\n")),
                    ])))
        #expect(nine.expandLabel == "Show 1 more line")
    }

    @Test func theCountsReadLikeAStat() throws {
        let diff = try #require(
            EditDiff(
                edit(
                    "Edit",
                    [
                        "file_path": .string("/a"), "old_string": .string("a"),
                        "new_string": .string("b\nc"),
                    ])))
        #expect(diff.stat == "+2 -1")
    }

    @Test func editsWithADiffStandAloneInTheTranscriptWhileOtherCallsGroup() {
        let read = TranscriptItem(
            id: "r1", content: .tool(edit("Read", ["file_path": .string("/a")])), eventID: 1)
        let read2 = TranscriptItem(
            id: "r2", content: .tool(edit("Read", ["file_path": .string("/b")])), eventID: 1)
        let change = TranscriptItem(
            id: "e1",
            content: .tool(
                edit("Write", ["file_path": .string("/a"), "content": .string("x")], result: nil)
            ), eventID: 1)
        let read3 = TranscriptItem(
            id: "r3", content: .tool(edit("Read", ["file_path": .string("/c")])), eventID: 1)
        let entries = TranscriptGrouping.entries([read, read2, change, read3], live: false)
        #expect(entries.map(\.id) == ["tools-r1", "e1", "r3"])
        guard case .item(let lone) = entries[1], case .tool(let call) = lone.content else {
            Issue.record("expected the edit alone")
            return
        }
        #expect(call.stopped)
    }
}
