import CoreGraphics
import Foundation
import Testing

@testable import NestKit

@Suite struct ElapsedTests {
    @Test func underAMinuteIsNow() {
        #expect(Elapsed.short(0) == "now")
        #expect(Elapsed.short(59) == "now")
        #expect(Elapsed.short(-30) == "now")
    }

    @Test func minutesHoursAndDays() {
        #expect(Elapsed.short(60) == "1m")
        #expect(Elapsed.short(59 * 60 + 59) == "59m")
        #expect(Elapsed.short(3600) == "1h")
        #expect(Elapsed.short(3600 + 12 * 60) == "1h 12m")
        #expect(Elapsed.short(23 * 3600 + 59 * 60) == "23h 59m")
        #expect(Elapsed.short(24 * 3600) == "1d")
        #expect(Elapsed.short(3 * 24 * 3600 + 7 * 3600) == "3d")
    }

    @Test func betweenTwoDates() {
        let start = Date(timeIntervalSince1970: 1000)
        #expect(Elapsed.short(from: start, to: start.addingTimeInterval(540)) == "9m")
    }
}

@Suite struct InitialsTests {
    @Test func firstLettersOfTheFirstTwoWords() {
        #expect(Initials.of("Giorgos Papadopoulos") == "GP")
        #expect(Initials.of("narrative-engine") == "NE")
        #expect(Initials.of("cv page builder") == "CP")
    }

    @Test func singleWordsAndSymbols() {
        #expect(Initials.of("nest") == "N")
        #expect(Initials.of("  (draft) fix: login ") == "DF")
        #expect(Initials.of("") == "?")
        #expect(Initials.of("--") == "?")
    }
}

@Suite struct ProjectMarkTests {
    @Test func theSameNameAlwaysGetsTheSameColor() {
        let index = ProjectMark.colorIndex(for: "cv-page", count: 4)
        #expect(index == ProjectMark.colorIndex(for: "cv-page", count: 4))
        #expect((0..<4).contains(index))
    }

    @Test func namesSpreadOverTheColors() {
        let names = ["cv-page", "narrative-engine", "llm-hunter", "nest", "MedGemma", "x"]
        let indexes = Set(names.map { ProjectMark.colorIndex(for: $0, count: 4) })
        #expect(indexes.count > 1)
        #expect(ProjectMark.colorIndex(for: "anything", count: 0) == 0)
    }
}

@Suite struct OptionLabelTests {
    @Test func effortLabels() {
        #expect(
            Effort.selectable.map(\.label) == ["Low", "Medium", "High", "Extra high", "Max"])
        #expect(Effort.unknown.label == "Unknown")
    }

    @Test func permissionModesDescribeThemselves() {
        #expect(
            PermissionMode.selectable.map(\.summary) == [
                "Asks before edits and commands", "Edits files without asking",
                "Reads and plans only", "Runs everything without asking",
            ])
        #expect(PermissionMode.unknown.summary == "")
        #expect(PermissionMode.auto.summary == "Asks only when Claude Code judges an action risky")
        #expect(PermissionMode.acceptEdits.shortLabel == "Edits")
        #expect(PermissionMode.plan.shortLabel == "Plan")
        #expect(PermissionMode.unknown.planChoiceLabel == "Auto-accept edits")
    }
}

@Suite struct DropZoneTests {
    private let size = CGSize(width: 400, height: 300)

    @Test func anEmptyWorkspaceOpensTheChat() {
        let zone = DropZone.zone(at: CGPoint(x: 10, y: 10), in: size, kind: .chat, target: nil)
        #expect(zone == .open)
        #expect(zone.label == "Open here")
        #expect(zone.highlight(in: size) == CGRect(origin: .zero, size: size))
    }

    @Test func aChatSplitsOnTheSideItIsDroppedOn() {
        func side(_ x: Double, _ y: Double) -> DropZone {
            DropZone.zone(
                at: CGPoint(x: x, y: y), in: size, kind: .chat,
                target: .init(isDraggedChat: false, draggedIsOpen: false, openCount: 2))
        }
        #expect(side(200, 20) == .split(.top))
        #expect(side(200, 290) == .split(.bottom))
        #expect(side(50, 150) == .split(.left))
        #expect(side(350, 150) == .split(.right))
        #expect(side(200, 20).label == "Split top")
        #expect(side(200, 290).label == "Split bottom")
        #expect(side(50, 150).label == "Split left")
        #expect(side(350, 150).label == "Split right")
    }

    @Test func splitHighlightsCoverTheHalfThatWillHoldTheChat() {
        #expect(
            DropZone.split(.left).highlight(in: size) == CGRect(x: 0, y: 0, width: 200, height: 300)
        )
        #expect(
            DropZone.split(.right).highlight(in: size)
                == CGRect(x: 200, y: 0, width: 200, height: 300))
        #expect(
            DropZone.split(.top).highlight(in: size) == CGRect(x: 0, y: 0, width: 400, height: 150))
        #expect(
            DropZone.split(.bottom).highlight(in: size)
                == CGRect(x: 0, y: 150, width: 400, height: 150))
    }

    @Test func aNewChatReplacesThePaneWhenFourAreOpen() {
        let full = DropZone.Target(isDraggedChat: false, draggedIsOpen: false, openCount: 4)
        let zone = DropZone.zone(at: CGPoint(x: 50, y: 150), in: size, kind: .chat, target: full)
        #expect(zone == .replace)
        #expect(zone.label == "Replace this chat")
        #expect(zone.highlight(in: size) == CGRect(origin: .zero, size: size))

        let open = DropZone.Target(isDraggedChat: false, draggedIsOpen: true, openCount: 4)
        #expect(
            DropZone.zone(at: CGPoint(x: 50, y: 150), in: size, kind: .chat, target: open)
                == .split(.left))
    }

    @Test func aPaneSwapsAndNothingHappensOnItself() {
        let other = DropZone.Target(isDraggedChat: false, draggedIsOpen: true, openCount: 2)
        let zone = DropZone.zone(at: CGPoint(x: 50, y: 150), in: size, kind: .pane, target: other)
        #expect(zone == .swap)
        #expect(zone.label == "Swap panes")

        let itself = DropZone.Target(isDraggedChat: true, draggedIsOpen: true, openCount: 2)
        #expect(
            DropZone.zone(at: CGPoint(x: 50, y: 150), in: size, kind: .chat, target: itself)
                == .none)
        #expect(DropZone.none.label == "")
        #expect(DropZone.none.highlight(in: size) == .zero)
    }

    /// Regression: dragging a pane over itself gave an empty highlight, and insetting an
    /// empty rect yields CGRect.null with an infinite origin, which crashed the app when
    /// SwiftUI set it as a layer position.
    @Test func theShownHighlightIsInsetAndNeverEmptyOrInfinite() {
        let size = CGSize(width: 400, height: 300)
        #expect(
            DropZone.split(.left).shownHighlight(in: size)
                == CGRect(x: 4, y: 4, width: 192, height: 292))
        #expect(DropZone.none.shownHighlight(in: size) == nil)
        #expect(DropZone.open.shownHighlight(in: CGSize(width: 6, height: 300)) == nil)
        #expect(DropZone.open.shownHighlight(in: .zero) == nil)
    }
}

/// Hit-testing a drag over the workspace by pane placements: two panes side by side
/// with a 10 pt gutter, the right one offset so points are made local to it.
@Suite struct DropHitTests {
    private let left = PanePlacement(chat: "a", frame: CGRect(x: 0, y: 0, width: 400, height: 300))
    private let right = PanePlacement(
        chat: "b", frame: CGRect(x: 410, y: 0, width: 400, height: 300))
    private var placements: [PanePlacement] { [left, right] }

    @Test func aPaneDroppedOnItselfIsANoOp() {
        let hit = DropZone.hit(
            at: CGPoint(x: 100, y: 150), placements: placements, dragged: "a", kind: .pane)
        #expect(hit == DropHit(pane: "a", zone: .none))
    }

    @Test func aPaneDroppedOnAnotherSwaps() {
        let hit = DropZone.hit(
            at: CGPoint(x: 700, y: 20), placements: placements, dragged: "a", kind: .pane)
        #expect(hit == DropHit(pane: "b", zone: .swap))
    }

    @Test func outsideEveryPaneIsNoTarget() {
        #expect(
            DropZone.hit(
                at: CGPoint(x: 405, y: 150), placements: placements, dragged: "a", kind: .pane)
                == nil)
        #expect(
            DropZone.hit(
                at: CGPoint(x: 100, y: 320), placements: placements, dragged: "a", kind: .pane)
                == nil)
        #expect(
            DropZone.hit(
                at: CGPoint(x: -1, y: 10), placements: placements, dragged: "a", kind: .pane)
                == nil)
        #expect(
            DropZone.hit(at: CGPoint(x: 10, y: 10), placements: [], dragged: "a", kind: .pane)
                == nil)
    }

    @Test func aChatSplitsTheSideOfThePaneUnderThePointer() {
        func zone(_ x: Double, _ y: Double) -> DropZone? {
            DropZone.hit(
                at: CGPoint(x: x, y: y), placements: placements, dragged: "new", kind: .chat)?
                .zone
        }
        #expect(zone(610, 20) == .split(.top))
        #expect(zone(610, 290) == .split(.bottom))
        #expect(zone(450, 150) == .split(.left))
        #expect(zone(790, 150) == .split(.right))
        #expect(zone(390, 150) == .split(.right))
    }

    @Test func aNewChatReplacesThePaneWhenFourAreOpen() {
        let size = CGSize(width: 200, height: 150)
        let full = ["a", "b", "c", "d"].enumerated().map { index, chat in
            PanePlacement(
                chat: chat,
                frame: CGRect(
                    origin: CGPoint(x: Double(index % 2) * 210, y: Double(index / 2) * 160),
                    size: size))
        }
        let hit = DropZone.hit(
            at: CGPoint(x: 300, y: 200), placements: full, dragged: "new", kind: .chat)
        #expect(hit == DropHit(pane: "d", zone: .replace))
        let open = DropZone.hit(
            at: CGPoint(x: 300, y: 230), placements: full, dragged: "a", kind: .chat)
        #expect(open == DropHit(pane: "d", zone: .split(.left)))
    }
}

@Suite struct MarkdownBlockTests {
    @Test func paragraphsAreSplitOnBlankLines() {
        let blocks = MarkdownBlock.parse("First line\nsecond line\n\n\nNext **one**")
        #expect(blocks == [.paragraph("First line\nsecond line"), .paragraph("Next **one**")])
    }

    @Test func fencedCodeKeepsItsTextAndLanguage() {
        let text = "Run this:\n```swift\nlet a = 1\n\nprint(a)\n```\nDone"
        #expect(
            MarkdownBlock.parse(text) == [
                .paragraph("Run this:"), .code(language: "swift", text: "let a = 1\n\nprint(a)"),
                .paragraph("Done"),
            ])
    }

    @Test func anUnclosedFenceRunsToTheEnd() {
        #expect(
            MarkdownBlock.parse("```\nstreaming") == [.code(language: nil, text: "streaming")])
    }

    @Test func headingsStandAlone() {
        #expect(
            MarkdownBlock.parse("## Plan\nFirst\n#nohash") == [
                .heading(level: 2, text: "Plan"), .paragraph("First\n#nohash"),
            ])
        #expect(MarkdownBlock.parse("") == [])
    }

    @Test func listLinesBecomeItemsWithTheirMarkerAndDepth() {
        let text = "Steps:\n- one\n* two\n  + nested\n    deeper\n1. first\n12) twelfth\n\nAfter"
        #expect(
            MarkdownBlock.parse(text) == [
                .paragraph("Steps:"),
                .listItem(marker: "•", level: 0, text: "one"),
                .listItem(marker: "•", level: 0, text: "two"),
                .listItem(marker: "•", level: 1, text: "nested\ndeeper"),
                .listItem(marker: "1.", level: 0, text: "first"),
                .listItem(marker: "12.", level: 0, text: "twelfth"),
                .paragraph("After"),
            ])
    }

    @Test func markerLookalikesStayParagraphText() {
        #expect(
            MarkdownBlock.parse("*bold* text\n-1 degrees\n1.5 apples\n-") == [
                .paragraph("*bold* text\n-1 degrees\n1.5 apples\n-")
            ])
    }

    @Test func aHeadingOrFenceEndsAListItem() {
        #expect(
            MarkdownBlock.parse("- item\n# Next\n- again\n```\ncode\n```") == [
                .listItem(marker: "•", level: 0, text: "item"), .heading(level: 1, text: "Next"),
                .listItem(marker: "•", level: 0, text: "again"),
                .code(language: nil, text: "code"),
            ])
    }
}

@Suite struct ToolSummaryTests {
    private func call(_ name: String, _ input: [String: JSONValue], result: String? = nil)
        -> ToolCall
    {
        ToolCall(id: "t", name: name, input: .object(input), result: result, isError: false)
    }

    @Test func kindsFollowTheToolName() {
        #expect(ToolSummary.kind(of: "Read") == .read)
        #expect(ToolSummary.kind(of: "Edit") == .edit)
        #expect(ToolSummary.kind(of: "MultiEdit") == .edit)
        #expect(ToolSummary.kind(of: "Write") == .edit)
        #expect(ToolSummary.kind(of: "NotebookEdit") == .edit)
        #expect(ToolSummary.kind(of: "Bash") == .terminal)
        #expect(ToolSummary.kind(of: "Grep") == .search)
        #expect(ToolSummary.kind(of: "Glob") == .search)
        #expect(ToolSummary.kind(of: "Task") == .agent)
        #expect(ToolSummary.kind(of: "Agent") == .agent)
        #expect(ToolSummary.kind(of: "WebFetch") == .web)
        #expect(ToolSummary.kind(of: "WebSearch") == .web)
        #expect(ToolSummary.kind(of: "TaskCreate") == .other)
        #expect(ToolSummary.kind(of: "mcp__x__y") == .other)
    }

    @Test func argumentsPickTheTellingField() {
        #expect(
            ToolSummary.argument(of: call("Bash", ["command": .string("npm test")])) == "npm test")
        #expect(
            ToolSummary.argument(
                of: call("Read", ["file_path": .string("/repo/a.ts"), "limit": .number(4)]))
                == "/repo/a.ts")
        #expect(
            ToolSummary.argument(
                of: call("Grep", ["pattern": .string("doi"), "path": .string("refs.bib")]))
                == "\"doi\" refs.bib")
        #expect(ToolSummary.argument(of: call("Grep", ["pattern": .string("doi")])) == "\"doi\"")
        #expect(
            ToolSummary.argument(
                of: call(
                    "Task",
                    ["subagent_type": .string("Explore"), "description": .string("Find DOIs")]))
                == "Explore: Find DOIs")
        #expect(
            ToolSummary.argument(of: call("Task", ["description": .string("Find DOIs")]))
                == "Find DOIs")
        #expect(
            ToolSummary.argument(of: call("WebFetch", ["url": .string("https://a.b")]))
                == "https://a.b")
        #expect(ToolSummary.argument(of: call("Other", ["count": .number(2)])) == "")
        let notObject = ToolCall(id: "t", name: "Bash", input: .null, result: nil, isError: false)
        #expect(ToolSummary.argument(of: notObject) == "")
    }

    @Test func resultsSummarizeToAShortNote() {
        // Without a result a call runs, until its turn ends without one.
        var open = call("Bash", [:])
        #expect(ToolSummary.result(of: open) == "running")
        open.stopped = true
        #expect(ToolSummary.result(of: open) == "stopped")
        var failed = call("Bash", [:], result: "exit 1")
        failed.isError = true
        #expect(ToolSummary.result(of: failed) == "failed")
        #expect(ToolSummary.result(of: call("Read", [:], result: "a\nb\nc")) == "3 lines")
        #expect(ToolSummary.result(of: call("Read", [:], result: "a")) == "1 line")
        #expect(ToolSummary.result(of: call("Edit", [:], result: "The file was updated")) == "done")
        #expect(
            ToolSummary.result(of: call("Bash", [:], result: "\n  5 passed  \nmore")) == "5 passed")
        #expect(ToolSummary.result(of: call("Bash", [:], result: " \n")) == "done")
        let long = String(repeating: "x", count: 60)
        #expect(
            ToolSummary.result(of: call("Bash", [:], result: long)) == String(long.prefix(39)) + "…"
        )
    }
}
