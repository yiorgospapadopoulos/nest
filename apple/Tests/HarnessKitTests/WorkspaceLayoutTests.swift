import CoreGraphics
import Testing

@testable import HarnessKit

private let wide = CGSize(width: 1000, height: 600)

private func row(_ id: Int, _ first: LayoutNode, _ second: LayoutNode, ratio: Double = 0.5)
    -> LayoutNode
{
    .split(id: id, direction: .row, ratio: ratio, first: first, second: second)
}

private func column(_ id: Int, _ first: LayoutNode, _ second: LayoutNode, ratio: Double = 0.5)
    -> LayoutNode
{
    .split(id: id, direction: .column, ratio: ratio, first: first, second: second)
}

private func leaf(_ id: String) -> LayoutNode { .leaf(id) }

/// a | b, with a split into a over c, and b into b over d.
private func fourPanes() -> WorkspaceLayout {
    var layout = WorkspaceLayout()
    for chat in ["a", "b", "c", "d"] {
        layout.open(chat, in: wide)
    }
    return layout
}

@Suite struct WorkspaceOpenTests {
    @Test func theFirstChatFillsTheWorkspace() {
        var layout = WorkspaceLayout()
        #expect(layout.open("a", in: wide) == .added)
        #expect(layout.root == leaf("a"))
        #expect(layout.focused == "a")
        #expect(layout.leaves == ["a"])
    }

    @Test func eachNewChatSplitsTheLargestPaneAlongItsLongerSide() {
        var layout = WorkspaceLayout()
        layout.open("a", in: wide)
        layout.open("b", in: wide)
        #expect(layout.root == row(1, leaf("a"), leaf("b")))

        // Equal panes: the first in reading order is split, and it is tall, so below.
        layout.open("c", in: wide)
        #expect(layout.root == row(1, column(2, leaf("a"), leaf("c")), leaf("b")))

        // b is now the largest pane.
        layout.open("d", in: wide)
        #expect(
            layout.root == row(1, column(2, leaf("a"), leaf("c")), column(3, leaf("b"), leaf("d"))))
        #expect(layout.leaves == ["a", "c", "b", "d"])
        #expect(layout.focused == "d")
    }

    @Test func aTallWorkspaceStacksTheSecondChat() {
        var layout = WorkspaceLayout()
        layout.open("a", in: CGSize(width: 600, height: 900))
        layout.open("b", in: CGSize(width: 600, height: 900))
        #expect(layout.root == column(1, leaf("a"), leaf("b")))
    }

    @Test func aFifthChatReplacesTheBottomRightPaneOnly() {
        var layout = fourPanes()

        #expect(layout.open("e", in: wide) == .replaced("d"))

        #expect(
            layout.root == row(1, column(2, leaf("a"), leaf("c")), column(3, leaf("b"), leaf("e"))))
        #expect(layout.focused == "e")
        let bottomRight = layout.paneFrames(in: wide).max { a, b in
            (a.frame.maxY, a.frame.maxX) < (b.frame.maxY, b.frame.maxX)
        }
        #expect(bottomRight?.chat == "e")

        #expect(layout.open("f", in: wide) == .replaced("e"))
        #expect(layout.leaves == ["a", "c", "b", "f"])
    }

    @Test func aFullWorkspaceReplacesEvenWhenMaximized() {
        var layout = fourPanes()
        layout.toggleMaximize("a")
        #expect(layout.open("e", in: wide) == .replaced("d"))
        #expect(layout.maximized == nil)
    }

    @Test func openingAnOpenChatFocusesIt() {
        var layout = fourPanes()
        let before = layout.root
        #expect(layout.open("a", in: wide) == .focused)
        #expect(layout.root == before)
        #expect(layout.focused == "a")
    }

    @Test func openingAnOpenChatWhileMaximizedShowsItMaximized() {
        var layout = fourPanes()
        layout.toggleMaximize("a")
        #expect(layout.open("c", in: wide) == .focused)
        #expect(layout.maximized == "c")
    }

    @Test func openingANewChatWhileMaximizedSplitsTheMaximizedPane() {
        var layout = WorkspaceLayout()
        layout.open("a", in: CGSize(width: 600, height: 900))
        layout.open("b", in: CGSize(width: 600, height: 900))
        layout.toggleMaximize("b")

        layout.open("c", in: CGSize(width: 600, height: 900))

        #expect(layout.root == column(1, leaf("a"), row(2, leaf("b"), leaf("c"))))
        #expect(layout.maximized == nil)
        #expect(layout.focused == "c")
    }
}

@Suite struct WorkspaceDragTests {
    @Test(arguments: [
        (DropSide.left, row(1, leaf("b"), leaf("a"))),
        (DropSide.right, row(1, leaf("a"), leaf("b"))),
        (DropSide.top, column(1, leaf("b"), leaf("a"))),
        (DropSide.bottom, column(1, leaf("a"), leaf("b"))),
    ])
    func droppingOnASideSplitsTheTarget(side: DropSide, expected: LayoutNode) {
        var layout = WorkspaceLayout()
        layout.open("a", in: wide)
        #expect(layout.drop("b", onto: "a", side: side) == .added)
        #expect(layout.root == expected)
        #expect(layout.focused == "b")
    }

    @Test func droppingAnOpenChatMovesIt() {
        var layout = WorkspaceLayout()
        layout.open("a", in: wide)
        layout.open("b", in: wide)
        layout.open("c", in: wide)

        layout.drop("b", onto: "c", side: .right)

        #expect(layout.root == column(2, leaf("a"), row(3, leaf("c"), leaf("b"))))
    }

    @Test func droppingIntoAnEmptyWorkspaceOpensTheChat() {
        var layout = WorkspaceLayout()
        #expect(layout.drop("a", onto: nil, side: .left) == .added)
        #expect(layout.root == leaf("a"))
        #expect(layout.focused == "a")
    }

    @Test func droppingANewChatOnAFullWorkspaceReplacesTheTarget() {
        var layout = fourPanes()
        #expect(layout.drop("e", onto: "c", side: .left) == .replaced("c"))
        #expect(layout.leaves == ["a", "e", "b", "d"])
        #expect(layout.focused == "e")
    }

    @Test func droppingAnOpenChatOnAFullWorkspaceStillSplits() {
        var layout = fourPanes()
        #expect(layout.drop("d", onto: "a", side: .top) == .added)
        #expect(layout.leaves == ["d", "a", "c", "b"])
    }

    @Test func meaninglessDropsChangeNothing() {
        var layout = fourPanes()
        let before = layout
        #expect(layout.drop("a", onto: "a", side: .left) == nil)
        #expect(layout.drop("e", onto: "zzz", side: .left) == nil)
        #expect(layout.drop("e", onto: nil, side: .left) == nil)
        #expect(layout == before)
    }

    @Test func swapExchangesPanes() {
        var layout = fourPanes()
        layout.swap("a", "d")
        #expect(layout.leaves == ["d", "c", "b", "a"])
        layout.swap("a", "zzz")
        #expect(layout.leaves == ["d", "c", "b", "a"])
    }

    @Test func replaceShowsAnotherChatInAPane() {
        var layout = fourPanes()
        layout.focus("c")
        layout.toggleMaximize("c")

        layout.replace("c", with: "e")

        #expect(layout.leaves == ["a", "e", "b", "d"])
        #expect(layout.focused == "e")
        #expect(layout.maximized == nil)
    }

    @Test func replaceKeepsFocusAndMaximizedElsewhere() {
        var layout = fourPanes()
        layout.toggleMaximize("a")
        layout.replace("c", with: "e")
        #expect(layout.focused == "a")
        #expect(layout.maximized == "a")
    }

    @Test func replaceWithAnOpenChatSwaps() {
        var layout = fourPanes()
        layout.replace("a", with: "b")
        #expect(layout.leaves == ["b", "c", "a", "d"])
        layout.replace("zzz", with: "e")
        #expect(layout.leaves == ["b", "c", "a", "d"])
    }
}

@Suite struct WorkspaceCloseAndResizeTests {
    @Test func removingAPaneCollapsesItsSplit() {
        var layout = fourPanes()
        layout.remove("c")
        #expect(layout.root == row(1, leaf("a"), column(3, leaf("b"), leaf("d"))))
        layout.remove("b")
        #expect(layout.root == row(1, leaf("a"), leaf("d")))
        layout.remove("zzz")
        #expect(layout.leaves == ["a", "d"])
    }

    @Test func removingTheFocusedOrMaximizedPaneMovesOn() {
        var layout = fourPanes()
        layout.toggleMaximize("d")
        layout.remove("d")
        #expect(layout.maximized == nil)
        #expect(layout.focused == "a")
        layout.toggleMaximize("b")
        layout.focus("c")
        layout.remove("a")
        #expect(layout.focused == "c")
        #expect(layout.maximized == "b")
    }

    @Test func removingTheLastPaneEmptiesTheWorkspace() {
        var layout = WorkspaceLayout()
        layout.open("a", in: wide)
        layout.remove("a")
        #expect(layout.root == nil)
        #expect(layout.focused == nil)
        #expect(layout.leaves.isEmpty)
    }

    @Test func maximizeTogglesAndRestores() {
        var layout = fourPanes()
        layout.toggleMaximize("b")
        #expect(layout.maximized == "b")
        #expect(layout.focused == "b")
        layout.toggleMaximize("b")
        #expect(layout.maximized == nil)
        layout.toggleMaximize("c")
        layout.restore()
        #expect(layout.maximized == nil)
        layout.toggleMaximize("zzz")
        layout.focus("zzz")
        #expect(layout.maximized == nil)
        #expect(layout.focused == "c")
    }

    @Test func paneFramesLeaveAGutterBetweenPanes() {
        let frames = fourPanes().paneFrames(in: wide)
        #expect(frames.map(\.chat) == ["a", "c", "b", "d"])
        #expect(frames[0].frame == CGRect(x: 0, y: 0, width: 495, height: 295))
        #expect(frames[1].frame == CGRect(x: 0, y: 305, width: 495, height: 295))
        #expect(frames[2].frame == CGRect(x: 505, y: 0, width: 495, height: 295))
        #expect(frames[3].frame == CGRect(x: 505, y: 305, width: 495, height: 295))
        #expect(WorkspaceLayout().paneFrames(in: wide).isEmpty)
    }

    @Test func placementsAndGuttersFollowTheTree() {
        var layout = fourPanes()
        layout.resize(split: 1, ratio: 0.6, in: wide)
        #expect(layout.placements(in: wide).map(\.chat) == ["a", "c", "b", "d"])
        #expect(
            layout.placements(in: wide)[0]
                == PanePlacement(chat: "a", frame: CGRect(x: 0, y: 0, width: 594, height: 295)))
        let gutters = layout.gutterFrames(in: wide)
        #expect(gutters.map(\.split) == [1, 2, 3])
        #expect(
            gutters[0]
                == GutterFrame(
                    split: 1, direction: .row, ratio: 0.6,
                    frame: CGRect(x: 594, y: 0, width: 10, height: 600), span: 990))
        #expect(
            gutters[1]
                == GutterFrame(
                    split: 2, direction: .column, ratio: 0.5,
                    frame: CGRect(x: 0, y: 295, width: 594, height: 10), span: 590))
        #expect(gutters[2].frame.minX == 604)
        #expect(WorkspaceLayout().gutterFrames(in: wide).isEmpty)
    }

    @Test func resizeKeepsPanesAboveTheirMinimumSize() throws {
        var layout = fourPanes()

        layout.resize(split: 1, ratio: 0.6, in: wide)
        #expect(
            layout.root
                == row(
                    1, column(2, leaf("a"), leaf("c")), column(3, leaf("b"), leaf("d")), ratio: 0.6)
        )

        layout.resize(split: 1, ratio: 0.05, in: wide)
        #expect(ratio(of: layout.root, split: 1) == 280.0 / 990)
        layout.resize(split: 1, ratio: 0.99, in: wide)
        #expect(ratio(of: layout.root, split: 1) == 1 - 280.0 / 990)

        layout.resize(split: 3, ratio: 0.9, in: wide)
        #expect(ratio(of: layout.root, split: 3) == 1 - 180.0 / 590)
    }

    @Test func nestedSplitsNeedRoomForAllTheirPanes() {
        var layout = WorkspaceLayout()
        layout.open("a", in: wide)
        layout.drop("b", onto: "a", side: .right)
        layout.drop("c", onto: "b", side: .right)
        layout.drop("d", onto: "a", side: .bottom)
        // Split 1 is a | (b | c): its second side needs two pane widths and a gutter.
        layout.resize(split: 1, ratio: 0.9, in: CGSize(width: 1400, height: 600))
        #expect(ratio(of: layout.root, split: 1) == 1 - 570.0 / 1390)
        // Its first side is a over d, which needs only one pane width.
        layout.resize(split: 1, ratio: 0, in: CGSize(width: 1400, height: 600))
        #expect(ratio(of: layout.root, split: 1) == 280.0 / 1390)
    }

    @Test func aTooSmallSplitSharesSpaceByMinimumSizes() {
        var layout = WorkspaceLayout()
        layout.open("a", in: wide)
        layout.open("b", in: wide)
        layout.resize(split: 1, ratio: 0.9, in: CGSize(width: 500, height: 600))
        #expect(ratio(of: layout.root, split: 1) == 0.5)
    }

    @Test func resizingAnUnknownSplitChangesNothing() {
        var layout = fourPanes()
        let before = layout
        layout.resize(split: 99, ratio: 0.2, in: wide)
        #expect(layout == before)
        var empty = WorkspaceLayout()
        empty.resize(split: 1, ratio: 0.2, in: wide)
        #expect(empty.root == nil)
    }

    private func ratio(of node: LayoutNode?, split id: Int) -> Double? {
        guard case .split(let splitID, _, let ratio, let first, let second) = node else {
            return nil
        }
        return splitID == id
            ? ratio : self.ratio(of: first, split: id) ?? self.ratio(of: second, split: id)
    }
}
